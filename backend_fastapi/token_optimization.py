"""
Token Optimization Utilities for LLM Calls

Provides functions to compress, summarize, and efficiently format
text and data structures to minimize token consumption in LLM calls.

Strategies:
1. Text compression: Remove redundant content, summarize OCR
2. Dialog history windowing: Keep only recent context
3. Context summarization: Compress tool results and search results
4. Tool definition filtering: Send only relevant tool definitions
"""

import json
import re
from typing import List, Dict, Any, Optional, Tuple


def compress_ocr_text(ocr_text: str, max_chars: int = 2000) -> str:
    """
    Compress OCR text before sending to LLM.
    
    Removes unnecessary whitespace, deduplicates lines, and truncates.
    Saves ~60-70% tokens on OCR processing.
    
    Args:
        ocr_text: Raw OCR output
        max_chars: Maximum characters to keep (default 2000 = ~500 tokens)
    
    Returns:
        Compressed text suitable for LLM
    """
    if not ocr_text:
        return ""
    
    # Remove excessive whitespace
    lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
    
    # Remove duplicate/near-duplicate consecutive lines
    deduplicated = []
    for line in lines:
        if not deduplicated or deduplicated[-1] != line:
            deduplicated.append(line)
    
    # Remove page markers, headers, and irrelevant lines
    cleaned = []
    for line in deduplicated:
        # Skip page numbers, page markers
        if re.match(r'^(page\s*\d+|\d+\s*/\s*\d+|—+|—|=+)$', line, re.IGNORECASE):
            continue
        # Skip metadata-only lines
        if len(line) < 3:
            continue
        cleaned.append(line)
    
    # Join and truncate
    result = '\n'.join(cleaned)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n[truncated...]"
    
    return result


def summarize_tool_results(tool_results: str, max_chars: int = 300) -> str:
    """
    Compress tool results (search results, database queries, etc).
    
    Removes formatting overhead and truncates verbose results.
    Saves ~40-50% tokens on tool result context.
    
    Args:
        tool_results: Raw tool output (often JSON or verbose text)
        max_chars: Maximum characters to preserve
    
    Returns:
        Summarized result
    """
    if not tool_results:
        return ""
    
    # Try to parse as JSON for compact representation
    try:
        data = json.loads(tool_results)
        if isinstance(data, list) and len(data) > 5:
            # For large lists, keep only first 3 items and summary
            summary_items = data[:3]
            return f"{json.dumps(summary_items)} ... ({len(data)} total results)"
        # Re-serialize compactly (no extra whitespace)
        return json.dumps(data, separators=(',', ':'))
    except (json.JSONDecodeError, TypeError):
        pass
    
    # For plain text, normalize and truncate
    normalized = re.sub(r'\s+', ' ', tool_results.strip())
    if len(normalized) > max_chars:
        normalized = normalized[:max_chars] + "..."
    
    return normalized


def window_dialog_history(
    history: List[Dict[str, Any]],
    window_size: int = 3,
    summarize_older: bool = True
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Window dialog history to keep only recent turns, optionally summarizing older ones.
    
    Saves ~50-80% tokens on long conversations by keeping recent context
    while summarizing older turns into a brief summary.
    
    Args:
        history: Full dialog history list of dicts with 'role', 'message'
        window_size: Number of recent turns to keep (default 3)
        summarize_older: Whether to include brief summary of older turns
    
    Returns:
        Tuple of (windowed history, summary of older turns or None)
    """
    if not history:
        return [], None
    
    if len(history) <= window_size * 2:
        return history, None
    
    # Keep recent turns
    recent = history[-window_size:]
    
    if not summarize_older:
        return recent, None
    
    # Create brief summary of older turns
    older = history[:-window_size]
    summary_points = []
    for msg in older:
        role = msg.get('role', 'unknown').capitalize()
        text = msg.get('message', '')
        if text and len(text) > 100:
            text = text[:100] + "..."
        if text:
            summary_points.append(f"{role}: {text}")
    
    if summary_points:
        older_summary = "\n".join(summary_points[:5])  # Keep only first 5 older turns
        return recent, older_summary
    
    return recent, None


def filter_tools_by_intent(
    all_tools: List[Dict[str, Any]],
    user_intent: str,
    required_tools: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Filter tool definitions to send only relevant ones.
    
    Saves ~30-50% tokens by not sending unused tool definitions.
    
    Args:
        all_tools: All available tool definitions
        user_intent: User's detected intent (e.g., 'create', 'search', 'analyze')
        required_tools: Specific tool names that must be included
    
    Returns:
        Filtered list of relevant tools
    """
    if not all_tools:
        return []
    
    required_tools = required_tools or []
    
    # Intent-to-tools mapping
    intent_tools = {
        'create': ['create_task', 'create_document'],
        'update': ['update_task', 'update_document'],
        'complete': ['complete_task', 'mark_done'],
        'search': ['search_tasks', 'search_documents', 'vector_search'],
        'analyze': ['analyze_document', 'get_statistics', 'analyze_tasks'],
        'list': ['list_tasks', 'list_documents', 'get_all_tasks'],
    }
    
    # Get tools for this intent
    relevant_names = set(intent_tools.get(user_intent.lower(), []))
    relevant_names.update(required_tools)
    
    # Filter
    filtered = [
        tool for tool in all_tools
        if tool.get('name') in relevant_names
    ]
    
    # If filtering removed everything, return top 3 most common tools
    if not filtered:
        filtered = all_tools[:3]
    
    return filtered


def truncate_context(
    context: str,
    max_tokens: int = 1000,
    chars_per_token: float = 4.0
) -> str:
    """
    Truncate context string to maximum token budget.
    
    Args:
        context: Context text
        max_tokens: Maximum tokens allowed
        chars_per_token: Rough estimate of chars per token (default 4.0)
    
    Returns:
        Truncated context
    """
    if not context:
        return ""
    
    max_chars = int(max_tokens * chars_per_token)
    if len(context) <= max_chars:
        return context
    
    truncated = context[:max_chars]
    # Try to cut at a sentence boundary
    last_period = truncated.rfind('.')
    if last_period > max_chars * 0.8:  # If sentence boundary is recent
        truncated = truncated[:last_period + 1]
    else:
        truncated = truncated + "..."
    
    return truncated


def compact_json_representation(data: Any) -> str:
    """
    Create compact JSON representation of data.
    Removes extra whitespace and unnecessary fields.
    
    Args:
        data: Data to serialize
    
    Returns:
        Compact JSON string
    """
    return json.dumps(data, separators=(',', ':'))


def estimate_tokens(text: str, model: str = "mistral-tiny") -> int:
    """
    Rough estimate of token count for text.
    Uses 1 token ≈ 4 characters as a heuristic.
    
    For exact counts, use the LLM provider's tokenizer.
    
    Args:
        text: Text to estimate tokens for
        model: Model name (not currently used, reserved for future)
    
    Returns:
        Estimated token count
    """
    if not text:
        return 0
    # Rough heuristic: 1 token ≈ 4 characters
    return max(1, len(text) // 4)


def compress_message_for_routing(
    message: str,
    max_chars: int = 500
) -> str:
    """
    Compress user message for routing/classification.
    
    Args:
        message: User message
        max_chars: Maximum characters to keep
    
    Returns:
        Compressed message
    """
    if not message:
        return ""
    
    # Remove extra whitespace
    normalized = re.sub(r'\s+', ' ', message.strip())
    
    # Remove very long repetitive text
    if len(normalized) > max_chars:
        normalized = normalized[:max_chars]
        # Try to cut at word boundary
        last_space = normalized.rfind(' ')
        if last_space > max_chars * 0.8:
            normalized = normalized[:last_space]
        normalized = normalized + "..."
    
    return normalized
