"""
Tool functions that the AI agent can call.
These are exposed via the agent API and executed server-side.
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import re
import json
import numpy as np

from backend_fastapi.embeddings import generate_embedding
from backend_fastapi.utils import cosine_similarity


# Tool Schemas for agent
TOOL_DEFINITIONS = [
    {
        "name": "search_tasks",
        "description": "Search for tasks matching a query string. Returns matching task titles, descriptions, and IDs.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for tasks (e.g., 'bug fixes', 'authentication')",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_task_details",
        "description": "Get full details of a specific task including title, description, status, and assigned user.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to retrieve",
                }
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "create_task",
        "description": "Create a new task with title and description.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Task title",
                },
                "description": {
                    "type": "string",
                    "description": "Task description",
                },
            },
            "required": ["title", "description"],
        },
    },
    {
        "name": "update_task",
        "description": "Update an existing task's title or description.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to update",
                },
                "title": {
                    "type": "string",
                    "description": "New task title",
                },
                "description": {
                    "type": "string",
                    "description": "New task description",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "complete_task",
        "description": "Mark an existing task as completed.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to mark complete",
                }
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "reopen_task",
        "description": "Mark an existing task as not completed.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to reopen",
                }
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "delete_task",
        "description": "Delete an existing task by task ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "integer",
                    "description": "The ID of the task to delete",
                }
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List tasks with pagination and optional completion filtering.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of tasks to return (default 10)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting position (default 0)",
                },
                "completed": {
                    "type": "boolean",
                    "description": "Optional completion filter. Use false to list pending tasks.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "sort_tasks_by_time",
        "description": "Sort tasks by the explicit time or date-time mentioned in their descriptions, using the current time as the reference. Tasks without a parseable time are returned last.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of tasks to return (default 10)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting position (default 0)",
                },
                "completed": {
                    "type": "boolean",
                    "description": "Optional completion filter. Use false to sort pending tasks only.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_task_stats",
        "description": "Get statistics about tasks: total count, by status, by user.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


def search_tasks(query: str, db) -> List[Dict[str, Any]]:
    """Search tasks semantically by title and description."""
    from sqlalchemy import select
    
    try:
        TaskModel, _ = _get_models()
        stmt = select(TaskModel)
        tasks = db.execute(stmt).scalars().all()
        return _rank_tasks_semantically(query, tasks, db)
    except Exception as e:
        return [{"error": str(e)}]


def get_task_details(task_id: int, db) -> Dict[str, Any]:
    """Get full task details."""
    from sqlalchemy import select
    
    try:
        TaskModel, _ = _get_models()
        
        stmt = select(TaskModel).where(TaskModel.id == task_id)
        task = db.execute(stmt).scalar_one_or_none()
        
        if not task:
            return {"error": f"Task {task_id} not found"}

        deadline_at, deadline_source = _parse_task_deadline(task.title or "", task.description or "", datetime.now())
        
        return {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "status": "pending" if not task.completed else "completed",
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "deadline_at": deadline_at.isoformat() if deadline_at else None,
            "deadline_display": _format_deadline_display(deadline_at) if deadline_at else None,
            "deadline_source": deadline_source,
        }
    except Exception as e:
        return {"error": str(e)}


def create_task(title: str, description: str, db) -> Dict[str, Any]:
    """Create a new task."""
    try:
        TaskModel, _ = _get_models()
        
        new_task = TaskModel(
            title=title,
            description=description,
            completed=False,
            created_at=datetime.utcnow(),
        )
        db.add(new_task)
        db.commit()
        _refresh_and_sync_task(new_task, db)
        
        return {
            "id": new_task.id,
            "title": new_task.title,
            "description": new_task.description,
            "status": "pending",
            "created_at": new_task.created_at.isoformat(),
        }
    except Exception as e:
        db.rollback()
        return {"error": str(e)}


def extract_update_task_fields(message: str) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Extract task ID and updated title/description from a user request."""
    if not message:
        return None, None, None

    task_id = None
    match = re.search(r"\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b", message, flags=re.IGNORECASE)
    if match:
        task_id = int(match.group(1))

    title = None
    description = None

    title_match = re.search(
        r"\btitle\b\s*(?:to|as|is|=|:)\s*(?:\"(?P<title1>.*?)\"|'(?P<title2>.*?)'|(?P<title3>[^,.;]+))",
        message,
        flags=re.IGNORECASE,
    )
    if title_match:
        title = title_match.group("title1") or title_match.group("title2") or title_match.group("title3")

    description_match = re.search(
        r"\bdescription\b\s*(?:to|as|is|=|:)\s*(?:\"(?P<desc1>.*?)\"|'(?P<desc2>.*?)'|(?P<desc3>[^,.;]+))",
        message,
        flags=re.IGNORECASE,
    )
    if description_match:
        description = description_match.group("desc1") or description_match.group("desc2") or description_match.group("desc3")

    if title is None and description is None:
        fallback_match = re.search(
            r"\b(?:update|change|rename|modify)\b.*\btask\s*(?:with\s+)?(?:id\s*)?#?\d+\b.*?\bto\s+(?P<value>.+)$",
            message,
            flags=re.IGNORECASE,
        )
        if fallback_match:
            title = fallback_match.group("value").strip(" .;:\"'")

    if title is not None:
        title = title.strip()
    if description is not None:
        description = description.strip()

    return task_id, title, description


def extract_create_task_titles(message: str) -> List[str]:
    """Extract task titles from explicit multi-task create requests."""
    if not message:
        return []

    normalized = re.sub(r"\s+", " ", message.strip())
    if not re.search(r"\b(?:create|add|make)\b(?:\s+(?:a|new|several|multiple|few|some))?\s*tasks?\b", normalized, flags=re.IGNORECASE):
        return []

    titles = [group[0] or group[1] for group in re.findall(r'"([^"]+)"|\'([^\']+)\'', message)]
    if titles:
        return [title.strip() for title in titles if title.strip()]

    tail_match = re.search(
        r"\b(?:create|add|make)\b(?:\s+(?:a|new|several|multiple|few|some))?\s*tasks?\b\s*[:\-]?\s*(.+)$",
        normalized,
        flags=re.IGNORECASE,
    )
    if not tail_match:
        return []

    tail = tail_match.group(1).strip()
    parts = [part.strip(" \"' .;:\-") for part in re.split(r",\s*|\s+and\s+|;\s*", tail)]
    titles = [part for part in parts if part]
    return titles if len(titles) > 1 else []


def looks_like_explicit_create_task_request(message: str) -> bool:
    """Return True only for requests that explicitly specify title and description fields or explicit create task phrasing."""
    text = re.sub(r"\s+", " ", (message or "").strip())
    if not text:
        return False

    if extract_create_task_titles(message):
        return True

    lower_text = text.lower()
    explicit_patterns = [
        r"\b(?:create|add|make)\b(?:\s+a|\s+new)?\s*tasks?\b.+\b(?:title|with title)\b\s*(?:as|is|=|:)?\s*.+?\b(?:and\s+)?description\b\s*(?:as|is|=|:)?\s*.+",
        r"\btitle\b\s*(?:as|is|=|:)?\s*.+?\b(?:and\s+)?description\b\s*(?:as|is|=|:)?\s*.+",
        r"\b(?:create|add|make)\b(?:\s+a|\s+new)?\s*tasks?\b.+\btitle\b.+\bdescription\b",
        r"\b(?:create|add|make)\b(?:\s+a|\s+new)?\s*tasks?\b\s+(?:for|about|titled?|on|regarding)\b.+",
        r"\b(?:and\s+)?another\s+(?:one|task)\b\s+(?:for|about|titled?|on|regarding)\b.+",
    ]
    return any(re.search(pattern, lower_text, flags=re.IGNORECASE | re.DOTALL) for pattern in explicit_patterns)


def looks_like_task_status_update_request(message: str) -> Optional[str]:
    """Return the status action when the message explicitly requests completion or reopen."""
    text = re.sub(r"\s+", " ", (message or "").strip())
    if not text:
        return None

    lower_text = text.lower()
    # If this is an explicit create request (title+description), don't treat
    # contained words like 'complete' as an action — it's part of the create.
    if looks_like_explicit_create_task_request(message):
        return None
    
    # Pattern for explicit task ID: "task #123" or "id 123"
    explicit_id_pattern = re.compile(
        r"(?:\b(?:task|tasks)\b[^\n.]{0,40}?\b(?:with\s+)?(?:id\s*)?#?\d+\b|\b(?:id\s*)?#?\d+\b[^\n.]{0,40}?\b(?:task|tasks)\b)",
        flags=re.IGNORECASE,
    )
    
    # Pattern for implicit task selection: "any", "all", "pending", pronouns ("it", "that"), or contextual keywords
    implicit_selection_pattern = re.compile(
        r"\b(?:any|all|these|them|this|that|the|remaining|pending|finished|completed|done|it)\b",
        flags=re.IGNORECASE,
    )

    # Prefer explicit reopen requests before completion
    if re.search(r"\b(?:reopen|re-open|open again|uncomplete|undo complete|mark pending|mark not done)\b", lower_text):
        # Accept reopen if explicit ID present OR if "any/all/pending" selection context exists
        if explicit_id_pattern.search(text) or implicit_selection_pattern.search(text):
            return "reopen_task"

    if re.search(r"\b(?:delete|remove|erase|trash|discard)\b", lower_text):
        # Accept delete if explicit ID present OR if there is selection context
        if explicit_id_pattern.search(text) or implicit_selection_pattern.search(text):
            return "delete_task"

    if re.search(r"\b(?:complete|completed|done|finish|mark done|mark as done|close)\b", lower_text):
        # Accept complete if explicit ID present OR if "any/all" or implied context (e.g., "that are pending")
        if explicit_id_pattern.search(text) or implicit_selection_pattern.search(text):
            return "complete_task"
    
    return None


def _strip_explicit_date_phrases(text: str) -> str:
    if not text:
        return ""

    cleaned = re.sub(
        r"\b(?:to be completed by|complete by|due by|due on|complete on|by|before|until|till|up to)\s+(?:\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:,?\s+\d{2,4})?|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{1,2}-\d{1,2}|today|tomorrow)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def _detect_task_status_filter(query_text: str) -> Optional[bool]:
    """Return False for pending-only, True for completed-only, or None for ambiguous."""
    lower_text = (query_text or "").lower()
    cleaned_text = _strip_explicit_date_phrases(lower_text)

    wants_pending = bool(re.search(r"\b(pending|open|incomplete|unfinished|not done|undone)\b", cleaned_text))
    wants_completed = bool(re.search(r"\b(completed|done|finished|closed)\b", cleaned_text))

    # Disambiguate when both are detected: "done" in "will be done" is not a status indicator
    if wants_pending and wants_completed:
        # Check if "done" appears in past tense context (completed action) vs future context (estimate)
        if re.search(r"\b(will be done|when.*done|how.*done|estimate|forecast|project|predict)\b", cleaned_text):
            # "done" here means completion time estimate, not task status
            return False
        # If "done" appears with past tense verbs, prefer completed interpretation
        if re.search(r"\b(is done|are done|was done|were done|got done|been done)\b", cleaned_text):
            return True
        # Otherwise ambiguous
        return None
    
    if wants_pending and not wants_completed:
        return False
    if wants_completed and not wants_pending:
        return True
    return None


def normalize_task_search_query(query: str) -> str:
    """Normalize natural-language task search prompts into a concise keyword query.

    Examples:
    - 'list all tasks related to documentation' -> 'documentation'
    - 'find tasks about architecture' -> 'architecture'
    """
    text = re.sub(r"\s+", " ", (query or "").strip()).lower()
    if not text:
        return ""

    removable_words = {
        "list",
        "show",
        "get",
        "display",
        "find",
        "search",
        "look",
        "retrieve",
        "view",
        "all",
        "my",
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "task",
        "tasks",
        "related",
        "about",
        "for",
        "to",
        "of",
        "on",
        "in",
        "with",
        "and",
        "or",
        "is",
        "are",
        "be",
    }

    tokens = [token for token in re.split(r"[^a-z0-9]+", text) if token and token not in removable_words]
    normalized = " ".join(tokens).strip()
    return normalized


def filter_tasks_by_query(tasks: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Filter ranked task results using a permissive keyword overlap check.

    The semantic ranking already does the heavy lifting. This helper only guards
    against over-pruning prompts like 'find tasks about API and analyze the results'
    by keeping results that match any important query term or a direct substring.
    """
    if not tasks:
        return []

    query_text = (query or "").strip()
    if not query_text:
        return list(tasks)

    normalized_query = normalize_task_search_query(query_text)
    if not normalized_query:
        return list(tasks)

    query_terms = {term for term in re.findall(r"[a-z0-9]+", normalized_query.lower()) if term}
    if not query_terms:
        return list(tasks)

    compound_query = bool(re.search(r"\b(and|then|also|plus)\b", query_text.lower())) or bool(re.search(r"\b(analyze|analysis|summarize|explain|inspect|review|understand|compare|report|context|details|summary)\b", query_text.lower()))
    if compound_query:
        return list(tasks)

    filtered = []
    for item in tasks:
        title = str(item.get("title") or "")
        description = str(item.get("description") or "")
        task_text = f"{title} {description}".lower()

        if any(term in task_text for term in query_terms):
            filtered.append(item)
            continue

        if normalized_query.lower() in task_text:
            filtered.append(item)

    if filtered:
        return filtered

    return list(tasks)


def extract_create_task_fields(message: str) -> Tuple[str, str]:
    """Extract task title and description from explicit create requests only."""
    text = re.sub(r"\s+", " ", (message or "").strip())
    if not text or not looks_like_explicit_create_task_request(message):
        return "", ""

    patterns = [
        r"title\s*(?:as|is|=|:)\s*(?P<title>.+?)\s*(?:,?\s*(?:and|with)\s+)?description\s*(?:as|is|=|:)\s*(?P<description>.+?)(?:[.!?]+)?$",
        r"description\s*(?:as|is|=|:)\s*(?P<description>.+?)\s*(?:,?\s*(?:and|with)\s+)?title\s*(?:as|is|=|:)\s*(?P<title>.+?)(?:[.!?]+)?$",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            title = match.group("title").strip(" ,.;:-\"'")
            description = match.group("description").strip(" ,.;:-\"'")
            return title or "New Task", description or text

    title_match = re.search(
        r"\btitle\s*(?:as|is|=|:)?\s*(?P<title>.+?)(?=(?:\s+(?:and|with)\s+description\b|\s+description\b|$))",
        text,
        flags=re.IGNORECASE,
    )
    description_match = re.search(
        r"\bdescription\s*(?:as|is|=|:)?\s*(?P<description>.+)$",
        text,
        flags=re.IGNORECASE,
    )

    title = title_match.group("title").strip(" ,.;:-\"'") if title_match else ""
    description = description_match.group("description").strip(" ,.;:-\"'") if description_match else ""

    if not title and not description:
        return "", ""

    return title, description


def _sync_task_document(db, task) -> None:
    """Refresh the vector document for a task after any mutation."""
    _, DocumentModel = _get_models()

    db.query(DocumentModel).filter(DocumentModel.task_id == task.id).delete()

    content = f"{task.title}\n{task.description}"
    embedding = generate_embedding(content)

    db.add(
        DocumentModel(
            task_id=task.id,
            title=task.title,
            content=content,
            embedding=embedding,
        )
    )


def _get_models():
    """Deferred import of ORM models to avoid circular dependencies."""
    from backend_fastapi.models import TaskModel, DocumentModel
    return TaskModel, DocumentModel


def _get_document_embedding_for_task(task, db) -> Optional[np.ndarray]:
    """Return stored document embedding for a task if available."""
    if db is None:
        return None

    _, DocumentModel = _get_models()
    # support dict-shaped or object-shaped tasks
    task_id = None
    if isinstance(task, dict):
        task_id = task.get("id") or task.get("task_id")
    else:
        task_id = getattr(task, "id", None)
    if task_id is None:
        return None

    doc = db.query(DocumentModel).filter(DocumentModel.task_id == task_id).first()
    if doc is None or doc.embedding is None:
        return None

    embedding = np.array(doc.embedding, dtype=np.float32)
    if embedding.size == 0:
        return None
    return embedding


def _get_task_by_id(task_id: int, db):
    TaskModel, _ = _get_models()
    return db.query(TaskModel).filter(TaskModel.id == task_id).first()


def _refresh_and_sync_task(task, db) -> None:
    db.refresh(task)
    _sync_task_document(db, task)
    db.commit()


def _task_search_text(task) -> str:
    if task is None:
        return ""
    if isinstance(task, dict):
        title = task.get("title", "") or ""
        description = task.get("description", "") or ""
    else:
        title = getattr(task, "title", "") or ""
        description = getattr(task, "description", "") or ""
    return f"{title}\n{description}"

def _ordinal_suffix(day: int) -> str:
    if 11 <= day % 100 <= 13:
        return "th"
    last_digit = day % 10
    if last_digit == 1:
        return "st"
    if last_digit == 2:
        return "nd"
    if last_digit == 3:
        return "rd"
    return "th"

def _format_deadline_display(deadline_at: datetime, reference_now: Optional[datetime] = None) -> str:
    reference_now = reference_now or datetime.now()
    suffix = _ordinal_suffix(deadline_at.day)
    if deadline_at.year == reference_now.year:
        return f"{deadline_at.day}{suffix} {deadline_at.strftime('%B')}"
    return f"{deadline_at.day}{suffix} {deadline_at.strftime('%B %Y')}"

def _detect_relative_time_query(query_text: str) -> Optional[str]:
    lower_query = (query_text or "").lower()
    if re.search(r"\b(today|tonight|later today|due today)\b", lower_query):
        return "today"
    if re.search(r"\b(tomorrow|tmr|tmrw|due tomorrow)\b", lower_query):
        return "tomorrow"
    if re.search(r"\b(this week|this week\b|due this week|due this coming week)\b", lower_query):
        return "this_week"
    if re.search(r"\b(next week|coming week)\b", lower_query):
        return "next_week"
    if re.search(r"\b(last week|previous week)\b", lower_query):
        return "last_week"
    # fallback: month/quarter handling could be added later
    return None


def _detect_explicit_date_constraint(query_text: str) -> Optional[Tuple[str, datetime]]:
    """Detect explicit date constraints such as 'by 25th June' or 'on 25 June'."""
    text = (query_text or "").strip()
    if not text:
        return None

    lower_text = text.lower()
    reference_now = datetime.now()
    patterns = [
        (r"\b(?:by|before|until|up to|till|due by|due on|on)\s+(?P<date>\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:,?\s+\d{2,4})?)\b", ["%d %B %Y", "%d %B", "%d %b %Y", "%d %b"]),
        (r"\b(?:by|before|until|up to|till|due by|due on|on)\s+(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\b", ["%m/%d/%Y", "%m/%d/%y"]),
        (r"\b(?:by|before|until|up to|till|due by|due on|on)\s+(?P<date>\d{4}-\d{1,2}-\d{1,2})\b", ["%Y-%m-%d"]),
    ]

    constraint = "exact"
    if re.search(r"\b(?:by|before|until|up to|till|due by)\b", lower_text):
        constraint = "on_or_before"

    for pattern, formats in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        date_text = match.group("date")
        cleaned_date_text = re.sub(r"(st|nd|rd|th)", "", date_text).strip()
        for fmt in formats:
            try:
                parsed = datetime.strptime(cleaned_date_text, fmt)
                if "%Y" not in fmt:
                    parsed = parsed.replace(year=reference_now.year)
                return constraint, parsed
            except ValueError:
                continue

    return None


def _task_matches_relative_time(task_text: str, time_mode: str, reference_now: Optional[datetime] = None) -> bool:
    reference_now = reference_now or datetime.now()
    lower_text = (task_text or "").lower()

    scheduled_at, _ = _parse_task_deadline("", task_text, reference_now)
    if scheduled_at is not None:
        if time_mode == "today":
            return scheduled_at.date() == reference_now.date()
        if time_mode == "tomorrow":
            return scheduled_at.date() == (reference_now + timedelta(days=1)).date()
        if time_mode == "this_week":
            # ISO week: Monday is 0 for weekday(); compute week start/end
            start = reference_now - timedelta(days=reference_now.weekday())
            end = start + timedelta(days=6)
            return start.date() <= scheduled_at.date() <= end.date()
        if time_mode == "next_week":
            start = reference_now - timedelta(days=reference_now.weekday()) + timedelta(days=7)
            end = start + timedelta(days=6)
            return start.date() <= scheduled_at.date() <= end.date()
        if time_mode == "last_week":
            start = reference_now - timedelta(days=reference_now.weekday()) - timedelta(days=7)
            end = start + timedelta(days=6)
            return start.date() <= scheduled_at.date() <= end.date()
        return True

    today_match = bool(re.search(r"\b(today|tonight|later today|due today)\b", lower_text))
    tomorrow_match = bool(re.search(r"\b(tomorrow|tmr|tmrw|due tomorrow)\b", lower_text))

    if time_mode == "today":
        return today_match or bool(re.search(r"\b(?:due by|by|on|before|until)\s+(?:today|tonight)\b", lower_text))
    if time_mode == "tomorrow":
        return tomorrow_match or bool(re.search(r"\b(?:due by|by|on|before|until)\s+(?:tomorrow|tmr|tmrw)\b", lower_text))
    return True


def _task_matches_date_constraint(task, target_date: datetime, constraint: str) -> bool:
    if isinstance(task, dict):
        title = task.get("title", "") or ""
        description = task.get("description", "") or ""
    else:
        title = getattr(task, "title", "") or ""
        description = getattr(task, "description", "") or ""

    scheduled_at, _ = _parse_task_deadline(title, description, datetime.now())
    if scheduled_at is None:
        return False

    if constraint == "on_or_before":
        return scheduled_at.date() <= target_date.date()
    return scheduled_at.date() == target_date.date()


def _normalize_search_terms(text: str) -> set:
    terms = set()
    for token in re.findall(r"[a-z0-9]+", (text or "").lower()):
        terms.add(token)
        if len(token) > 3 and token.endswith("s"):
            terms.add(token[:-1])
    return terms


def _rank_tasks_semantically(query: str, tasks, db, desired_status: Optional[str] = None) -> List[Dict[str, Any]]:
    query_text = (query or "").strip()
    if not query_text:
        return []

    query_embedding = np.array(generate_embedding(query_text), dtype=np.float32)
    query_terms = _normalize_search_terms(query_text)
    query_lower = query_text.lower()
    wants_completed = any(term in query_lower for term in ["completed", "done", "finished", "closed"])
    project_terms = {"project", "projects", "project work", "project-related"}
    wants_project_tasks = any(term in query_lower for term in ["project", "projects", "project work", "project-related"])
    relative_time_mode = _detect_relative_time_query(query_text)
    explicit_date_constraint = _detect_explicit_date_constraint(query_text)
    status_filter = _detect_task_status_filter(query_text)

    ranked = []
    for task in tasks:
        # Normalize common fields across dict/object shapes
        is_dict = isinstance(task, dict)
        task_status = "pending"
        if is_dict:
            task_status = "completed" if task.get("completed") else "pending"
        else:
            task_status = "completed" if getattr(task, "completed", False) else "pending"
        if desired_status and task_status != desired_status:
            continue
        if status_filter is False and task_status == "completed":
            continue
        if status_filter is True and task_status == "pending":
            continue
        title = task.get("title") if isinstance(task, dict) else getattr(task, "title", "")
        description = task.get("description") if isinstance(task, dict) else getattr(task, "description", "")
        task_text = _task_search_text(task)
        if relative_time_mode and not _task_matches_relative_time(task_text, relative_time_mode, datetime.now()):
            continue
        if explicit_date_constraint:
            constraint_name, target_date = explicit_date_constraint
            if not _task_matches_date_constraint(task, target_date, constraint_name):
                continue

        task_embedding = _get_document_embedding_for_task(task, db)
        if task_embedding is None:
            task_embedding = np.array(generate_embedding(task_text), dtype=np.float32)
        semantic_score = cosine_similarity(query_embedding, task_embedding)

        task_terms = _normalize_search_terms(task_text)
        lexical_overlap = len(query_terms & task_terms) / max(len(query_terms), 1)
        fuzzy_overlap = 0.0
        for query_term in query_terms:
            best_ratio = 0.0
            for task_term in task_terms:
                ratio = SequenceMatcher(None, query_term, task_term).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
            fuzzy_overlap += best_ratio
        fuzzy_overlap = fuzzy_overlap / max(len(query_terms), 1)

        if task_embedding is not None:
            title_score = semantic_score
            description_score = semantic_score
        else:
            title_score = cosine_similarity(query_embedding, np.array(generate_embedding(title or ""), dtype=np.float32))
            description_score = cosine_similarity(query_embedding, np.array(generate_embedding(description or ""), dtype=np.float32))

        title_text = (title or "").lower()
        title_boost = 0.0
        if query_terms and any(term in title_text for term in query_terms):
            title_boost += 0.18

        if wants_project_tasks and any(term in task_text.lower() for term in project_terms):
            title_boost += 0.15

        description_boost = 0.0
        if query_terms and any(term in task_text.lower() for term in query_terms):
            description_boost += 0.05

        completed_flag = (task.get("completed") if isinstance(task, dict) else getattr(task, "completed", False))
        status_penalty = 0.0
        if completed_flag and not wants_completed:
            status_penalty = 0.12

        combined_score = (
            (0.56 * semantic_score)
            + (0.18 * title_score)
            + (0.10 * description_score)
            + (0.10 * lexical_overlap)
            + (0.08 * fuzzy_overlap)
            + title_boost
            + description_boost
            - status_penalty
        )

        task_id = (task.get("id") if isinstance(task, dict) else getattr(task, "id", None)) or (task.get("task_id") if isinstance(task, dict) else getattr(task, "task_id", None))
        ranked.append(
            {
                "id": int(task_id) if task_id is not None else None,
                "title": title,
                "description": (description or "")[:100],
                "status": task_status,
                "completed": bool(completed_flag),
                "similarity_score": round(float(combined_score), 6),
            }
        )

    ranked.sort(key=lambda item: (-item["similarity_score"], item["id"]))
    minimum_score = 0.18
    if wants_project_tasks:
        minimum_score = 0.22
    if relative_time_mode or explicit_date_constraint:
        minimum_score = 0.0

    if not wants_completed:
        ranked = [item for item in ranked if item["similarity_score"] >= minimum_score]
    return ranked


def _parse_clock_time(time_text: str) -> Optional[Tuple[int, int]]:
    time_text = time_text.strip().lower()
    if time_text == "noon":
        return 12, 0
    if time_text == "midnight":
        return 0, 0

    match = re.search(r"\b(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?(?::\d{2})?\s*(?P<meridiem>am|pm)\b", time_text)
    if match:
        hour = int(match.group("hour"))
        minute = int(match.group("minute") or 0)
        meridiem = match.group("meridiem")
        if hour == 12:
            hour = 0
        if meridiem == "pm":
            hour += 12
        return hour, minute

    match = re.search(r"\b(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::\d{2})?\b", time_text)
    if match:
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
        return None

    return None


def _parse_task_deadline(title: str, description: str, reference_now: datetime) -> Tuple[Optional[datetime], str]:
    text = f"{title or ''}\n{description or ''}".strip()
    lower_text = text.lower()

    if not text:
        return None, "no_description"

    patterns = [
        (r"\b(?P<date>\d{4}-\d{1,2}-\d{1,2})\b(?:\s+(?:at\s+)?)?(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)?", ["%Y-%m-%d"]),
        (r"\b(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\b(?:\s+(?:at\s+)?)?(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)?", ["%m/%d/%Y", "%m/%d/%y"]),
        (r"\b(?P<date>(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?)\b(?:\s+(?:at\s+)?)?(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)?", ["%B %d %Y", "%B %d", "%b %d %Y", "%b %d"]),
        (r"\b(?P<date>\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:,?\s+\d{4})?)\b(?:\s+(?:at\s+)?)?(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)?", ["%d %B %Y", "%d %B", "%d %b %Y", "%d %b"]),
    ]

    for pattern, date_formats in patterns:
        match = re.search(pattern, lower_text)
        if not match:
            continue

        date_text = match.group("date")
        time_text = match.group("time")
        cleaned_date_text = re.sub(r"(st|nd|rd|th)", "", date_text).strip()

        date_value = None
        for date_format in date_formats:
            try:
                parsed = datetime.strptime(cleaned_date_text, date_format)
                if "%Y" not in date_format:
                    parsed = parsed.replace(year=reference_now.year)
                date_value = parsed
                break
            except ValueError:
                continue

        if date_value is None:
            continue

        if time_text:
            parsed_time = _parse_clock_time(time_text)
            if parsed_time is not None:
                hour, minute = parsed_time
                date_value = date_value.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return date_value, "explicit_date_time"

        date_value = date_value.replace(hour=23, minute=59, second=0, microsecond=0)
        return date_value, "date_only"

    time_patterns = [
        r"\b(?:at\s+)?(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm)|noon|midnight)\b",
    ]

    for pattern in time_patterns:
        match = re.search(pattern, lower_text)
        if not match:
            continue

        parsed_time = _parse_clock_time(match.group("time"))
        if parsed_time is None:
            continue

        hour, minute = parsed_time
        scheduled = reference_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled < reference_now:
            scheduled += timedelta(days=1)
        return scheduled, "time_only"

    if "tomorrow" in lower_text:
        time_match = re.search(r"\b(?:tomorrow|tmr|tmrw)\b(?:\s+(?:at\s+)?)?(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm)|noon|midnight)?", lower_text)
        scheduled = (reference_now + timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)
        if time_match and time_match.group("time"):
            parsed_time = _parse_clock_time(time_match.group("time"))
            if parsed_time is not None:
                hour, minute = parsed_time
                scheduled = scheduled.replace(hour=hour, minute=minute)
        return scheduled, "relative_tomorrow"

    if "today" in lower_text:
        time_match = re.search(r"\b(?:today|tonight)\b(?:\s+(?:at\s+)?)?(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm)|noon|midnight)?", lower_text)
        scheduled = reference_now.replace(hour=23, minute=59, second=0, microsecond=0)
        if time_match and time_match.group("time"):
            parsed_time = _parse_clock_time(time_match.group("time"))
            if parsed_time is not None:
                hour, minute = parsed_time
                scheduled = scheduled.replace(hour=hour, minute=minute)
        return scheduled, "relative_today"

    return None, "no_parseable_time"


def _task_priority_bucket(title: str, description: str, reference_now: datetime) -> Tuple[int, str, Optional[datetime]]:
    """Assign a priority bucket based on urgency words and parsed time references.

    Lower bucket values are ranked first.
    """
    text = f"{title or ''}\n{description or ''}".lower()
    urgency_keywords = {
        "urgent", "urgently", "asap", "now", "immediately", "important", "critical",
        "priority", "high priority", "soon", "soonest", "today", "tonight", "this morning",
        "this afternoon", "this evening", "later today", "due today", "due soon"
    }

    scheduled_at, time_source = _parse_task_deadline(title, description, reference_now)

    if scheduled_at is not None:
        if scheduled_at > reference_now:
            return 0, f"future_due:{time_source}", scheduled_at
        return 1, f"due_or_overdue:{time_source}", scheduled_at

    if any(keyword in text for keyword in urgency_keywords):
        return 2, "urgency_keyword", None

    return 3, "no_time_or_urgency", None


def delete_task(task_id: int, db) -> Dict[str, Any]:
    """Delete a task and its vector document."""
    try:
        TaskModel, DocumentModel = _get_models()

        task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not task:
            return {"error": f"Task {task_id} not found"}

        db.query(DocumentModel).filter(DocumentModel.task_id == task.id).delete()
        db.delete(task)
        db.commit()

        return {
            "id": task_id,
            "status": "deleted",
        }
    except Exception as e:
        db.rollback()
        return {"error": str(e)}


def complete_task(task_id: int, db) -> Dict[str, Any]:
    """Mark a task as completed."""
    try:
        TaskModel, _ = _get_models()

        task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not task:
            return {"error": f"Task {task_id} not found"}

        task.completed = True
        task.completed_at = datetime.utcnow()
        db.commit()
        _refresh_and_sync_task(task, db)

        return {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "status": "completed",
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }
    except Exception as e:
        db.rollback()
        return {"error": str(e)}


def reopen_task(task_id: int, db) -> Dict[str, Any]:
    """Mark a task as not completed."""
    try:
        TaskModel, _ = _get_models()

        task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not task:
            return {"error": f"Task {task_id} not found"}

        task.completed = False
        task.completed_at = None
        db.commit()
        _refresh_and_sync_task(task, db)

        return {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "status": "pending",
            "completed_at": None,
        }
    except Exception as e:
        db.rollback()
        return {"error": str(e)}


def list_tasks(limit: int = 10, offset: int = 0, completed: Optional[bool] = None, db = None) -> List[Dict[str, Any]]:
    """List tasks with pagination."""
    from sqlalchemy import select
    
    try:
        TaskModel, _ = _get_models()
        
        stmt = select(TaskModel)
        if completed is not None:
            stmt = stmt.where(TaskModel.completed == completed)
        stmt = stmt.limit(limit).offset(offset)
        tasks = db.execute(stmt).scalars().all()
        
        return [
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "status": "pending" if not task.completed else "completed",
                "completed": bool(task.completed),
            }
            for task in tasks
        ]
    except Exception as e:
        return [{"error": str(e)}]


def sort_tasks_by_time(limit: int = 10, offset: int = 0, completed: Optional[bool] = False, db = None) -> Dict[str, Any]:
    """Sort tasks by urgency keywords and the time mentioned in task text."""
    from sqlalchemy import select

    try:
        TaskModel, _ = _get_models()

        stmt = select(TaskModel)
        if completed is not None:
            stmt = stmt.where(TaskModel.completed == completed)

        tasks = db.execute(stmt).scalars().all()
        
        # FIX: Swapped timezone-aware .astimezone() for .now() to prevent TypeError crashes during datetime comparisons
        reference_now = datetime.now()

        sorted_tasks = []
        for task in tasks:
            sort_bucket, sort_reason, scheduled_at = _task_priority_bucket(task.title, task.description, reference_now)
            if scheduled_at is None:
                minutes_from_now = None
                status_label = "unscheduled"
                time_source = sort_reason
            else:
                delta = scheduled_at - reference_now
                minutes_from_now = int(delta.total_seconds() // 60)
                status_label = "overdue" if scheduled_at < reference_now else "upcoming"
                time_source = sort_reason

            sorted_tasks.append({
                "id": task.id,
                "title": task.title,
                "description": task.description[:120],
                "status": "pending" if not task.completed else "completed",
                "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
                "time_source": time_source,
                "priority_reason": sort_reason,
                "minutes_from_now": minutes_from_now,
                "time_status": status_label,
                "_sort_bucket": sort_bucket,
            })

        sorted_tasks.sort(
            key=lambda item: (
                item["_sort_bucket"],
                item["scheduled_at"] or "9999-12-31T23:59:59",
                item["id"],
            )
        )

        paged_tasks = sorted_tasks[offset: offset + limit]
        for task in paged_tasks:
            task.pop("_sort_bucket", None)

        return {
            "current_time": reference_now.isoformat(),
            "sorted_by": "urgency_and_time",
            "completed_filter": completed,
            "total_tasks": len(sorted_tasks),
            "returned": len(paged_tasks),
            "tasks": paged_tasks,
        }
    except Exception as e:
        return {"error": str(e)}


def get_task_stats(db) -> Dict[str, Any]:
    """Get task statistics."""
    try:
        TaskModel, _ = _get_models()
        
        total = db.query(TaskModel).count()
        completed = db.query(TaskModel).filter(TaskModel.completed == True).count()
        pending = total - completed
        
        return {
            "total_tasks": total,
            "completed": completed,
            "pending": pending,
        }
    except Exception as e:
        return {"error": str(e)}


def update_task(task_id: int, title: Optional[str] = None, description: Optional[str] = None, db=None) -> Dict[str, Any]:
    """Update task title and/or description."""
    try:
        TaskModel, _ = _get_models()
        task = db.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not task:
            return {"error": f"Task {task_id} not found"}

        if title is None and description is None:
            return {"error": "No update fields provided. Please provide title or description."}

        if title is not None:
            title = title.strip()
            if not title:
                return {"error": "Title cannot be empty"}
            if len(title) > 255:
                return {"error": "Title cannot exceed 255 characters"}
            task.title = title

        if description is not None:
            task.description = description.strip()
            if len(task.description) > 1000:
                return {"error": "Description cannot exceed 1000 characters"}

        db.commit()
        _refresh_and_sync_task(task, db)

        return {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "status": "completed" if getattr(task, "completed", False) else "pending",
        }
    except Exception as e:
        db.rollback()
        return {"error": str(e)}


def execute_tool(tool_name: str, tool_args: Dict[str, Any], db) -> str:
    """Execute a tool by name with arguments."""
    tools = {
        "search_tasks": search_tasks,
        "get_task_details": get_task_details,
        "create_task": create_task,
        "update_task": update_task,
        "complete_task": complete_task,
        "reopen_task": reopen_task,
        "delete_task": delete_task,
        "list_tasks": list_tasks,
        "sort_tasks_by_time": sort_tasks_by_time,
        "get_task_stats": get_task_stats,
    }
    
    if tool_name not in tools:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    
    try:
        # FIX: Separated positional vs keyword variables safely to resolve TypeError argument unpack issues
        func = tools[tool_name]
        
        # Merge database session directly into the execution mapping context
        kwargs = {**tool_args, "db": db}
        result = func(**kwargs)
        
        return json.dumps(result)
    except TypeError as e:
        # Handle argument mismatch
        return json.dumps({"error": f"Tool argument error: {str(e)}"})
    except Exception as e:
        return json.dumps({"error": str(e)})