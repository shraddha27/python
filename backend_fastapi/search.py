import json
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend_fastapi.embeddings import generate_embedding, generate_embeddings_batch
from backend_fastapi.models import DocumentModel, TaskModel
from backend_fastapi.rag_tools import (
    execute_tool,
    extract_create_task_fields,
    extract_update_task_fields,
    looks_like_explicit_create_task_request,
    looks_like_task_status_update_request,
    normalize_task_search_query,
    filter_tasks_by_query,
    _detect_explicit_date_constraint,
    search_tasks as rag_search_tasks,
)
from backend_fastapi.utils import format_pgvector_literal, cosine_similarity

INTENT_EXAMPLE_EMBEDDINGS_CACHE: Dict[str, List[List[float]]] = {}


def cleanup_duplicate_documents(db: Session):
    db.execute(
        text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY task_id
                           ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM documents
                WHERE task_id IS NOT NULL
            )
            DELETE FROM documents
            WHERE id IN (
                SELECT id
                FROM ranked
                WHERE rn > 1
            )
            """
        )
    )
    db.commit()


def sync_task_document(db: Session, task: TaskModel):
    db.query(DocumentModel).filter(DocumentModel.task_id == task.id).delete()
    content = f"{task.title}\n{task.description}"
    embedding = generate_embedding(content)
    doc = DocumentModel(
        task_id=task.id,
        title=task.title,
        content=content,
        embedding=embedding,
    )
    db.add(doc)


def _precompute_intent_embeddings() -> None:
    intent_examples = {
        "list_tasks": [
            "show all tasks",
            "list all tasks",
            "display all tasks",
            "show tasks",
            "what tasks do I have",
        ],
        "sort_tasks_by_time": [
            "prioritize tasks by time",
            "sort tasks by urgency",
            "show tasks due soon",
            "what task comes next",
            "rank tasks by current time",
        ],
        "search_tasks": [
            "find tasks related to shopping",
            "search tasks about training",
            "look for my work task",
            "what task is related to lunch",
            "find the task about market",
        ],
        "get_task_stats": [
            "how many tasks are completed",
            "how many tasks are pending",
            "task counts",
            "show completed and pending tasks",
        ],
        "list_completed_tasks": [
            "which tasks are completed",
            "show completed tasks",
            "list done tasks",
            "what tasks have been completed",
            "completed task list",
        ],
        "list_pending_tasks": [
            "which tasks are pending",
            "show pending tasks",
            "open tasks",
            "unfinished tasks",
            "what tasks are not done",
        ],
        "get_task_details": [
            "tell me about my training task",
            "show task details for this task",
            "what is task 7",
            "task info",
        ],
        "complete_task": [
            "complete my eating lunch task",
            "mark this task done",
            "finish the work task",
            "complete the shopping task",
        ],
        "reopen_task": [
            "reopen my work related task",
            "mark this task pending",
            "undo complete on the task",
            "reopen the completed task",
        ],
        "delete_task": [
            "delete shopping task",
            "remove the market task",
            "erase this task",
            "trash the training task",
        ],
        "update_task": [
            "update task title",
            "rename task",
            "edit the task description",
            "change task title to sprint retro planning",
        ],
        "create_task": [
            "create a new task",
            "add a task",
            "make a new task",
            "create task title and description",
        ],
    }

    for intent_name, examples in intent_examples.items():
        INTENT_EXAMPLE_EMBEDDINGS_CACHE[intent_name] = generate_embeddings_batch(examples)


def _semantic_intent(message: str) -> tuple[str, float]:
    if message is None:
        return "", 0.0

    msg_lower = message.lower()

    if looks_like_explicit_create_task_request(message):
        return "create_task", 0.95

    status_action = looks_like_task_status_update_request(message)
    if status_action:
        return status_action, 0.95

    is_task_list_request = bool(re.search(r"\b(?:list|show|display|find|get)\b.*\b(?:task|tasks)\b", msg_lower))
    is_pending_request = bool(re.search(r"\b(?:pending|open|unfinished|not done|incomplete)\b", msg_lower))
    if is_task_list_request and is_pending_request:
        if re.search(r"\b(?:prioritize|prioritise|priority|rank|sort|order|urgency|deadline|due)\b", msg_lower):
            return "sort_tasks_by_time", 0.95
        return "list_pending_tasks", 0.95

    keyword_intents = {
        "list_tasks": ["list", "show all", "display", "all tasks", "what tasks"],
        "sort_tasks_by_time": ["urgent", "priority", "due soon", "due date", "deadline", "next task", "rank"],
        "get_task_stats": ["how many", "completed", "pending", "count", "statistics", "summary"],
        "list_completed_tasks": ["completed", "done", "finished", "complete"],
        "list_pending_tasks": ["pending", "open", "unfinished", "not done", "incomplete"],
        "delete_task": ["delete", "remove", "erase", "trash"],
        "complete_task": ["complete", "done", "finish", "mark done"],
        "reopen_task": ["reopen", "undo complete", "mark pending", "reactivate"],
        "update_task": ["update", "edit", "rename", "change", "modify"],
    }
    for intent, keywords in keyword_intents.items():
        if any(keyword in msg_lower for keyword in keywords):
            return intent, 0.9

    message_embedding = generate_embedding(message)
    best_intent = ""
    best_score = 0.0
    for intent_name, cached_embeddings in INTENT_EXAMPLE_EMBEDDINGS_CACHE.items():
        for example_embedding in cached_embeddings:
            example_score = cosine_similarity(message_embedding, example_embedding)
            if example_score > best_score:
                best_score = example_score
                best_intent = intent_name

    return best_intent, best_score


def extract_task_id(text: str) -> Optional[int]:
    if not text:
        return None
    match = re.search(r"\btask\s*(?:with\s+)?(?:id\s*)?#?(\d+)\b", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\bid\s*#?(\d+)\b", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d+)\b", text)
    return int(match.group(1)) if match else None


def _normalize_task_target_query(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return ""
    normalized = re.sub(
        r"\b(?:please\s+)?(?:complete|reopen|re-open|open again|uncomplete|undo complete|mark pending|mark not done|delete|remove|erase|trash|discard)\b",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\b(?:task|tasks|task\s+id|task\s+with\s+id|id)\b",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\b(?:when|due|deadline|by when|due by|complete by)\b",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\b(?:related to|about|regarding|associated with|matching|called|named|for)\b",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\b(?:the|a|an|this|that|my|with|as|of)\b", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip(" ,.;:-\"'")
    return normalized


def _is_deadline_question(text: str) -> bool:
    if not text:
        return False
    lower_text = text.lower()
    return (
        any(word in lower_text for word in ["when", "due", "deadline", "by when", "complete by"])
        and any(word in lower_text for word in ["task", "review", "edit", "work", "project", "job"])
    )


def _format_deadline_response(task_details: dict) -> str:
    deadline_display = task_details.get("deadline_display")
    if deadline_display:
        return f"The task is due on {deadline_display}."
    deadline_at = task_details.get("deadline_at")
    if deadline_at:
        return f"The task is due on {deadline_at}."
    return "I found the task, but I could not find a due date in its description."


def _execute_tool(db: Session, tool_name: str, tool_args: dict) -> tuple[str, Any]:
    try:
        tool_result_text = execute_tool(tool_name, tool_args, db)
        try:
            tool_result = json.loads(tool_result_text)
        except json.JSONDecodeError:
            tool_result = tool_result_text
        return tool_result_text, tool_result
    except Exception as exc:
        error_text = str(exc)
        return error_text, {"error": error_text}


def _tool_call(db: Session, tool_name: str, tool_args: dict, tool_calls: List[dict]) -> str:
    tool_result_text, tool_result = _execute_tool(db, tool_name, tool_args)
    tool_calls.append({"name": tool_name, "args": tool_args, "result": tool_result})
    return f"Tool: {tool_name}\nResult: {tool_result_text}"


def _resolve_task_id_for_action(
    message: str,
    db: Session,
    candidate_docs: Optional[List[dict]] = None,
    desired_status: Optional[str] = None,
) -> Optional[int]:
    task_id = extract_task_id(message)
    if task_id is not None:
        return task_id
    return resolve_task_id_from_query(message, db=db, desired_status=desired_status, candidate_docs=candidate_docs)


def _tool_from_semantic_intent(
    intent: str,
    message: str,
    db: Session,
    candidate_docs: Optional[List[dict]] = None,
) -> tuple[Optional[str], Optional[dict]]:
    explicit_date_constraint = _detect_explicit_date_constraint(message)
    if explicit_date_constraint and intent in {"list_tasks", "list_completed_tasks", "list_pending_tasks", "sort_tasks_by_time"}:
        return "search_tasks", {"query": message}
    if intent == "list_tasks":
        return "list_tasks", {"completed": None, "limit": 100, "offset": 0}
    if intent == "sort_tasks_by_time":
        return "sort_tasks_by_time", {"completed": False, "limit": 100, "offset": 0}
    if intent == "search_tasks":
        return "search_tasks", {"query": message}
    if intent == "get_task_stats":
        return "get_task_stats", {}
    if intent == "list_completed_tasks":
        return "list_tasks", {"completed": True, "limit": 100, "offset": 0}
    if intent == "list_pending_tasks":
        return "list_tasks", {"completed": False, "limit": 100, "offset": 0}
    if intent == "get_task_details":
        task_id = _resolve_task_id_for_action(message, db, candidate_docs)
        return ("get_task_details", {"task_id": task_id}) if task_id is not None else (None, None)
    if intent == "complete_task":
        task_id = _resolve_task_id_for_action(message, db, candidate_docs, desired_status="pending")
        return ("complete_task", {"task_id": task_id}) if task_id is not None else (None, None)
    if intent == "reopen_task":
        task_id = _resolve_task_id_for_action(message, db, candidate_docs, desired_status="completed")
        return ("reopen_task", {"task_id": task_id}) if task_id is not None else (None, None)
    if intent == "delete_task":
        task_id = _resolve_task_id_for_action(message, db, candidate_docs)
        return ("delete_task", {"task_id": task_id}) if task_id is not None else (None, None)
    if intent == "create_task":
        title, description = extract_create_task_fields(message)
        return "create_task", {"title": title, "description": description}
    if intent == "update_task":
        task_id, title, description = extract_update_task_fields(message)
        if task_id is not None and (title is not None or description is not None):
            return "update_task", {"task_id": task_id, "title": title, "description": description}
        return None, None
    return None, None


def _infer_tool_from_keywords(
    message_lower: str,
    message: str,
    db: Session,
    candidate_docs: Optional[List[dict]] = None,
) -> tuple[Optional[str], Optional[dict]]:
    if any(word in message_lower for word in ["show all tasks", "list all tasks", "display all tasks", "show tasks", "list tasks", "display tasks", "all tasks"]):
        return "list_tasks", {"completed": None, "limit": 100, "offset": 0}

    if any(word in message_lower for word in ["sort", "order", "rank", "prioritize", "prioritise", "priority", "importance", "urgency", "soon", "asap", "earliest", "later", "by time", "time-based", "deadline", "schedule"]):
        return "sort_tasks_by_time", {"completed": False, "limit": 100, "offset": 0}

    if any(word in message_lower for word in ["related to", "about", "regarding", "associated with", "my training", "training"]):
        return "search_tasks", {"query": message}

    if any(word in message_lower for word in ["how many completed", "how many pending", "completed and pending", "completed tasks", "pending tasks", "task counts", "task count", "count of tasks", "how many tasks", "stats", "summary", "count"]):
        return "get_task_stats", {}

    if _detect_explicit_date_constraint(message):
        return "search_tasks", {"query": message}

    status_action = looks_like_task_status_update_request(message)
    if status_action == "complete_task":
        task_id = _resolve_task_id_for_action(message, db, candidate_docs, desired_status="pending")
        return ("complete_task", {"task_id": task_id}) if task_id is not None else (None, None)
    if status_action == "reopen_task":
        task_id = _resolve_task_id_for_action(message, db, candidate_docs, desired_status="completed")
        return ("reopen_task", {"task_id": task_id}) if task_id is not None else (None, None)

    if any(word in message_lower for word in ["update", "edit", "rename", "change", "modify"]) and "task" in message_lower:
        task_id, title, description = extract_update_task_fields(message)
        if task_id is not None and (title is not None or description is not None):
            return "update_task", {"task_id": task_id, "title": title, "description": description}

    if any(word in message_lower for word in ["details", "detail", "tell me about", "what is", "task info", "task information"]):
        task_id = _resolve_task_id_for_action(message, db, candidate_docs)
        if task_id is not None:
            return "get_task_details", {"task_id": task_id}
        return "search_tasks", {"query": message}

    status_action = looks_like_task_status_update_request(message)
    if status_action == "complete_task":
        task_id = _resolve_task_id_for_action(message, db, candidate_docs, desired_status="pending")
        return ("complete_task", {"task_id": task_id}) if task_id is not None else (None, None)
    if status_action == "reopen_task":
        task_id = _resolve_task_id_for_action(message, db, candidate_docs, desired_status="completed")
        return ("reopen_task", {"task_id": task_id}) if task_id is not None else (None, None)

    if looks_like_explicit_create_task_request(message):
        title, description = extract_create_task_fields(message)
        return "create_task", {"title": title, "description": description}

    return None, None


def resolve_task_id_from_query(
    text: str,
    db: Session,
    desired_status: Optional[str] = None,
    candidate_docs: Optional[List[dict]] = None,
) -> Optional[int]:
    query_text = _normalize_task_target_query(text)
    if not query_text:
        return None

    candidates: List[dict] = []
    if candidate_docs:
        for doc in candidate_docs:
            task_id = doc.get("task_id") or doc.get("id")
            if task_id is None:
                continue
            candidates.append(
                {
                    "id": task_id,
                    "title": doc.get("title", ""),
                    "similarity_score": doc.get("similarity_score", 0.0),
                }
            )

    if not candidates:
        tool_result = execute_tool("search_tasks", {"query": query_text}, db)
        try:
            candidates = json.loads(tool_result)
        except json.JSONDecodeError:
            return None

    if not isinstance(candidates, list) or not candidates:
        return None

    if desired_status:
        filtered = []
        for item in candidates:
            task_id = item.get("id")
            if task_id is None:
                continue
            task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
            if not task:
                continue
            task_status = "completed" if task.completed else "pending"
            if task_status == desired_status:
                filtered.append(item)
        if filtered:
            candidates = filtered

    lowered_query = query_text.lower().strip()
    for candidate in candidates:
        candidate_title = str(candidate.get("title", "")).lower().strip()
        if candidate_title == lowered_query or lowered_query in candidate_title:
            return candidate.get("id")

    candidates.sort(key=lambda item: float(item.get("similarity_score", 0.0)), reverse=True)
    return candidates[0].get("id")


def vector_search(db: Session, query_embedding: List[float], limit: int = 5) -> List[dict]:
    try:
        embedding_literal = format_pgvector_literal(query_embedding)
        results = db.execute(
            text(
                """
                SELECT d.id, d.task_id, d.title, d.content,
                       1 - (embedding <=> CAST(:embedding AS vector(384))) as similarity_score
                FROM documents d
                INNER JOIN tasks t ON t.id = d.task_id
                ORDER BY d.embedding <=> CAST(:embedding AS vector(384))
                LIMIT :limit
                """
            ),
            {"embedding": embedding_literal, "limit": limit},
        ).fetchall()

        return [
            {
                "id": r[0],
                "task_id": r[1],
                "title": r[2],
                "content": r[3],
                "similarity_score": float(r[4]),
            }
            for r in results
        ]
    except Exception:
        return []


def _search_relevance_boost(query: str, title: str, content: str) -> float:
    query_text = (query or "").strip().lower()
    if not query_text:
        return 0.0

    doc_text = f"{title or ''}\n{content or ''}".lower()
    query_terms = set(re.findall(r"[a-z0-9]+", query_text))
    doc_terms = set(re.findall(r"[a-z0-9]+", doc_text))
    if not query_terms or not doc_terms:
        return 0.0

    lexical_overlap = len(query_terms & doc_terms) / max(len(query_terms), 1)
    temporal_terms = {
        "today",
        "tomorrow",
        "tonight",
        "deadline",
        "due",
        "soon",
        "asap",
        "later",
        "schedule",
        "time",
        "urgent",
        "urgency",
    }
    temporal_query = bool(query_terms & temporal_terms)
    temporal_doc = bool(doc_terms & temporal_terms)

    boost = 0.65 * lexical_overlap
    if temporal_query and temporal_doc:
        boost += 0.15
    return min(1.0, boost)


def _token_similarity(query_terms: set[str], doc_terms: set[str]) -> float:
    if not query_terms or not doc_terms:
        return 0.0

    exact_overlap = len(query_terms & doc_terms) / max(len(query_terms), 1)
    fuzzy_total = 0.0
    for query_term in query_terms:
        best_ratio = 0.0
        for doc_term in doc_terms:
            ratio = SequenceMatcher(None, query_term, doc_term).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
        fuzzy_total += best_ratio

    fuzzy_overlap = fuzzy_total / max(len(query_terms), 1)
    prefix_bonus = 0.0
    if any(
        query_term.startswith(doc_term) or doc_term.startswith(query_term)
        for query_term in query_terms
        for doc_term in doc_terms
    ):
        prefix_bonus = 0.15

    return min(1.0, (0.30 * exact_overlap) + (0.55 * fuzzy_overlap) + prefix_bonus)


def _rank_document_search_result(query: str, query_embedding: List[float], document) -> float:
    doc_embedding_values = document.embedding if document.embedding is not None else []
    doc_embedding = list(doc_embedding_values)
    semantic_score = cosine_similarity(query_embedding, doc_embedding) if doc_embedding else 0.0

    query_text = (query or "").strip().lower()
    doc_text = f"{document.title or ''}\n{document.content or ''}".lower()
    query_terms = set(re.findall(r"[a-z0-9]+", query_text))
    doc_terms = set(re.findall(r"[a-z0-9]+", doc_text))
    text_score = _token_similarity(query_terms, doc_terms)

    temporal_terms = {
        "today",
        "tomorrow",
        "tonight",
        "deadline",
        "due",
        "soon",
        "asap",
        "later",
        "schedule",
        "time",
        "urgent",
        "urgency",
    }
    if query_terms & temporal_terms and doc_terms & temporal_terms:
        text_score = min(1.0, text_score + 0.12)

    return min(1.0, (0.58 * semantic_score) + (0.42 * text_score))
