"""
Lightweight LLM integration using the Mistral API.
The app still falls back to a deterministic local response if the API key is missing
or a request cannot be completed.
"""
import os
import re
from typing import Optional, List, Dict, Any
import json

import httpx
import requests

MISTRAL_BASE_URL = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1").rstrip("/")
DEFAULT_MODEL = os.getenv("MISTRAL_MODEL", "mistral-tiny")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "").strip()
HTTP_TIMEOUT = float(os.getenv("MISTRAL_TIMEOUT", "45.0"))
LOCAL_AGENT_NAME = "task-mini-agent"
VERIFY_SSL = os.getenv("MISTRAL_VERIFY_SSL", "false").lower() not in {"0", "false", "no", "off"}

# Instruction for structured proposals when the LLM decides to call tools
PROPOSAL_INSTRUCTION = (
    "When you determine that an agent/tool should be invoked, output EXACTLY one JSON object and nothing else. "
    "The object must follow this schema: {\"agent\": optional string, \"tool\": string, \"args\": object, \"intent\": optional string, \"confirm\": boolean}. "
    "If you need clarification, ask a plain-language question (no JSON). "
    "Examples: {\"agent\":\"task_manager_001\",\"tool\":\"create_task\",\"args\":{\"title\":\"My Task\"},\"intent\":\"create\",\"confirm\":false} or {\"tool\":\"search_tasks\",\"args\":{\"query\":\"pending tasks by June 27\"},\"confirm\":false}."
)

import logging

logger = logging.getLogger(__name__)

PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"ignore\s+(the\s+)?system\s+prompt",
    r"reveal\s+(the\s+)?(hidden|secret|internal|system)\s+(prompt|instructions?)",
    r"override\s+(all\s+)?(previous|prior|existing)\s+instructions?",
    r"you\s+are\s+(now|actually)\s+(chatgpt|openai|claude|system)",
    r"developer\s+prompt",
]

UNSAFE_OUTPUT_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"reveal\s+(the\s+)?(hidden|secret|internal|system)\s+(prompt|instructions?)",
    r"system\s+prompt",
    r"developer\s+prompt",
    r"ignore\s+(the\s+)?system\s+prompt",
]

logger.info(
    "Mistral client configured: base_url=%s model=%s verify_ssl=%s api_key_present=%s",
    MISTRAL_BASE_URL,
    DEFAULT_MODEL,
    VERIFY_SSL,
    bool(MISTRAL_API_KEY),
)


def has_prompt_injection_attempt(text: Optional[str]) -> bool:
    if text is None:
        return False
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in PROMPT_INJECTION_PATTERNS)


def sanitize_ai_input(text: Optional[str]) -> str:
    value = "" if text is None else str(text)
    sanitized = _normalize_text(value)
    if not sanitized:
        return ""
    if has_prompt_injection_attempt(sanitized):
        logger.warning("Prompt injection attempt detected and normalized before LLM processing")
    return f"Task request: {sanitized}"


def validate_ai_output(text: Optional[str]) -> bool:
    if text is None:
        return False
    normalized = _normalize_text(str(text))
    if not normalized:
        return False
    return not any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in UNSAFE_OUTPUT_PATTERNS)


def _normalize_text(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _format_tool_summary(tool_results: Optional[str]) -> str:
    if not tool_results:
        return ""
    normalized = _normalize_text(tool_results)
    if len(normalized) > 260:
        return normalized[:257] + "..."
    return normalized


INTENT_LABELS = [
    "create",
    "complete",
    "update",
    "deadline",
    "stats",
    "search",
    "list",
    "general",
]

INTENT_KEYWORDS = {
    "create": ["create task", "new task", "add task", "make task", "create a task"],
    "complete": ["complete", "finish", "mark done", "done", "close task"],
    "update": ["update", "edit", "rename", "change task", "modify"],
    "deadline": ["deadline", "due", "when", "overdue", "by when"],
    "stats": ["stats", "count", "how many", "completed", "pending", "total tasks"],
    "search": ["search", "find", "look for", "where is", "query"],
    "list": ["list", "show", "what tasks", "tasks", "task list"],
}


def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _keyword_classify_intent(text: str) -> Optional[str]:
    lowered = text.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if _contains_any(lowered, keywords):
            return intent
    return None


def _classify_intent_with_model(text: str) -> str:
    prompt = (
        "Classify the intent of the user text below into one of these labels: "
        + ", ".join(INTENT_LABELS)
        + ".\nReturn only the single label.\n\n"
        + "Text: "
        + text.strip()
    )
    response = generate_response(prompt, model=DEFAULT_MODEL, temperature=0.0)
    normalized = response.strip().lower()
    for label in INTENT_LABELS:
        if normalized == label or normalized.startswith(label):
            return label
    for label in INTENT_LABELS:
        if label in normalized:
            return label
    return "general"


def _classify_intent(text: str) -> str:
    intent = _keyword_classify_intent(text)
    if intent:
        return intent
    if MISTRAL_API_KEY:
        return _classify_intent_with_model(text)
    return "general"


def _local_model_response(
    message: str,
    *,
    context: Optional[str] = None,
    tool_results: Optional[str] = None,
    force_natural: bool = False,
) -> str:
    """
    Lightweight deterministic fallback model for offline use.
    It does not try to be a full LLM, but it gives practical responses
    for task management, search, and general assistant prompts.
    """
    # Preprocess message to remove trailing user notes like "didn't work" which
    # often appear when users report an earlier failure and can confuse parsing.
    cleaned_message = _normalize_text(message)
    # Remove common trailing failure phrases
    cleaned_message = re.sub(r"\b(didn\'t work|didnt work|did not work|not updating|not updated|didn\'t update|not working)\b.*$", "", cleaned_message, flags=re.IGNORECASE)
    text = cleaned_message
    lowered = text.lower()
    context_summary = _normalize_text(context)
    tool_summary = _format_tool_summary(tool_results)
    intent = _classify_intent(lowered)

    if intent == "create":
        # Attempt to craft a JSON proposal when possible
        title = None
        description = None
        m = re.search(r'title\s*(?:as|:|=)\s*"([^"]+)"', message, flags=re.IGNORECASE)
        if m:
            title = m.group(1).strip()
        elif '"' in message:
            # fallback: first quoted string
            qm = re.search(r'"([^"]+)"', message)
            if qm:
                title = qm.group(1).strip()

        d = re.search(r'description\s*(?:as|:|=)\s*"([^"]+)"', message, flags=re.IGNORECASE)
        if d:
            description = d.group(1).strip()

        proposal = {
            "agent": "task_manager_001",
            "tool": "create_task",
            "args": {},
            "intent": "create",
            "confirm": False,
        }
        if title:
            proposal["args"]["title"] = title
        if description:
            proposal["args"]["description"] = description

        if proposal["args"] and not force_natural:
            return json.dumps(proposal)

        if proposal["args"]:
            title = proposal["args"].get("title")
            desc = proposal["args"].get("description")
            parts = []
            if title:
                parts.append(f"title '{title}'")
            if desc:
                parts.append(f"description: {desc}")
            details = ", ".join(parts)
            return f"I can create a task with {details}. Confirm to proceed."

        return (
            f"{LOCAL_AGENT_NAME}: I can help create a task. "
            "Please send the title, priority, and any notes or due date you want saved."
        )

    if intent == "complete":
        # Try to extract a numeric task id and return a proposal JSON
        match = re.search(r"\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b", message, flags=re.IGNORECASE)
        if match:
            task_id = int(match.group(1))
            proposal = {
                "agent": "task_manager_001",
                "tool": "complete_task",
                "args": {"task_id": task_id},
                "intent": "complete",
                "confirm": True,
            }
            if not force_natural:
                return json.dumps(proposal)
            return f"I can mark task #{task_id} as complete. Confirm to proceed."

        return (
            f"{LOCAL_AGENT_NAME}: I can help mark a task complete. "
            "Send the task ID or title and I’ll route the update."
        )

    if intent == "update":
        task_id = None
        # search in the cleaned text to avoid trailing notes
        match = re.search(r"\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b", text, flags=re.IGNORECASE)
        if match:
            task_id = int(match.group(1))

        title = None
        description = None
        # More tolerant matching for title/description assignments; search cleaned text
        title_match = re.search(r"\btitle\b\s*(?:to|as|is|=|:)\s*(?:\"(?P<title1>.*?)\"|'(?P<title2>.*?)'|(?P<title3>[^,.;]+))", text, flags=re.IGNORECASE)
        if title_match:
            title = title_match.group("title1") or title_match.group("title2") or title_match.group("title3")
        # Allow patterns like "description of task #9 to '...'", so find 'description' and then
        # look for the assignment keyword (to|as|is|=|:) later in the substring.
        description = None
        desc_pos = text.lower().find("description")
        if desc_pos != -1:
            desc_sub = text[desc_pos:]
            description_match = re.search(r"\b(?:to|as|is|=|:)\b\s*(?:\"(?P<desc1>.*?)\"|'(?P<desc2>.*?)'|(?P<desc3>[^,.;]+))", desc_sub, flags=re.IGNORECASE)
            if description_match:
                description = description_match.group("desc1") or description_match.group("desc2") or description_match.group("desc3")

        if task_id is not None and (title or description):
            proposal = {
                "agent": "task_manager_001",
                "tool": "update_task",
                "args": {"task_id": task_id},
                "intent": "update",
                "confirm": False,
            }
            if title:
                proposal["args"]["title"] = title.strip()
            if description:
                proposal["args"]["description"] = description.strip()
            if not force_natural:
                return json.dumps(proposal)
            changes = []
            if title:
                changes.append(f"set title to '{title.strip()}'")
            if description:
                changes.append(f"update description to '{description.strip()}'")
            return f"I can update task #{task_id} to {', '.join(changes)}. Confirm to proceed."

        return (
            f"{LOCAL_AGENT_NAME}: I can help update a task. "
            "Tell me which field should change and what the new value should be."
        )

    if intent == "deadline" and tool_summary:
        return (
            f"{LOCAL_AGENT_NAME} suggests: {tool_summary} "
            "If you need an exact due date, confirm the task details before relying on this."
        )

    if intent == "stats" and tool_summary:
        return f"{LOCAL_AGENT_NAME} summary: {tool_summary}"

    if intent == "list" and tool_summary:
        return f"{LOCAL_AGENT_NAME} summary: {tool_summary}"

    if intent == "search":
        if context_summary:
            return (
                f"{LOCAL_AGENT_NAME}: Based on the available context, the most relevant details appear to be: "
                f"{context_summary}"
            )
        return (
            f"{LOCAL_AGENT_NAME}: I don’t have enough indexed context yet, "
            "but I can still help narrow the search terms you should use."
        )

    if context_summary:
        return (
            f"{LOCAL_AGENT_NAME}: I’m using the provided context to answer. "
            f"Key details: {context_summary}"
        )

    if tool_summary:
        return f"{LOCAL_AGENT_NAME}: I found related task details: {tool_summary}"

    return (
        f"{LOCAL_AGENT_NAME}: I’m running in local fallback mode. "
        "I can still help with task summaries, search hints, and next-step guidance."
    )


def _build_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if MISTRAL_API_KEY:
        headers["Authorization"] = f"Bearer {MISTRAL_API_KEY}"
    return headers


def _extract_response_content(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return str(message.get("content", "")).strip()


def generate_response(
    prompt: str,
    context: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
) -> str:
    """
    Generate a response from the Mistral API when configured.
    If context is provided, it is prepended to the prompt for RAG.
    """
    safe_prompt = sanitize_ai_input(prompt)
    if has_prompt_injection_attempt(safe_prompt):
        logger.warning("Rejecting unsafe prompt injection attempt before LLM generation.")
        return (
            "I can help with task management requests. Please ask for concrete task actions or summaries "
            "without overriding instructions, revealing hidden prompts, or bypassing safeguards."
        )

    full_prompt = safe_prompt
    if context:
        full_prompt = f"Context:\n{context}\n\nQuestion: {safe_prompt}"

    if not MISTRAL_API_KEY:
        return _local_model_response(safe_prompt, context=context)

    try:
        logger.info(
            "Calling Mistral chat completion with model=%s timeout=%s verify_ssl=%s",
            model,
            HTTP_TIMEOUT,
            VERIFY_SSL,
        )
        response = requests.post(
            f"{MISTRAL_BASE_URL}/chat/completions",
            headers=_build_headers(),
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are TaskFlow AI, a concise task-management assistant for a productivity app. "
                            "Always produce a structured JSON proposal when you decide a tool/agent should be invoked. "
                            + PROPOSAL_INSTRUCTION
                        ),
                    },
                    {"role": "user", "content": full_prompt},
                ],
                "temperature": temperature,
            },
            timeout=HTTP_TIMEOUT,
            verify=VERIFY_SSL,
        )
        response.raise_for_status()
        content = _extract_response_content(response.json())
        logger.info("Mistral response received successfully (chars=%s)", len(content))
        return content
    except Exception as exc:
        logger.warning("Mistral request failed, falling back to local response: %s", exc)
        return _local_model_response(prompt, context=context)


async def chat_with_tools(
    user_message: str,
    context: Optional[str] = None,
    tool_results: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    force_natural: bool = False,
) -> str:
    """
    Async chat completion using the Mistral API.
    """
    safe_user_message = sanitize_ai_input(user_message)
    if has_prompt_injection_attempt(safe_user_message):
        logger.warning("Unsafe prompt detected in chat request; returning a safe fallback response.")
        return _local_model_response(
            "I can help with task management requests. Please ask for concrete task actions or summaries without overriding instructions, revealing hidden prompts, or bypassing safeguards.",
            context=context,
            tool_results=tool_results,
            force_natural=True,
        )

    if not MISTRAL_API_KEY:
        logger.warning("Mistral API key missing; using local fallback response for chat")
        return _local_model_response(
            safe_user_message,
            context=context,
            tool_results=tool_results,
            force_natural=force_natural,
        )

    if force_natural:
        system_prompt = (
            "You are TaskFlow AI, a concise task-management assistant for a productivity app. "
            "Answer in plain natural language and do not output JSON proposals. "
            "When tool results are available, use them as the primary source of truth and mention task IDs when present. "
        )
    else:
        system_prompt = (
        "You are TaskFlow AI, a concise task-management assistant for a productivity app. "
        "Your job is to help users create, review, update, search, summarize, and prioritize tasks. "
        "Always answer in a practical, user-friendly way. "
        "If tool results are available, use them as the primary source of truth and mention task IDs when present. "
        "When tool results contain task lists, include the title, status, and a short description for each task. "
        "When tool results contain statistics, clearly report completed, pending, and total counts. "
        "When context is relevant, use it to support the answer; if it is unrelated, ignore it. "
        "Do not invent deadlines, ownership, or schedule details that are not provided. "
        "If the user asks to create or update a task, ask for the missing fields only if needed. "
        "If the request is ambiguous, briefly ask a clarifying question instead of guessing."
        + "\n\n" + PROPOSAL_INSTRUCTION
    )

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt}
    ]

    user_payload = f"User Question: {safe_user_message}"
    if context:
        user_payload += f"\n\nRelevant Context:\n{context}"
    if tool_results:
        user_payload += f"\n\nTool Results:\n{tool_results}"

    messages.append({"role": "user", "content": user_payload})

    try:
        logger.info(
            "Calling Mistral async chat completion with model=%s timeout=%s verify_ssl=%s",
            model,
            HTTP_TIMEOUT,
            VERIFY_SSL,
        )
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, verify=VERIFY_SSL) as client:
            response = await client.post(
                f"{MISTRAL_BASE_URL}/chat/completions",
                headers=_build_headers(),
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7,
                },
                timeout=HTTP_TIMEOUT,
            )
            response.raise_for_status()
            content = _extract_response_content(response.json())
            logger.info("Mistral async response received successfully (chars=%s)", len(content))
            if not validate_ai_output(content):
                logger.warning("LLM response failed output guardrail validation and was rejected.")
                return _local_model_response(
                    safe_user_message,
                    context=context,
                    tool_results=tool_results,
                    force_natural=force_natural,
                )
            return content
    except Exception as exc:
        logger.warning(
            "Mistral async request failed, falling back to local response: %s",
            exc,
        )
        return _local_model_response(
            safe_user_message,
            context=context,
            tool_results=tool_results,
        )


async def check_ollama_health() -> bool:
    """Check whether a usable LLM provider configuration is available."""
    return bool(MISTRAL_API_KEY)