import asyncio
import base64
import json
import os
import re
import tempfile
import time
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, status
from sqlalchemy.orm import Session

from backend_fastapi.auth import get_current_user_dep
from backend_fastapi.embeddings import generate_embedding
from backend_fastapi.models import DocumentModel, TaskModel, get_db
from backend_fastapi.mcp_server import ToolCallRequest
from backend_fastapi.rag_tools import TOOL_DEFINITIONS
from backend_fastapi.schemas import (
    ApiResponse,
    ChatRequest,
    IndexDocumentsRequest,
    SearchRequest,
    SearchResult,
    WorkflowExecuteRequest,
)
from backend_fastapi.search import (
    _format_deadline_response,
    _infer_tool_from_keywords,
    _is_deadline_question,
    _semantic_intent,
    _tool_call,
    _tool_from_semantic_intent,
    resolve_task_id_from_query,
    sync_task_document,
    vector_search,
)
from backend_fastapi.mistral_client import (
    MISTRAL_API_KEY,
    MISTRAL_BASE_URL,
    VERIFY_SSL,
    check_ollama_health,
    chat_with_tools,
    generate_response,
)
import backend_fastapi.state as state
from backend_fastapi.mlflow_tracking import MLflowTracker, track_vector_search, track_workflow_execution
from backend_fastapi.langsmith_tracing import trace_workflow_execution, trace_llm_call

logger = logging.getLogger(__name__)

ai_router = APIRouter(prefix="/api/ai", tags=["ai"])
workflow_router = APIRouter(prefix="/api/workflow", tags=["workflow"])


def _extract_workflow_name(result: Optional[Dict[str, Any]]) -> str:
    """Safely extract a workflow name from a workflow result payload."""
    if not isinstance(result, dict):
        return "default"

    workflow_stages = result.get("workflow_stages")
    if isinstance(workflow_stages, list) and workflow_stages:
        first_stage = workflow_stages[0]
        if isinstance(first_stage, str) and first_stage.strip():
            return first_stage
        if first_stage is not None:
            return str(first_stage)
        return "default"

    if workflow_stages is None:
        return "default"

    if isinstance(workflow_stages, (str, int, float, bool)):
        return str(workflow_stages)

    return "default"


def _parse_tasks_from_ocr_text(ocr_text: str, user_prompt: str) -> List[Dict[str, str]]:
    """Convert OCR text into a list of task dictionaries with titles and descriptions."""
    if not ocr_text:
        return []

    cleaned_lines: List[str] = []
    for line in ocr_text.splitlines():
        normalized = re.sub(r"\s+", " ", line).strip()
        if normalized:
            cleaned_lines.append(normalized)
    if not cleaned_lines:
        return []
    cleaned = "\n".join(cleaned_lines)

    def _is_valid_task_title(title: str) -> bool:
        if not title:
            return False
        normalized = title.strip()
        if len(normalized) < 3:
            return False
        if normalized in {"{", "}", "[", "]"}:
            return False
        if re.fullmatch(r"[\W_]+", normalized):
            return False
        if len(re.findall(r"[A-Za-z0-9]", normalized)) < 2:
            return False
        # Reject code/formatting artifacts
        if normalized.lower() in {"json", "```", "```json", "code", "yaml", "xml", "markdown"}:
            return False
        return True

    def _strip_label(text: str) -> str:
        cleaned = re.sub(r"^#+\s*", "", str(text or "").strip())
        cleaned = re.sub(r"^['\"]?(title|description)['\"]?\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" ,")
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'\"', "'"}:
            cleaned = cleaned[1:-1].strip()
        return cleaned.strip(" `\t")

    def _strip_description_label(text: str) -> str:
        return _strip_label(re.sub(r"^(description|desc)\s*:\s*", "", str(text or ""), flags=re.IGNORECASE))

    def _clean_field(text: str, field_name: str = "") -> str:
        """Remove OCR/LLM formatting from a task field while preserving its text."""
        cleaned = str(text or "").strip()
        cleaned = re.sub(r"^#+\s*", "", cleaned)
        if field_name:
            cleaned = re.sub(
                rf"^['\"]?{field_name}['\"]?\s*:\s*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            ).strip()
        cleaned = re.sub(r"^(title|description|desc)\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = cleaned.strip(" ,")
        if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'\"', "'"}:
            cleaned = cleaned[1:-1].strip()
        return cleaned.strip(" `\t")

    def _description_from_entry(entry: Dict[str, Any], title: str = "") -> str:
        description_fields: List[str] = []
        for key in ["description", "details", "notes", "assigned to", "deadline", "status"]:
            value = entry.get(key)
            if value:
                text = _strip_description_label(str(value).strip())
                if text:
                    description_fields.append(text)
        if description_fields:
            return " | ".join(description_fields)
        if title:
            return f"{title}."
        return ""

    def _split_title_description(raw: str) -> tuple[str, str]:
        raw = raw.strip()
        if not raw:
            return "", ""

        # Remove task ID if present at the start.
        raw = re.sub(r"(?i)^(task\s*id\s*[:\-]?\s*)?([A-Z]-?\d+)\s+", "", raw).strip()

        metadata: List[str] = []
        for label in ["assigned to", "deadline", "status"]:
            match = re.search(rf"(?i)\b{label}\s*[:\-]?\s*([^|,;]+)", raw)
            if match:
                metadata.append(f"{label.title()}: {match.group(1).strip()}")
                raw = (raw[: match.start()] + raw[match.end() :]).strip()

        raw = re.sub(r"\s{2,}", "  ", raw).strip()

        verb_split = re.split(
            r"\s+(?=(Meet|Develop|Create|Implement|Add|Conduct|Deploy|Prepare|Finalize|Review|Draft|Update|Test|Design|Research|Write|Build|Launch|Coordinate|Plan)\b)",
            raw,
            maxsplit=1,
            flags=re.IGNORECASE,
        )
        if len(verb_split) == 2:
            title = _strip_label(verb_split[0])
            description = _strip_label(verb_split[1])
            if metadata:
                description = " | ".join([description] + metadata)
            return title, description

        if "  " in raw:
            title_part, description_part = raw.split("  ", 1)
            title = _strip_label(title_part)
            description = _strip_label(description_part)
            if metadata:
                description = " | ".join([description] + metadata)
            return title, description

        if metadata:
            return raw, " | ".join(metadata)
        return raw, ""

    def _row_to_task(row: List[str]) -> Optional[Dict[str, str]]:
        if not row:
            return None

        title = ""
        description = ""

        if len(row) == 1:
            raw = row[0].strip()
            parts = re.split(r"\s*\|\s*", raw)
            description_parts: List[str] = []
            if len(parts) == 1:
                title, description = _split_title_description(raw)
            else:
                for part in parts:
                    match = re.match(r"^(task id|title|description|assigned to|deadline)\s*:\s*(.+)$", part, flags=re.IGNORECASE)
                    if match:
                        key = match.group(1).strip().lower()
                        value = match.group(2).strip()
                        if key == "title":
                            title = value
                        elif key == "description":
                            description_parts.append(value)
                        elif key in {"assigned to", "deadline"}:
                            description_parts.append(f"{match.group(1).strip()}: {value}")
                        else:
                            # Skip task id and other non-description fields.
                            continue
                    else:
                        if not title:
                            title = _strip_label(part)
                        else:
                            description_parts.append(_strip_label(part))
                title = _strip_label(title)
                description = " | ".join([_strip_label(part) for part in description_parts if part.strip()])
            if not title and description:
                title, fallback_description = _split_title_description(raw)
                if title and fallback_description:
                    description = fallback_description
        else:
            title = _strip_label(row[0].strip())
            description_parts = [row[1].strip() for row in row[1:] if row[1].strip()]
            description = " | ".join([_strip_label(part) for part in description_parts])

        if not title and description:
            title = description[:120]
        if not description and title:
            # Preserve a description even when the row only included title-like text.
            description = title
        if not title or not _is_valid_task_title(title):
            return None
        return {"title": title[:120], "description": description[:1000]}

    def _parse_markdown_task_table(lines: List[str]) -> List[Dict[str, str]]:
        """Parse task tables without allowing the LLM to change column meaning."""
        header_index = -1
        header_cells: List[str] = []
        for index, line in enumerate(lines):
            if "|" not in line:
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            normalized = [re.sub(r"\s+", " ", cell).lower() for cell in cells]
            if "task name" in normalized and "description" in normalized:
                header_index = index
                header_cells = normalized
                break

        if header_index < 0:
            return []

        title_index = header_cells.index("task name")
        description_index = header_cells.index("description")
        assigned_index = header_cells.index("assigned to") if "assigned to" in header_cells else -1
        deadline_index = header_cells.index("deadline") if "deadline" in header_cells else -1
        tasks: List[Dict[str, str]] = []

        for line in lines[header_index + 1:]:
            if "|" not in line:
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not cells or all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
                continue
            if max(title_index, description_index, assigned_index, deadline_index) >= len(cells):
                continue

            title = _clean_field(cells[title_index], "title")
            if not _is_valid_task_title(title):
                continue
            description_parts = [_clean_field(cells[description_index], "description")]
            if assigned_index >= 0 and cells[assigned_index]:
                description_parts.append(f"Assigned To: {_clean_field(cells[assigned_index])}")
            if deadline_index >= 0 and cells[deadline_index]:
                description_parts.append(f"Deadline: {_clean_field(cells[deadline_index])}")
            description = " | ".join(part for part in description_parts if part)
            tasks.append({"title": title[:120], "description": description[:1000] or title})

        return tasks

    def _line_has_table_fields(line: str) -> bool:
        return bool(re.search(r"\b(task id|assigned to|deadline|description|task name)\b", line, re.IGNORECASE))

    def _is_irrelevant_line(line: str) -> bool:
        normalized = line.strip().lower()
        if not normalized:
            return True
        if normalized in {"{", "}", "[", "]"}:
            return True
        if re.match(r"page\s*\d+", normalized) or re.match(r"\d+\s*/\s*\d+", normalized):
            return True
        if "notes" in normalized and "dependencies" in normalized:
            return True
        if any(keyword in normalized for keyword in ["generated by", "confidential", "draft", "page", "note:"]):
            return True
        header_fields = ["task id", "task name", "description", "assigned to", "deadline"]
        if sum(1 for field in header_fields if field in normalized) >= 3:
            return True
        if re.search(r"^(table|task list|project plan|notes)", normalized):
            return True
        return False

    def _merge_title_lines(lines: List[str]) -> List[str]:
        merged: List[str] = []
        pending: Optional[str] = None
        for line in lines:
            if _is_irrelevant_line(line):
                continue
            if pending and _line_has_table_fields(line) and not _line_has_table_fields(pending):
                merged.append(f"{pending} | {line}")
                pending = None
                continue
            if pending:
                merged.append(pending)
            pending = line
        if pending:
            merged.append(pending)
        return merged

    def _split_into_task_segments(line: str) -> List[str]:
        header_match = re.search(
            r"(?i)(task\s*id.*task\s*name.*description.*assigned\s*to.*deadline)",
            line,
        )
        if header_match:
            line = line[header_match.end() :].strip()

        segments = re.split(
            r'(?=(?:T[-\s]?\d{1,4}\b|\b\d{1,4}-\d{1,4}\b|\bTask\s*ID\b))',
            line,
        )
        segments = [seg.strip(" .,:;|\t") for seg in segments if seg.strip(" .,:;|\t")]
        if len(segments) > 1:
            return segments

        deadline_split = re.split(
            r'(?=(?:\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b))',
            line,
        )
        deadline_split = [seg.strip(" .,:;|\t") for seg in deadline_split if seg.strip(" .,:;|\t")]
        if len(deadline_split) > 1:
            return deadline_split

        return [line]

    def _extract_numbered_rows(lines: List[str]) -> List[List[str]]:
        """Turn lines with leading serial numbers into rows [title, description].

        Example:
        1. Title line
        Description line

        becomes [["Title line", "Description line"]]
        """
        numbered: List[List[str]] = []
        i = 0
        
        # Check if we have numbered items at all
        has_numbers = any(re.match(r"^\s*\d+[\)\.\-:]\s*", line.strip()) for line in lines)
        if not has_numbers:
            return []
        
        while i < len(lines):
            ln = lines[i].strip()
            m = re.match(r"^\s*(\d+)[\)\.\-:]\s*(.*)$", ln)
            
            if m:
                title_text = m.group(2).strip()
                if not title_text:  # Skip if number has no title
                    i += 1
                    continue
                    
                description = ""
                # Collect all following non-numbered lines as description
                desc_lines = []
                j = i + 1
                while j < len(lines):
                    nxt = lines[j].strip()
                    if not nxt:  # Skip empty lines
                        j += 1
                        continue
                    if re.match(r"^\s*\d+[\)\.\-:]\s*", nxt):  # Next numbered item
                        break
                    desc_lines.append(nxt)
                    j += 1
                
                if desc_lines:
                    description = " ".join(desc_lines)
                    i = j
                else:
                    i += 1
                
                if description:
                    numbered.append([title_text, description])
                else:
                    numbered.append([title_text])
            else:
                i += 1
        
        return numbered

    def _split_rows(lines: List[str]) -> List[List[str]]:
        rows: List[List[str]] = []
        for line in lines:
            normalized = line.strip()
            if not normalized or _is_irrelevant_line(normalized):
                continue
            segments = _split_into_task_segments(normalized)
            for segment in segments:
                if re.search(r"\t|\s{2,}", segment):
                    cells = re.split(r"\t|\s{2,}", segment)
                    rows.append([cell.strip() for cell in cells if cell.strip()])
                else:
                    rows.append([segment])
        return rows

    table_tasks = _parse_markdown_task_table(cleaned_lines)
    if table_tasks:
        return table_tasks

    prompt = (
        "You are an OCR text cleaner and task extractor. "
        "The input is noisy OCR output from a PDF or image of a task table. "
        "Return only valid JSON, never plain text. "
        "Produce a JSON array of objects, one object per task row. "
        "Each object must include exactly these fields: title, description. "
        "The title should be concise and capture the main task. "
        "The description should include all supplementary text from that row, including details, notes, task id, assigned to, and deadline. "
        "If the row contains a title but no explicit description, use the remaining row text as description. "
        "If a row has a title and separated metadata (Assigned To, Deadline), include all metadata in description. "
        "If the text contains a header row or multiple tasks on one line, ignore the header and split into distinct tasks. "
        "Do not omit description. Do not output markdown, YAML, XML, tables, or comments. "
        "Use double quotes only around JSON keys and values. "
        "Example output format: [{\"title\":\"Requirements Gathering\",\"description\":\"Meet with stakeholders to collect design, functionality, and branding needs. Assigned To: Priya Sharma | Deadline: 25 July 2026\"}]" 
        f"User request: {user_prompt}.\n\nDocument text:\n{cleaned[:12000]}"
    )

    try:
        llm_payload = generate_response(prompt, temperature=0.0)
        if llm_payload:
            stripped = llm_payload.strip()
            if stripped.startswith("[") or stripped.startswith("{"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        tasks = []
                        for entry in parsed:
                            if not isinstance(entry, dict):
                                continue
                            title = _clean_field(str(entry.get("title") or ""), "title")
                            description = _clean_field(str(entry.get("description") or ""), "description")
                            if title and not description:
                                description = _description_from_entry(entry, title=title)
                            if title:
                                tasks.append({"title": title[:120], "description": description[:1000]})
                        if tasks:
                            return tasks
                    elif isinstance(parsed, dict):
                        title = _clean_field(str(parsed.get("title") or ""), "title")
                        description = _clean_field(str(parsed.get("description") or ""), "description")
                        if title and not description:
                            description = _description_from_entry(parsed, title=title)
                        if title:
                            return [{"title": title[:120], "description": description[:1000]}]
                except Exception:
                    pass

            # Retry once with a stricter JSON-only prompt if the LLM output was not parseable.
            if not (stripped.startswith("[") or stripped.startswith("{")):
                strict_prompt = prompt + "\n\nIf you cannot return clean JSON, return an empty JSON array [] instead."
                llm_payload = generate_response(strict_prompt, temperature=0.0)
                stripped = llm_payload.strip() if llm_payload else ""
                if stripped.startswith("[") or stripped.startswith("{"):
                    try:
                        parsed = json.loads(stripped)
                        if isinstance(parsed, list):
                            tasks = []
                            for entry in parsed:
                                if not isinstance(entry, dict):
                                    continue
                                title = _clean_field(str(entry.get("title") or ""), "title")
                                description = _clean_field(str(entry.get("description") or ""), "description")
                                if title and not description:
                                    description = _description_from_entry(entry, title=title)
                                if title:
                                    tasks.append({"title": title[:120], "description": description[:1000]})
                            if tasks:
                                return tasks
                        elif isinstance(parsed, dict):
                            title = _clean_field(str(parsed.get("title") or ""), "title")
                            description = _clean_field(str(parsed.get("description") or ""), "description")
                            if title and not description:
                                description = _description_from_entry(parsed, title=title)
                            if title:
                                return [{"title": title[:120], "description": description[:1000]}]
                    except Exception:
                        pass

            lines = [line.strip(" -•\t") for line in stripped.splitlines() if line.strip()]
            
            # Try numbered rows format (1. Title / Description / 2. Title / Description)
            numbered_rows = _extract_numbered_rows(lines)
            tasks = [task for row in numbered_rows if (task := _row_to_task(row))]
            if tasks:
                return tasks
            
            lines = _merge_title_lines(lines)
            rows = _split_rows(lines)
            tasks = [task for row in rows if (task := _row_to_task(row))]
            if tasks:
                return tasks
    except Exception:
        pass

    lines = [line.strip(" -•\t") for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return []

    # Try numbered rows format first
    numbered_rows = _extract_numbered_rows(lines)
    tasks = [task for row in numbered_rows if (task := _row_to_task(row))]
    if tasks:
        return tasks
    
    lines = _merge_title_lines(lines)
    rows = _split_rows(lines)
    tasks = [task for row in rows if (task := _row_to_task(row))]
    if tasks:
        return tasks

    candidates: List[str] = []
    for line in lines:
        normalized = re.sub(r"\s+", " ", line).strip()
        if len(normalized) < 4:
            continue
        if normalized.lower().startswith(("title:", "description:", "note:", "summary:")):
            continue
        if normalized.lower().startswith(("task list", "todo list", "tasks:")):
            continue
        if normalized.lower() in {"-", "•", "*"}:
            continue
        candidates.append(normalized)

    if not candidates:
        candidates = [cleaned]

    tasks = []
    for item in candidates[:20]:
        title = re.sub(r"\s+", " ", item).strip()
        if re.match(r"^(\d+|[a-z]|[ivx]+)[\).\-:]\s+", title, flags=re.IGNORECASE):
            title = re.sub(r"^(\d+|[a-z]|[ivx]+)[\).\-:]\s+", "", title, flags=re.IGNORECASE)
        title = _strip_label(title).strip()
        if not title:
            continue
        tasks.append({"title": title[:120], "description": title[:1000]})

    if not tasks:
        tasks.append({"title": "Extracted task", "description": user_prompt or cleaned[:500]})

    return tasks


def _mistral_ocr_file(file_path: str, suffix: str) -> str:
    """Extract text from a PDF or image using Mistral OCR."""
    if not MISTRAL_API_KEY:
        return ""

    try:
        import requests

        with open(file_path, "rb") as input_file:
            encoded_file = base64.b64encode(input_file.read()).decode("ascii")

        is_pdf = suffix.lower() == ".pdf"
        mime_type = "application/pdf" if is_pdf else {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".bmp": "image/bmp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(suffix.lower(), "application/octet-stream")
        document_type = "document_url" if is_pdf else "image_url"
        document_url = f"data:{mime_type};base64,{encoded_file}"

        response = requests.post(
            f"{MISTRAL_BASE_URL}/ocr",
            headers={
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "mistral-ocr-latest",
                "document": {
                    "type": document_type,
                    document_type: document_url,
                },
            },
            timeout=90,
            verify=VERIFY_SSL,
        )
        response.raise_for_status()
        payload = response.json()
        pages = payload.get("pages", [])
        return "\n\n".join(
            page.get("markdown", "")
            for page in pages
            if isinstance(page, dict) and page.get("markdown")
        ).strip()
    except Exception as exc:
        logger.warning("Mistral OCR failed: %s", exc)
        return ""


def _format_verified_task_response(tool_calls: List[dict]) -> Optional[str]:
    if len(tool_calls) != 1:
        return None

    tool_call = tool_calls[0]
    tool_name = tool_call.get("name")
    result = tool_call.get("result")
    if tool_name == "list_tasks" and isinstance(result, list):
        tasks = [task for task in result if isinstance(task, dict) and not task.get("error")]
        if not tasks:
            return "No matching tasks found."
        return "Pending tasks:\n" + "\n".join(
            f"{index}. Task ID: {task.get('id')} — {task.get('title', 'Untitled task')}"
            for index, task in enumerate(tasks, start=1)
        )

    if tool_name == "sort_tasks_by_time" and isinstance(result, dict):
        tasks = result.get("tasks")
        if not isinstance(tasks, list):
            return None
        if not tasks:
            return "No pending tasks found to prioritize."
        return "Pending tasks, prioritized by due date and urgency:\n" + "\n".join(
            f"{index}. Task ID: {task.get('id')} — {task.get('title', 'Untitled task')} "
            f"({task.get('priority_reason', 'No priority reason available')})"
            for index, task in enumerate(tasks, start=1)
        )

    if tool_name == "get_task_stats" and isinstance(result, dict) and not result.get("error"):
        return (
            f"Task summary: {result.get('total_tasks', 0)} total, "
            f"{result.get('pending', 0)} pending, {result.get('completed', 0)} completed."
        )

    return None


async def _run_chat_agent(message: str, context: Optional[str] = None, tool_results: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Route chat through coordinator agent if available, otherwise fall back to direct chat."""
    if state.agent_manager is None:
        return None

    preferred_agent = "coordinator_001" if state.agent_manager.get_agent("coordinator_001") else "chat_agent_001"
    payload = {
        "operation": "orchestrate_message" if preferred_agent == "coordinator_001" else "send_message",
        "message": message,
        "context": context,
        "tool_results": tool_results,
    }

    try:
        result = await state.agent_manager.execute_task(preferred_agent, payload)
        if result.get("status") == "success":
            response_value = result.get("response")
            if isinstance(response_value, dict):
                response_value = response_value.get("response", response_value)
            if isinstance(response_value, str) and response_value.strip():
                return {"status": "success", "response": response_value}
    except Exception:
        pass

    try:
        response = await chat_with_tools(
            user_message=message,
            context=context,
            tool_results=tool_results,
            force_natural=True,
        )
        return {"status": "success", "response": response}
    except Exception:
        return None


@ai_router.get("/health/")
async def ai_health():
    llm_available = await check_ollama_health()

    agent_system = {
        "initialized": state.agent_manager is not None,
        "total_agents": len(state.agent_manager.agents) if state.agent_manager is not None else 0,
        "agents": [agent.get_status() for agent in state.agent_manager.agents.values()] if state.agent_manager is not None else [],
    }

    return ApiResponse(
        success=True,
        data={
            "llm_provider": "mistral" if llm_available else "fallback",
            "embeddings": True,
            "status": "ready" if llm_available else "fallback_only",
            "agent_system": agent_system,
        },
    )


@ai_router.post("/search/", response_model=ApiResponse)
async def search_documents(payload: SearchRequest, request: Request, db: Session = Depends(get_db)):
    start_time = time.time()
    with MLflowTracker("vector_search", tags={"type": "search", "operation": "vector_search"}):
        user = await get_current_user_dep(request)
        query_embedding = await asyncio.get_event_loop().run_in_executor(None, generate_embedding, payload.query)
        documents = vector_search(db, query_embedding, limit=payload.limit if hasattr(payload, 'limit') else 5)
        ranked_results = [
            SearchResult(
                id=doc["id"],
                title=doc["title"],
                content=doc["content"][:200],
                similarity_score=doc["similarity_score"],
            )
            for doc in documents
            if doc["similarity_score"] >= 0.08
        ]
        
        # Track metrics
        execution_time = time.time() - start_time
        track_vector_search(
            query=payload.query,
            results_count=len(ranked_results),
            similarity_threshold=0.08
        )
        trace_workflow_execution(
            workflow_name="vector_search",
            user_input=payload.query,
            execution_time=execution_time
        )
        
    return ApiResponse(success=True, data=ranked_results)


@ai_router.post("/index/", response_model=ApiResponse)
async def index_documents(payload: IndexDocumentsRequest, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_dep(request)
    user_roles = [role["name"] for role in getattr(user, "_roles_cache", [])] if hasattr(user, "_roles_cache") else [role.role.name for role in user.roles]
    if "admin" not in user_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can index documents")

    query = db.query(TaskModel)
    if payload.task_ids:
        query = query.filter(TaskModel.id.in_(payload.task_ids))

    tasks = query.all()
    indexed_count = 0

    for task in tasks:
        db.query(DocumentModel).filter(DocumentModel.task_id == task.id).delete()
        content = f"{task.title}\n{task.description}"
        embedding = await asyncio.get_event_loop().run_in_executor(None, generate_embedding, content)
        doc = DocumentModel(task_id=task.id, title=task.title, content=content, embedding=embedding)
        db.add(doc)
        indexed_count += 1

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    return ApiResponse(success=True, data={"indexed_count": indexed_count}, message=f"Indexed {indexed_count} documents")


@ai_router.post("/chat/", response_model=ApiResponse)
async def ai_chat(payload: ChatRequest, request: Request, db: Session = Depends(get_db)):
    start_time = time.time()
    with MLflowTracker("ai_chat", tags={"type": "ai_request", "operation": "chat"}):
        user = await get_current_user_dep(request)
        response_data = {"message": payload.message, "context": None, "tool_calls": None, "response": ""}

        context_docs = []
        context_text = ""
        if payload.use_context:
            query_embedding = await asyncio.get_event_loop().run_in_executor(None, generate_embedding, payload.message)
            context_docs = vector_search(db, query_embedding, limit=3)
            context_docs = [doc for doc in context_docs if doc["similarity_score"] >= 0.2]
            context_text = "\n\n".join([f"- {doc['title']}: {doc['content'][:150]}" for doc in context_docs])
            if context_docs:
                response_data["context"] = [
                    SearchResult(
                        id=doc["id"],
                        title=doc["title"],
                        content=doc["content"][:200],
                        similarity_score=doc["similarity_score"],
                    )
                    for doc in context_docs
                ]

        tool_results_text = ""
        tool_calls: List[dict] = []
        if payload.use_tools:
            message_lower = payload.message.lower()
            if _is_deadline_question(payload.message):
                task_id = resolve_task_id_from_query(payload.message, db=db, candidate_docs=context_docs)
                if task_id is not None:
                    tool_results_text = _tool_call(db, "get_task_details", {"task_id": task_id}, tool_calls)
                    parsed_result = tool_calls[-1]["result"]
                    if isinstance(parsed_result, dict) and not parsed_result.get("error"):
                        tool_results_text = _format_deadline_response(parsed_result)
                    else:
                        tool_results_text = "I found a matching task, but I could not read its due date."
                else:
                    tool_results_text = "I could not identify a matching task to check the deadline."
            else:
                semantic_intent, semantic_score = _semantic_intent(payload.message)
                tool_name, tool_args = _tool_from_semantic_intent(semantic_intent, payload.message, db, candidate_docs=context_docs) if semantic_score >= 0.55 else (None, None)
                if tool_name is None:
                    tool_name, tool_args = _infer_tool_from_keywords(message_lower, payload.message, db, candidate_docs=context_docs)
                if tool_name is not None and tool_args is not None:
                    tool_results_text = _tool_call(db, tool_name, tool_args, tool_calls)

        if tool_calls:
            response_data["tool_calls"] = tool_calls

        verified_response = _format_verified_task_response(tool_calls)
        if verified_response is not None:
            response_data["response"] = verified_response
        else:
            agent_response = await _run_chat_agent(payload.message, context_text if payload.use_context else None, tool_results_text if tool_results_text else None)
            if not agent_response or not agent_response.get("response"):
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Agent chat pipeline is not available")
            response_data["response"] = agent_response["response"]
        
        # Track metrics
        execution_time = time.time() - start_time
        trace_llm_call(
            model="mistral",
            prompt=payload.message,
            response=response_data["response"],
        )
        trace_workflow_execution(
            workflow_name="ai_chat",
            user_input=payload.message,
            execution_time=execution_time,
            agent_count=len(tool_calls)
        )
        
    return ApiResponse(success=True, data=response_data)


@ai_router.get("/tools/")
def list_tools():
    return ApiResponse(success=True, data=TOOL_DEFINITIONS)


@workflow_router.post("/execute")
async def execute_workflow(request_payload: WorkflowExecuteRequest, request: Request):
    start_time = time.time()
    with MLflowTracker("workflow_execution", tags={"type": "workflow", "operation": "execute"}):
        user = await get_current_user_dep(request)
        if state.langraph_workflow is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="LangGraph workflow not initialized")

        context = request_payload.context or {}
        context["user_id"] = user.id
        context["user_email"] = user.email

        previous_memory = state.workflow_memory_cache.get(user.id)
        incoming_memory = context.get("workflow_memory")
        # Merge previous cached memory with incoming memory without allowing
        # explicit None/empty incoming values to overwrite existing cached fields.
        if isinstance(previous_memory, dict) and isinstance(incoming_memory, dict):
            merged = previous_memory.copy()
            for k, v in incoming_memory.items():
                # Only overwrite when incoming value is not None; preserve cached otherwise
                if v is not None:
                    merged[k] = v
            context["workflow_memory"] = merged
        elif isinstance(previous_memory, dict):
            context["workflow_memory"] = previous_memory.copy()
        elif isinstance(incoming_memory, dict):
            context["workflow_memory"] = incoming_memory.copy()

        result = await state.langraph_workflow.execute_workflow(user_input=request_payload.input, task_context=context)

        result_memory = result.get("workflow_memory")
        to_cache = None
        if isinstance(result_memory, dict):
            to_cache = result_memory
        else:
            ctx_mem = context.get("workflow_memory")
            if isinstance(ctx_mem, dict):
                to_cache = ctx_mem
            elif isinstance(previous_memory, dict):
                to_cache = previous_memory.copy()

        if isinstance(to_cache, dict):
            state.workflow_memory_cache[user.id] = to_cache

        # Track workflow execution
        execution_time = time.time() - start_time
        workflow_name = _extract_workflow_name(result)
        agent_messages = result.get("agents_used", [])
        trace_workflow_execution(
            workflow_name=workflow_name,
            user_input=request_payload.input,
            agent_messages=agent_messages,
            execution_time=execution_time,
        )
        track_workflow_execution(
            workflow_name=workflow_name,
            input_text=request_payload.input,
            execution_time=execution_time,
            agent_count=len(agent_messages),
        )

    return ApiResponse(
        success=True,
        data={
            "status": result.get("status"),
            "result": result.get("result"),
            "response": result.get("response"),
            "workflow_stages": result.get("workflow_stages"),
            "agents_used": result.get("agents_used"),
            "task_id": result.get("task_id"),
            "workflow_memory": result.get("workflow_memory"),
        },
        message="Workflow executed successfully" if result.get("status") == "success" else result.get("error"),
    )


@workflow_router.post("/upload")
async def upload_workflow_file(
    request: Request,
    file: UploadFile = File(...),
    prompt: str = Form(default="Create tasks from this document"),
    db: Session = Depends(get_db),
):
    user = await get_current_user_dep(request)
    if state.mcp_server is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="MCP server not initialized")

    if not file or not getattr(file, "filename", None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file uploaded")

    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".txt", ".md", ".docx"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".bin") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        extraction_note = ""
        if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".pdf"}:
            try:
                from PIL import Image
            except Exception as exc:
                if suffix != ".pdf":
                    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Image OCR dependencies unavailable: {exc}")

            ocr_text = ""
            if suffix == ".pdf":
                try:
                    import pypdf
                    reader = pypdf.PdfReader(tmp_path)
                    pages = [page.extract_text() or "" for page in reader.pages]
                    ocr_text = "\n\n".join(page for page in pages if page)
                    if ocr_text:
                        extraction_note = "Extracted embedded PDF text"
                    else:
                        extraction_note = "No embedded text found in PDF; attempting OCR"
                except Exception as exc:
                    logger.warning("PDF text extraction failed, falling back to OCR: %s", exc)
                    extraction_note = "PDF text extraction failed; attempting OCR"
                    ocr_text = ""
            if not ocr_text:
                ocr_text = _mistral_ocr_file(tmp_path, suffix)
                if ocr_text:
                    extraction_note = "OCR extracted text using Mistral OCR"
            if not ocr_text:
                try:
                    import easyocr
                    import cv2
                    import numpy as np
                    import ssl
                    
                    # Disable SSL verification to allow model downloads if needed
                    ssl._create_default_https_context = ssl._create_unverified_context
                    
                    # Use cached model directory if available
                    model_dir = os.environ.get('EASYOCR_HOME', None)
                    
                    # Initialize EasyOCR reader (lazy initialization, cached by library)
                    logger.info(f"Initializing EasyOCR with model_storage_directory={model_dir}")
                    reader = easyocr.Reader(['en'], gpu=False, verbose=False, model_storage_directory=model_dir)
                    
                    # Read image using OpenCV for better compatibility
                    if suffix == ".pdf":
                        img = Image.open(tmp_path)
                        img_array = np.array(img)
                    else:
                        img_array = cv2.imread(tmp_path)
                        if img_array is None:
                            img = Image.open(tmp_path)
                            img_array = np.array(img)
                    
                    # Preprocess image for better handwriting OCR
                    def preprocess_image(img_arr):
                        """Enhance image for better OCR results."""
                        if len(img_arr.shape) == 3 and img_arr.shape[2] == 3:
                            gray = cv2.cvtColor(img_arr, cv2.COLOR_BGR2GRAY)
                        else:
                            gray = img_arr
                        
                        # Apply bilateral filter to reduce noise while keeping edges sharp
                        filtered = cv2.bilateralFilter(gray, 9, 75, 75)
                        
                        # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
                        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                        enhanced = clahe.apply(filtered)
                        
                        # Threshold to binary (helps with handwriting)
                        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                        
                        return binary
                    
                    processed_img = preprocess_image(img_array)
                    logger.info(f"Preprocessed image from shape {img_array.shape} to {processed_img.shape}")
                    
                    # Run OCR on preprocessed image
                    logger.info(f"Starting OCR on preprocessed image")
                    result = reader.readtext(processed_img)
                    logger.info(f"OCR returned {len(result)} text regions")
                    
                    # Extract text from EasyOCR result (list of [bbox, text, confidence])
                    if result:
                        texts = [line[1] for line in result if line and len(line) > 1]
                        ocr_text = "\n".join(texts)
                        logger.info(f"Extracted {len(texts)} text lines, total length: {len(ocr_text)}")
                    
                    if ocr_text.strip():
                        extraction_note = "OCR extracted text using EasyOCR"
                    else:
                        extraction_note = "OCR completed but produced no readable text"
                        
                except ImportError as exc:
                    logger.error(f"EasyOCR or dependencies not installed: {exc}")
                    extraction_note = "OCR unavailable in this PyTorch-free deployment"
                    ocr_text = ""
                except Exception as exc:
                    logger.error(f"EasyOCR processing failed: {type(exc).__name__}: {exc}", exc_info=True)
                    extraction_note = f"OCR failed: {type(exc).__name__}"
                    ocr_text = ""
        else:
            with open(tmp_path, "r", encoding="utf-8", errors="ignore") as handle:
                ocr_text = handle.read()
            extraction_note = "Read text file directly"

        os.unlink(tmp_path)

        logger.info(f"Extracted OCR text ({len(ocr_text)} chars): {ocr_text[:500]}")
        
        # For short OCR outputs (typical for handwritten documents), always use LLM to clean up
        # since handwriting OCR is often garbled with character substitutions
        if ocr_text and 50 < len(ocr_text) < 500:  # Typical handwritten task list size
            logger.info(f"Short OCR output detected. Using LLM to reconstruct and clean text...")
            try:
                clean_prompt = (
                    "The following is OCR output from a handwritten document with numbered tasks (1., 2., 3., etc). "
                    "The OCR likely has character recognition errors from handwriting. "
                    "Please reconstruct the original text, correcting obvious OCR mistakes and keeping the numbered format. "
                    "Fix common errors like: 'tbe'→'the', 'tenplete'→'template', 'derkug'→'working', etc. "
                    "IMPORTANT: Do NOT include field labels like 'title:', 'description:', 'json', or any JSON formatting. "
                    "Return ONLY the reconstructed plain text with numbered items. Do NOT use markdown, code blocks, or special formatting.\n\n"
                    f"OCR text:\n{ocr_text}"
                )
                cleaned_text = generate_response(clean_prompt, temperature=0.1)
                if cleaned_text and len(cleaned_text) > 30:
                    # Remove markdown code blocks and artifacts
                    cleaned_text = cleaned_text.replace('```json', '').replace('```', '').replace('**', '').strip()
                    # Remove any remaining "title:" or "description:" labels from LLM output
                    cleaned_text = re.sub(r'["\']?(title|description)["\']?\s*:\s*', '', cleaned_text, flags=re.IGNORECASE)
                    # Remove any remaining JSON-like structures
                    cleaned_text = re.sub(r'[\{\}\[\],]', '', cleaned_text)
                    logger.info(f"LLM reconstructed text ({len(cleaned_text)} chars): {cleaned_text[:500]}")
                    ocr_text = cleaned_text
            except Exception as e:
                logger.warning(f"LLM reconstruction failed: {e}")
        
        tasks = _parse_tasks_from_ocr_text(ocr_text, prompt)
        logger.info(f"Parsed tasks: {tasks}")
        created_tasks = []
        for task in tasks:
            request_obj = ToolCallRequest(
                tool_name="create_task",
                arguments={"title": task["title"], "description": task["description"]},
            )
            result = await state.mcp_server.call_tool(request_obj)
            if result.success:
                created_tasks.append({"title": task["title"], "description": task["description"], "result": result.result})
            else:
                created_tasks.append({"title": task["title"], "description": task["description"], "error": result.error})

        response_text = (
            f"Processed file '{file.filename}'. Extracted {len(tasks)} task candidate(s) and created {len(created_tasks)} task(s) via MCP. "
            f"Extraction note: {extraction_note or 'No extraction note available.'}"
        )
        return ApiResponse(
            success=True,
            data={
                "status": "success",
                "response": response_text,
                "tasks_created": created_tasks,
                "extracted_text": ocr_text[:4000],
                "task_count": len(created_tasks),
            },
            message="OCR upload workflow completed",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("OCR upload workflow failed")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@workflow_router.get("/status", response_model=ApiResponse)
def workflow_status():
    return ApiResponse(
        success=True,
        data={
            "workflow_initialized": state.langraph_workflow is not None,
            "mcp_initialized": state.mcp_server is not None,
            "mcp_tools": len(state.mcp_server.list_tools()) if state.mcp_server else 0,
            "mcp_resources": len(state.mcp_server.list_resources()) if state.mcp_server else 0,
            "mcp_prompts": len(state.mcp_server.list_prompts()) if state.mcp_server else 0,
        },
    )
