"""
Specific agent implementations for different tasks.
"""

from typing import Any, Dict, List, Optional, Tuple
import json
import re
from datetime import datetime
from ..mistral_client import chat_with_tools
from ..rag_tools import (
    extract_create_task_fields,
    extract_create_task_titles,
    looks_like_explicit_create_task_request,
    looks_like_task_status_update_request,
    normalize_task_search_query,
    _detect_explicit_date_constraint,
    _detect_task_status_filter,
    _task_priority_bucket,
)
from .agent_base import Agent, AgentMessage, AgentRole, AgentStatus


def _log_agent_event(agent_name: str, event: str, payload: Any) -> None:
    print(
        f"[AI-AGENT] {event} | agent={agent_name} | payload={json.dumps(payload, default=str, ensure_ascii=False)}"
    )


def _log_agent_result(agent_name: str, result: Any) -> None:
    print(
        f"[AI-AGENT] result | agent={agent_name} | result={json.dumps(result, default=str, ensure_ascii=False)}"
    )


class TaskAgent(Agent):
    """Agent responsible for task management and workflow orchestration."""
    
    def __init__(self):
        super().__init__(
            agent_id="task_manager_001",
            role=AgentRole.TASK_MANAGER,
            name="Task Manager",
            description="Manages task creation, updates, tracking, and completion"
        )
    
    async def process_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """Process task messages if routed through the message bus."""
        return None
    
    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute task management operations."""
        self.set_status(AgentStatus.PROCESSING)
        
        try:
            operation = task.get("operation")
            mcp_server = task.get("mcp_server")
            
            if operation == "list_tasks":
                return await self._list_tasks(task, mcp_server)
            elif operation == "get_task":
                return await self._get_task(task)
            elif operation == "complete_task":
                return await self._complete_task(task, mcp_server)
            elif operation == "reopen_task":
                return await self._reopen_task(task, mcp_server)
            elif operation == "delete_task":
                return await self._delete_task(task, mcp_server)
            elif operation == "update_task":
                return await self._update_task(task, mcp_server)
            elif operation == "search_and_create":
                return await self._search_and_create_summary(task, mcp_server)
            elif operation == "search_and_complete":
                return await self._search_and_complete(task, mcp_server)
            elif operation == "search_and_reopen":
                return await self._search_and_reopen(task, mcp_server)
            elif operation == "search_and_delete":
                return await self._search_and_delete(task, mcp_server)
            elif operation == "preview_mutation":
                return await self._preview_mutation(task, mcp_server)
            
            return {"status": "error", "message": f"Unknown operation: {operation}"}
        finally:
            self.set_status(AgentStatus.IDLE)

    async def _preview_mutation(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Resolve, but never execute, the tasks selected by a mutation request."""
        if not mcp_server:
            return {"status": "error", "message": "MCP server not available", "tasks": []}

        from ..mcp_server import ToolCallRequest

        user_input = task.get("user_input", "")
        target_operation = task.get("target_operation", "")
        if "complete" in target_operation:
            action_name = "complete_task"
        elif "reopen" in target_operation:
            action_name = "reopen_task"
        else:
            action_name = "delete_task"
        query = self._normalize_search_query_for_action(user_input, action_name=action_name)
        explicit_id = task.get("task_id")
        if explicit_id is None:
            id_match = re.search(r"\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b", user_input, flags=re.IGNORECASE)
            explicit_id = int(id_match.group(1)) if id_match else None

        # "complete them" refers to the preceding search clause.
        split_match = re.search(
            r"^(?P<search>.+?)\s+(?:and|then)\s+"
            r"(?:complete|completed|done|finish|finished|mark done|mark as done|close|"
            r"reopen|re-open|open again|uncomplete|undo complete|mark pending|mark not done)\s+"
            r"(?:them|these|those|it)\b",
            user_input,
            flags=re.IGNORECASE,
        )
        if action_name in {"complete_task", "reopen_task"} and split_match:
            query = split_match.group("search").strip()

        if explicit_id is not None:
            result = await mcp_server.call_tool(ToolCallRequest(tool_name="list_tasks", arguments={"limit": 100}))
            tasks = result.result.get("results", []) if result.success and isinstance(result.result, dict) else []
            tasks = [item for item in tasks if (item.get("id") or item.get("task_id")) == explicit_id]
        else:
            result = await mcp_server.call_tool(
                ToolCallRequest(tool_name="search_tasks", arguments={"query": query, "limit": 20})
            )
            tasks = result.result.get("results", []) if result.success and isinstance(result.result, dict) else []
            tasks = self._filter_action_results_by_all_terms(tasks, query)
        if action_name == "complete_task":
            tasks = [item for item in tasks if self._task_is_pending(item)]
        elif action_name == "reopen_task":
            tasks = [item for item in tasks if self._task_is_completed(item)]

        return {
            "status": "success",
            "message": f"Preview found {len(tasks)} task(s)",
            "tasks_found": len(tasks),
            "tasks": tasks,
        }
    
    async def _list_tasks(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """List tasks using MCP server. Passes optional status filters from user_input."""
        if not mcp_server:
            return {"status": "error", "tasks": [], "message": "MCP server not available"}

        try:
            from ..mcp_server import ToolCallRequest

            user_input = task.get("user_input", "") or ""
            self.logger.info(f"[TASK_AGENT] _list_tasks called with user_input: '{user_input}'")

            status_filter = _detect_task_status_filter(user_input)
            completed = status_filter
            if status_filter is None:
                normalized = user_input.lower()
                if any(keyword in normalized for keyword in ["completed", "done", "finished", "closed"]):
                    completed = True
                elif any(keyword in normalized for keyword in ["pending", "open", "incomplete", "unfinished", "not done", "undone"]):
                    completed = False

            # If the user's input contains an explicit date constraint (e.g. "due by 10th July"),
            # prefer the `search_tasks` tool which understands natural-language date filters.
            explicit_date = _detect_explicit_date_constraint(user_input)
            if explicit_date:
                request = ToolCallRequest(tool_name="search_tasks", arguments={"query": user_input})
                self.logger.info(f"[TASK_AGENT] Detected explicit date constraint; calling search_tasks with query='{user_input}'")
            else:
                request = ToolCallRequest(
                    tool_name="list_tasks",
                    arguments={"limit": 100, "offset": 0, "completed": completed},
                )
                self.logger.info(f"[TASK_AGENT] Calling list_tasks with completed={completed}")

            result = await mcp_server.call_tool(request)

            if result.success:
                if isinstance(result.result, dict) and "results" in result.result:
                    tasks = result.result.get("results", [])
                else:
                    tasks = result.result or []
                count = len(tasks) if isinstance(tasks, list) else 0
                self.logger.info(f"[TASK_AGENT] list_tasks succeeded: found {count} tasks")
                return {"status": "success", "tasks": tasks, "count": count}
            else:
                self.logger.error(f"[TASK_AGENT] list_tasks failed: {result.error}")
                return {"status": "error", "message": result.error, "tasks": []}
        except Exception as e:
            self.logger.error(f"[TASK_AGENT] Error in _list_tasks: {e}")
            return {"status": "error", "message": str(e), "tasks": []}
    
    async def _get_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Get task details."""
        task_id = task.get("task_id")
        return {"status": "success", "task_id": task_id, "data": {}}

    async def _update_task(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Update a task through the MCP server."""
        if not mcp_server:
            return {"status": "error", "message": "MCP server not available"}

        try:
            from ..mcp_server import ToolCallRequest

            task_id = task.get("task_id")
            title = task.get("title")
            description = task.get("description")

            if task_id is None:
                return {"status": "error", "message": "No task ID provided"}
            if title is None and description is None:
                return {"status": "error", "message": "No update fields provided. Please provide title or description."}

            request = ToolCallRequest(
                tool_name="update_task",
                arguments={"task_id": int(task_id), "title": title, "description": description},
            )
            result = await mcp_server.call_tool(request)

            if result.success:
                payload = result.result or {}
                return {
                    "status": "success",
                    "tool_name": "update_task",
                    "tool_result_status": payload.get("status"),
                    **{k: v for k, v in payload.items() if k != "status"},
                }

            return {"status": "error", "message": result.error or "Task update failed"}
        except Exception as e:
            self.logger.error(f"[TASK_AGENT] Error updating task: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def _sort_tasks_by_deadline(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def sort_key(item: Dict[str, Any]):
            title = item.get("title", "") or ""
            description = item.get("description", "") or ""
            sort_bucket, _, scheduled_at = _task_priority_bucket(title, description, datetime.now())
            scheduled_at = scheduled_at or datetime.max
            return (sort_bucket, scheduled_at, item.get("id") or item.get("task_id") or 0)

        return sorted(tasks, key=sort_key)

    def _extract_task_id_for_action(self, user_input: str, patterns: List[str]) -> Optional[int]:
        """Extract a task ID for a specific action from a combined prompt."""
        if not user_input:
            return None

        for pattern in patterns:
            match = re.search(pattern, user_input, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))

        fallback_match = re.search(r"\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b", user_input, flags=re.IGNORECASE)
        if fallback_match:
            return int(fallback_match.group(1))
        return None

    def _normalize_search_query_for_action(self, user_input: str, action_name: Optional[str] = None) -> str:
        if not user_input:
            return ""

        # In a combined request, the text after the action describes the action
        # target. Example: search authentication tasks, then complete Q3 tasks.
        query = user_input
        action_pattern = {
            "complete_task": r"\b(?:complete|completed|done|finish|finished|mark done|mark as done|close)\b\s+(.*)$",
            "reopen_task": r"\b(?:reopen|re-open|open again|uncomplete|undo complete|mark pending|mark not done)\b\s+(.*)$",
            "delete_task": r"\b(?:delete|deleted|remove|removed|erase|erased|trash|trashed|discard|discarded)\b\s+(.*)$",
        }.get(action_name or "")
        if action_pattern:
            action_match = re.search(action_pattern, user_input, flags=re.IGNORECASE)
            if action_match and action_match.group(1).strip():
                query = action_match.group(1)

        # A trailing list/search clause is a separate request, not part of the
        # mutation target (for example: "complete authentication and list all").
        query = re.split(
            r"\s+(?:and|then)\s+(?:list|show|display|get|find|search)\b",
            query,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        query = re.sub(r"\b(?:task|tasks)\b", "", query, flags=re.IGNORECASE)
        query = re.sub(
            r"\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?\d+)\b", "", query, flags=re.IGNORECASE
        )
        query = re.sub(
            r"\b(?:complete|completed|done|finish|finished|mark done|mark as done|close|reopen|re-open|open again|uncomplete|undo complete|mark pending|mark not done|delete|deleted|remove|removed|erase|erased|trash|trashed|discard|discarded)\b",
            "",
            query,
            flags=re.IGNORECASE,
        )
        if action_name == "reopen_task":
            query = re.sub(
                r"\b(?:completed|done|finished|closed|pending|open|incomplete|unfinished|not done|undone)\b",
                "",
                query,
                flags=re.IGNORECASE,
            )
        elif action_name == "complete_task":
            query = re.sub(
                r"\b(?:completed|done|finished|closed)\b",
                "",
                query,
                flags=re.IGNORECASE,
            )

        query = re.sub(
            r"\b(?:any|all|these|those|the|that|them|remaining|ones|please|kindly|also|then|and|with)\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(r"[^\w\s]", " ", query)
        query = re.sub(r"\s+", " ", query).strip()
        return query if query else user_input.strip()

    def _filter_action_results_by_all_terms(self, tasks: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """Keep only tasks satisfying every meaningful term in a bulk-action query.

        Search is intentionally permissive so it can surface related tasks. Before
        mutating tasks, however, a query such as "authentication ... related to Q3"
        must match both ``authentication`` and ``q3`` on the same task.
        """
        non_constraint_terms = {
            "any", "all", "ones", "remaining", "pending", "open",
            "incomplete", "undone", "unfinished", "not", "done",
        }
        terms = [
            term
            for term in re.findall(r"[a-z0-9]+", normalize_task_search_query(query).lower())
            if term not in non_constraint_terms
        ]
        if not terms:
            return list(tasks)

        filtered_tasks = []
        for task in tasks:
            task_tokens = set(re.findall(
                r"[a-z0-9]+",
                f"{task.get('title') or ''} {task.get('description') or ''}".lower(),
            ))
            if all(term in task_tokens for term in terms):
                filtered_tasks.append(task)
        return filtered_tasks

    def _task_is_completed(self, task: Dict[str, Any]) -> bool:
        if not isinstance(task, dict):
            return False
        if task.get("completed") is not None:
            return bool(task.get("completed"))
        status = str(task.get("status", "")).lower()
        return status in {"completed", "done", "closed", "finished"}

    def _task_is_pending(self, task: Dict[str, Any]) -> bool:
        return not self._task_is_completed(task)

    def _is_explicit_bulk_action(self, user_input: str) -> bool:
        if not user_input:
            return False

        if re.search(
            r"\b(all|every|every one|everything|these|those|them|that|remaining|ones|bulk|all of them)\b",
            user_input,
            flags=re.IGNORECASE,
        ):
            return True

        # Treat explicit plural delete/remove actions as bulk when the user refers to tasks by status.
        if re.search(
            r"\b(?:delete|deleted|remove|removed|erase|erased|trash|trashed|discard|discarded)\b[^\n]*\b(?:tasks|completed tasks|pending tasks|open tasks|incomplete tasks|finished tasks|done tasks)\b",
            user_input,
            flags=re.IGNORECASE,
        ):
            return True

        return False

    async def _complete_task(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Complete a task via the MCP server. Supports single task or bulk completion from search results."""
        if not mcp_server:
            return {"status": "error", "message": "MCP server not available"}

        try:
            from ..mcp_server import ToolCallRequest

            # Check if this is a bulk operation on searched tasks
            last_searched_tasks = task.get("last_searched_tasks")
            user_input = task.get("user_input", "") or ""
            
            if last_searched_tasks and isinstance(last_searched_tasks, list):
                # Filter tasks based on user intent (e.g., "complete any that are pending")
                tasks_to_complete = []
                
                if re.search(r"\b(pending|not done|incomplete|open)\b", user_input, flags=re.IGNORECASE):
                    # Complete only pending tasks
                    tasks_to_complete = [t for t in last_searched_tasks if self._task_is_pending(t)]
                elif re.search(r"\b(finished|completed|done)\b", user_input, flags=re.IGNORECASE):
                    # Already completed, no action needed
                    return {"status": "success", "message": "Tasks already completed", "completed_count": 0}
                else:
                    # Default: complete all searched tasks
                    tasks_to_complete = last_searched_tasks
                
                if not tasks_to_complete:
                    return {"status": "success", "message": "No matching tasks to complete", "completed_count": 0}
                
                # Bulk complete
                completed_count = 0
                failed_count = 0
                for t in tasks_to_complete:
                    task_id = t.get("id") or t.get("task_id")
                    if task_id is None:
                        failed_count += 1
                        continue
                    
                    try:
                        request = ToolCallRequest(tool_name="complete_task", arguments={"task_id": int(task_id)})
                        result = await mcp_server.call_tool(request)
                        if result.success:
                            completed_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        self.logger.debug(f"Error completing task {task_id}: {e}")
                        failed_count += 1
                
                return {
                    "status": "success",
                    "message": f"Completed {completed_count} tasks",
                    "completed_count": completed_count,
                    "failed_count": failed_count,
                }
            
            # Single task completion
            task_id = task.get("task_id")
            if task_id is None:
                match = re.search(r"\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b", user_input, flags=re.IGNORECASE)
                if match:
                    task_id = int(match.group(1))

            if task_id is None:
                return {"status": "error", "message": "No task ID provided"}

            request = ToolCallRequest(tool_name="complete_task", arguments={"task_id": int(task_id)})
            result = await mcp_server.call_tool(request)
            if result.success:
                payload = result.result or {}
                return {
                    "status": "success",
                    "tool_name": "complete_task",
                    "tool_result_status": payload.get("status"),
                    **{k: v for k, v in payload.items() if k != "status"},
                }
            return {"status": "error", "message": result.error or "Task completion failed"}
        except Exception as e:
            self.logger.error(f"[TASK_AGENT] Error completing task: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def _reopen_task(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Reopen a task via the MCP server. Supports single task or bulk reopen from search results."""
        if not mcp_server:
            return {"status": "error", "message": "MCP server not available"}

        try:
            from ..mcp_server import ToolCallRequest

            # Check if this is a bulk operation on searched tasks
            last_searched_tasks = task.get("last_searched_tasks")
            user_input = task.get("user_input", "") or ""
            
            if last_searched_tasks and isinstance(last_searched_tasks, list):
                # Filter tasks based on user intent (e.g., "reopen any that are completed")
                tasks_to_reopen = []
                
                if re.search(r"\b(completed|done|closed|finished)\b", user_input, flags=re.IGNORECASE):
                    # Reopen only completed tasks
                    tasks_to_reopen = [t for t in last_searched_tasks if self._task_is_completed(t)]
                elif re.search(r"\b(pending|open|incomplete)\b", user_input, flags=re.IGNORECASE):
                    # Already open, no action needed
                    return {"status": "success", "message": "Tasks already open", "reopened_count": 0}
                else:
                    # Default: reopen all searched tasks
                    tasks_to_reopen = last_searched_tasks
                
                if not tasks_to_reopen:
                    return {"status": "success", "message": "No matching tasks to reopen", "reopened_count": 0}
                
                # Bulk reopen
                reopened_count = 0
                failed_count = 0
                for t in tasks_to_reopen:
                    task_id = t.get("id") or t.get("task_id")
                    if task_id is None:
                        failed_count += 1
                        continue
                    
                    try:
                        request = ToolCallRequest(tool_name="reopen_task", arguments={"task_id": int(task_id)})
                        result = await mcp_server.call_tool(request)
                        if result.success:
                            reopened_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        self.logger.debug(f"Error reopening task {task_id}: {e}")
                        failed_count += 1
                
                return {
                    "status": "success",
                    "message": f"Reopened {reopened_count} tasks",
                    "reopened_count": reopened_count,
                    "failed_count": failed_count,
                }
            
            # Single task reopen
            task_id = task.get("task_id")
            if task_id is None:
                match = re.search(r"\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b", user_input, flags=re.IGNORECASE)
                if match:
                    task_id = int(match.group(1))

            if task_id is None:
                return {"status": "error", "message": "No task ID provided"}

            request = ToolCallRequest(tool_name="reopen_task", arguments={"task_id": int(task_id)})
            result = await mcp_server.call_tool(request)
            if result.success:
                payload = result.result or {}
                return {
                    "status": "success",
                    "tool_name": "reopen_task",
                    "tool_result_status": payload.get("status"),
                    **{k: v for k, v in payload.items() if k != "status"},
                }
            return {"status": "error", "message": result.error or "Task reopen failed"}
        except Exception as e:
            self.logger.error(f"[TASK_AGENT] Error reopening task: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def _delete_task(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Delete a task via the MCP server. Supports single task or bulk deletion from search results."""
        if not mcp_server:
            return {"status": "error", "message": "MCP server not available"}

        try:
            from ..mcp_server import ToolCallRequest

            # Check if this is a bulk operation on searched tasks
            last_searched_tasks = task.get("last_searched_tasks")
            user_input = task.get("user_input", "") or ""
            
            if last_searched_tasks and isinstance(last_searched_tasks, list):
                # Filter tasks based on user intent (e.g., "delete any that are completed")
                tasks_to_delete = []
                
                if re.search(r"\b(completed|done|closed|finished)\b", user_input, flags=re.IGNORECASE):
                    # Delete only completed tasks
                    tasks_to_delete = [t for t in last_searched_tasks if self._task_is_completed(t)]
                elif re.search(r"\b(pending|open|incomplete)\b", user_input, flags=re.IGNORECASE):
                    # Delete only pending tasks
                    tasks_to_delete = [t for t in last_searched_tasks if self._task_is_pending(t)]
                else:
                    # Default: do not delete all matching tasks unless user explicitly asked for a bulk delete.
                    if self._is_explicit_bulk_action(user_input) or len(last_searched_tasks) == 1:
                        tasks_to_delete = last_searched_tasks
                    else:
                        return {
                            "status": "error",
                            "message": "Multiple tasks match this delete request. Specify a task id or say 'delete all matching tasks' to remove them all.",
                        }
                
                if not tasks_to_delete:
                    return {"status": "success", "message": "No matching tasks to delete", "deleted_count": 0}
                
                # Bulk delete
                deleted_count = 0
                failed_count = 0
                for t in tasks_to_delete:
                    task_id = t.get("id") or t.get("task_id")
                    if task_id is None:
                        failed_count += 1
                        continue
                    
                    try:
                        request = ToolCallRequest(tool_name="delete_task", arguments={"task_id": int(task_id)})
                        result = await mcp_server.call_tool(request)
                        if result.success:
                            deleted_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        self.logger.debug(f"Error deleting task {task_id}: {e}")
                        failed_count += 1
                
                return {
                    "status": "success",
                    "message": f"Deleted {deleted_count} tasks",
                    "deleted_count": deleted_count,
                    "failed_count": failed_count,
                }
            
            # Single task deletion
            task_id = task.get("task_id")
            user_input = task.get("user_input", "") or ""
            if task_id is None:
                match = re.search(r"\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b", user_input, flags=re.IGNORECASE)
                if match:
                    task_id = int(match.group(1))

            if task_id is None:
                return {"status": "error", "message": "No task ID provided"}

            request = ToolCallRequest(tool_name="delete_task", arguments={"task_id": int(task_id)})
            result = await mcp_server.call_tool(request)
            if result.success:
                payload = result.result or {}
                return {
                    "status": "success",
                    "tool_name": "delete_task",
                    "tool_result_status": payload.get("status"),
                    **{k: v for k, v in payload.items() if k != "status"},
                }
            return {"status": "error", "message": result.error or "Task deletion failed"}
        except Exception as e:
            self.logger.error(f"[TASK_AGENT] Error deleting task: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def _search_and_create_summary(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Search for tasks matching user input and create a summary task."""
        if not mcp_server:
            return {"status": "error", "message": "MCP server not available"}
        
        try:
            from ..mcp_server import ToolCallRequest
            
            user_input = task.get("user_input", "")
            self.logger.info(f"[TASK_AGENT] _search_and_create_summary called with: {user_input}")

            # Handle two independent clauses such as "search API tasks and create
            # a task for API rate limiter". Keep the searched tasks in the main
            # response instead of letting the creation clause replace them.
            search_create_match = re.match(
                r"^(?P<search>.+?)\s+(?:and|then)\s+"
                r"(?:create|add|make)\b(?:\s+(?:a|new))?\s*task\s+"
                r"(?:for|about|titled?|on|regarding)\s+(?P<title>.+?)\s*[.!?]?$",
                user_input,
                flags=re.IGNORECASE,
            )
            if search_create_match:
                search_query = search_create_match.group("search").strip()
                title = search_create_match.group("title").strip(" ,.;:-\"'")

                search_request = ToolCallRequest(
                    tool_name="search_tasks",
                    arguments={"query": search_query, "limit": 10},
                )
                search_result = await mcp_server.call_tool(search_request)
                searched_tasks = (
                    search_result.result.get("results", [])
                    if search_result.success and isinstance(search_result.result, dict)
                    else []
                )
                # A user asking for API tasks expects an actual API token, not a
                # loosely related semantic result.
                searched_tasks = self._filter_action_results_by_all_terms(searched_tasks, search_query)

                create_request = ToolCallRequest(
                    tool_name="create_task",
                    arguments={"title": title, "description": ""},
                )
                create_result = await mcp_server.call_tool(create_request)
                if not create_result.success:
                    return {
                        "status": "partial_success",
                        "message": f"Found {len(searched_tasks)} matching task(s), but could not create '{title}'",
                        "tasks_found": len(searched_tasks),
                        "tasks": searched_tasks,
                    }

                return {
                    "status": "success",
                    "message": f"Found {len(searched_tasks)} matching task(s) and created '{title}'",
                    "tasks_found": len(searched_tasks),
                    "tasks": searched_tasks,
                    "found_tasks": searched_tasks,
                    "created_task": create_result.result,
                }

            status_action = looks_like_task_status_update_request(user_input)
            action_requests: List[Tuple[str, Optional[int]]] = []

            if status_action == "complete_task":
                task_id = self._extract_task_id_for_action(
                    user_input,
                    [r"\b(?:complete|completed|done|finish|mark done|mark as done|close)\b[^\n.]{0,40}?\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b"],
                )
                action_requests.append(("complete_task", task_id))
            elif status_action == "reopen_task":
                task_id = self._extract_task_id_for_action(
                    user_input,
                    [r"\b(?:reopen|re-open|open again|uncomplete|undo complete|mark pending|mark not done)\b[^\n.]{0,40}?\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b"],
                )
                action_requests.append(("reopen_task", task_id))

            delete_patterns = [r"\b(?:delete|remove|erase|trash|discard)\b[^\n.]{0,40}?\b(?:task\s*(?:with\s+)?(?:id\s*)?#?|id\s*#?)(\d+)\b"]
            if re.search(r"\b(delete|deleted|remove|removed|erase|erased|trash|trashed|discard|discarded)\b", user_input, flags=re.IGNORECASE):
                task_id = self._extract_task_id_for_action(user_input, delete_patterns)
                action_requests.append(("delete_task", task_id))

            explicit_due_date = _detect_explicit_date_constraint(user_input)
            priority_request = bool(re.search(r"\b(prioritize|prioritise|priority|rank|sort|order|urgency|soon|asap|earliest|due date)\b", user_input, flags=re.IGNORECASE))

            list_request = bool(re.search(r"\b(list|show|display|get|find)\b.*\b(task|tasks)\b", user_input, flags=re.IGNORECASE))
            create_title, create_description = "", ""
            created_task = None
            create_titles = extract_create_task_titles(user_input)
            if looks_like_explicit_create_task_request(user_input):
                create_title, create_description = extract_create_task_fields(user_input)

            if create_titles:
                if len(create_titles) > 1:
                    self.logger.info("[TASK_AGENT] Explicit multi-task create request detected")
                    created_tasks = []
                    for title in create_titles:
                        create_request = ToolCallRequest(
                            tool_name="create_task",
                            arguments={"title": title, "description": ""},
                        )
                        create_result = await mcp_server.call_tool(create_request)
                        if create_result.success:
                            created_tasks.append(create_result.result)
                    return {
                        "status": "success",
                        "message": f"Created {len(created_tasks)} tasks",
                        "created_tasks": created_tasks,
                        "tasks_found": 0,
                        "tasks": [],
                    }
                if not create_title:
                    create_title = create_titles[0]
                    create_description = ""

            if create_title and create_description and not list_request:
                self.logger.info("[TASK_AGENT] Explicit create task request detected")
                create_request = ToolCallRequest(
                    tool_name="create_task",
                    arguments={"title": create_title, "description": create_description},
                )
                create_result = await mcp_server.call_tool(create_request)
                if create_result.success:
                    return {
                        "status": "success",
                        "message": f"Created task '{create_title}'",
                        "created_task": create_result.result,
                        "tasks_found": 0,
                        "tasks": [],
                    }
                return {
                    "status": "partial_success",
                    "message": f"Task creation requested but failed: {create_result.error}",
                    "tasks_found": 0,
                    "tasks": [],
                }

            if create_title and create_description and list_request:
                self.logger.info("[TASK_AGENT] Explicit create+list task request detected; creating task before searching")
                create_request = ToolCallRequest(
                    tool_name="create_task",
                    arguments={"title": create_title, "description": create_description},
                )
                create_result = await mcp_server.call_tool(create_request)
                if create_result.success:
                    created_task = create_result.result

            # Treat prompts that include listing/searching keywords OR date/selection context
            # (e.g., 'this week', 'by 27th June') as combined search+action requests so
            # missing task IDs can be inferred from search results before performing actions.
            is_combined_request = (
                bool(re.search(r"\b(list|show|find|search|look|display|get|summarize|related|about|pending|open|incomplete|undone|unfinished|any|all|these|them|that|remaining|ones)\b", user_input, flags=re.IGNORECASE))
                or bool(re.search(r"\b(?:this week|next week|last week|this month|this quarter|by \d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))\b", user_input, flags=re.IGNORECASE))
                or bool(explicit_due_date)
            ) and bool(action_requests)
            # If the user requested an action but did not include an explicit task id,
            # treat it as a combined search/action request so we can infer the task.
            if any(task_id is None for _, task_id in action_requests):
                is_combined_request = True
            # Prefer explicit action-only only when the user did not also ask for a list/search
            # or due-date/semantic query context in the same prompt.
            explicit_action_only = (
                bool(action_requests)
                and not list_request
                and not explicit_due_date
                and not bool(re.search(r"\b(?:related to|about|regarding)\b", user_input, flags=re.IGNORECASE))
            )
            if explicit_action_only and all(task_id is not None for _, task_id in action_requests):
                is_combined_request = False
            if action_requests and not is_combined_request:
                self.logger.info(f"[TASK_AGENT] Explicit action-only request detected with {len(action_requests)} action(s)")
                action_results = []
                for action_name, task_id in action_requests:
                    if task_id is None:
                        continue
                    action_task = {**task, "task_id": task_id, "user_input": user_input}
                    if action_name == "complete_task":
                        action_result = await self._complete_task(action_task, mcp_server)
                    elif action_name == "reopen_task":
                        action_result = await self._reopen_task(action_task, mcp_server)
                    else:
                        action_result = await self._delete_task(action_task, mcp_server)
                    action_results.append({"action": action_name, "result": action_result})

                if len(action_results) == 1:
                    single_result = dict(action_results[0]["result"])
                    single_result.update({"actions": action_results})
                    return single_result

                return {
                    "status": "success",
                    "message": f"Executed {len(action_results)} action(s)",
                    "actions": action_results,
                }

            if re.search(r"\b(list|show|display|get|find)\b.*\b(task|tasks)\b", user_input, flags=re.IGNORECASE):
                if action_requests:
                    if explicit_due_date:
                        self.logger.info("[TASK_AGENT] Detected combined due-date list and action request; executing actions before listing")
                        action_results = []
                        for action_name, task_id in action_requests:
                            if task_id is None:
                                if action_name != "delete_task":
                                    continue

                                action_query = self._normalize_search_query_for_action(
                                    user_input,
                                    action_name=action_name,
                                )
                                search_request = ToolCallRequest(
                                    tool_name="search_tasks",
                                    arguments={"query": action_query, "limit": 20},
                                )
                                search_result = await mcp_server.call_tool(search_request)
                                matching_tasks = (
                                    search_result.result.get("results", [])
                                    if search_result.success and isinstance(search_result.result, dict)
                                    else []
                                )
                                action_result = await self._delete_task(
                                    {
                                        **task,
                                        "last_searched_tasks": matching_tasks,
                                        "user_input": user_input,
                                    },
                                    mcp_server,
                                )
                                action_results.append({"action": action_name, "result": action_result})
                                continue
                            action_task = {**task, "task_id": task_id, "user_input": user_input}
                            if action_name == "complete_task":
                                action_result = await self._complete_task(action_task, mcp_server)
                            elif action_name == "reopen_task":
                                action_result = await self._reopen_task(action_task, mcp_server)
                            else:
                                action_result = await self._delete_task(action_task, mcp_server)
                            action_results.append({"action": action_name, "result": action_result})

                        self.logger.info("[TASK_AGENT] Listing tasks after action for due-date query")
                        search_request = ToolCallRequest(
                            tool_name="search_tasks",
                            arguments={"query": user_input, "limit": 10},
                        )
                        search_result = await mcp_server.call_tool(search_request)
                        tasks = search_result.result.get("results", []) if search_result.success and isinstance(search_result.result, dict) else []
                        if priority_request:
                            tasks = self._sort_tasks_by_deadline(tasks)
                        list_result = {"count": len(tasks), "tasks": tasks}
                    else:
                        self.logger.info("[TASK_AGENT] Detected combined list and action request; listing first then executing actions")
                        list_result = await self._list_tasks(task, mcp_server)
                        tasks = list_result.get("tasks", []) if isinstance(list_result, dict) else []
                        if priority_request:
                            tasks = self._sort_tasks_by_deadline(tasks)
                            list_result = {"count": len(tasks), "tasks": tasks}

                        action_results = []
                        for action_name, task_id in action_requests:
                            if task_id is None:
                                if action_name != "delete_task":
                                    continue

                                action_query = self._normalize_search_query_for_action(
                                    user_input,
                                    action_name=action_name,
                                )
                                search_request = ToolCallRequest(
                                    tool_name="search_tasks",
                                    arguments={"query": action_query, "limit": 20},
                                )
                                search_result = await mcp_server.call_tool(search_request)
                                matching_tasks = (
                                    search_result.result.get("results", [])
                                    if search_result.success and isinstance(search_result.result, dict)
                                    else []
                                )
                                action_result = await self._delete_task(
                                    {
                                        **task,
                                        "last_searched_tasks": matching_tasks,
                                        "user_input": user_input,
                                    },
                                    mcp_server,
                                )
                                action_results.append({"action": action_name, "result": action_result})
                                continue
                            action_task = {**task, "task_id": task_id, "user_input": user_input}
                            if action_name == "complete_task":
                                action_result = await self._complete_task(action_task, mcp_server)
                            elif action_name == "reopen_task":
                                action_result = await self._reopen_task(action_task, mcp_server)
                            else:
                                action_result = await self._delete_task(action_task, mcp_server)
                            action_results.append({"action": action_name, "result": action_result})

                    payload = {
                        "status": "success",
                        "message": f"Found {list_result.get('count', 0)} matching task(s) and executed {len(action_results)} action(s)",
                        "tasks_found": list_result.get('count', 0),
                        "tasks": list_result.get('tasks', []),
                        "found_tasks": list_result.get('tasks', []),
                        "actions": action_results,
                    }
                    if len(action_results) == 1 and isinstance(action_results[0].get('result'), dict):
                        payload.update(action_results[0]['result'])
                    if created_task is not None:
                        payload["created_task"] = created_task
                    return payload

                if explicit_due_date:
                    self.logger.info("[TASK_AGENT] Detected explicit due-date constraint; using search_tasks for filtering")
                    search_request = ToolCallRequest(
                        tool_name="search_tasks",
                        arguments={"query": user_input, "limit": 10}
                    )
                    search_result = await mcp_server.call_tool(search_request)
                    if search_result.success and isinstance(search_result.result, dict):
                        tasks = search_result.result.get("results", [])
                    else:
                        self.logger.warning("[TASK_AGENT] search_tasks failed for explicit date constraint; falling back to list_tasks")
                        list_result = await self._list_tasks(task, mcp_server)
                        tasks = list_result.get("tasks", []) if isinstance(list_result, dict) else []
                    if priority_request:
                        tasks = self._sort_tasks_by_deadline(tasks)
                    payload = {
                        "status": "success",
                        "message": f"Found {len(tasks)} matching task(s)",
                        "tasks_found": len(tasks),
                        "tasks": tasks,
                        "found_tasks": tasks,
                    }
                    if created_task is not None:
                        payload["created_task"] = created_task
                    return payload
                if re.search(r"\b(related to|about|regarding)\b", user_input, flags=re.IGNORECASE):
                    self.logger.info("[TASK_AGENT] Detected related/search query; using search_tasks for semantic retrieval")
                    search_request = ToolCallRequest(
                        tool_name="search_tasks",
                        arguments={"query": user_input, "limit": 10}
                    )
                    search_result = await mcp_server.call_tool(search_request)
                    if search_result.success and isinstance(search_result.result, dict):
                        tasks = search_result.result.get("results", [])
                    else:
                        self.logger.warning("[TASK_AGENT] search_tasks failed for related query; falling back to list_tasks")
                        list_result = await self._list_tasks(task, mcp_server)
                        tasks = list_result.get("tasks", []) if isinstance(list_result, dict) else []
                    if priority_request:
                        tasks = self._sort_tasks_by_deadline(tasks)
                    payload = {
                        "status": "success",
                        "message": f"Found {len(tasks)} matching task(s)",
                        "tasks_found": len(tasks),
                        "tasks": tasks,
                        "found_tasks": tasks,
                    }
                    if created_task is not None:
                        payload["created_task"] = created_task
                    return payload
                if priority_request:
                    self.logger.info("[TASK_AGENT] Detected priority request; using sort_tasks_by_time")
                    sort_request = ToolCallRequest(
                        tool_name="sort_tasks_by_time",
                        arguments={"completed": False, "limit": 100, "offset": 0},
                    )
                    sort_result = await mcp_server.call_tool(sort_request)
                    if sort_result.success:
                        tasks = sort_result.result.get("tasks", []) if isinstance(sort_result.result, dict) else []
                        if explicit_due_date:
                            tasks = self._sort_tasks_by_deadline(tasks)
                        return {
                            "status": "success",
                            "message": "Prioritized tasks by date found in title or description",
                            "tasks_found": len(tasks),
                            "tasks": tasks,
                            "found_tasks": tasks,
                        }
                    return {"status": "error", "message": sort_result.error or "Failed to prioritize tasks"}
                return await self._list_tasks(task, mcp_server)

            # Step 1: Search for tasks matching the user query
            search_request = ToolCallRequest(
                tool_name="search_tasks",
                arguments={"query": user_input, "limit": 10}
            )
            self.logger.info(f"[TASK_AGENT] Calling MCP search_tasks with query: {user_input}")
            search_result = await mcp_server.call_tool(search_request)
            
            self.logger.info(f"[TASK_AGENT] Search result: success={search_result.success}, error={search_result.error}")
            if not search_result.success:
                self.logger.warning(f"[TASK_AGENT] Search failed, trying fallback with empty query")
                # Fallback: try empty query to get all tasks
                search_request = ToolCallRequest(
                    tool_name="search_tasks", 
                    arguments={"query": "", "limit": 10}
                )
                search_result = await mcp_server.call_tool(search_request)
                
                if not search_result.success:
                    return {"status": "error", "message": f"Search failed: {search_result.error}"}
            
            tasks = search_result.result.get("results", [])
            count = search_result.result.get("count", 0)
            
            self.logger.info(f"[TASK_AGENT] Found {count} tasks")
            
            # If first search returned nothing, try fallback
            if count == 0 and user_input:
                if action_requests:
                    self.logger.info("[TASK_AGENT] Action request found but initial search returned no results; skipping empty-query fallback to avoid unintended bulk actions")
                else:
                    self.logger.info(f"[TASK_AGENT] First search returned no results, trying fallback with empty query")
                    search_request = ToolCallRequest(
                        tool_name="search_tasks", 
                        arguments={"query": "", "limit": 10}
                    )
                    search_result = await mcp_server.call_tool(search_request)
                    if search_result.success:
                        tasks = search_result.result.get("results", [])
                        count = search_result.result.get("count", 0)
                        self.logger.info(f"[TASK_AGENT] Fallback found {count} tasks")

            if action_requests and count == 0:
                return {
                    "status": "error",
                    "message": "No tasks matched the action query. Please specify a task ID or adjust your request.",
                }
            if action_requests:
                self.logger.info(f"[TASK_AGENT] Combined request detected with {len(action_requests)} action(s) after search")

                if tasks and any(task_id is None for _, task_id in action_requests):
                    self.logger.info("[TASK_AGENT] Inferring missing task IDs from search results")
                    inferred_requests = []
                    normalized_query = self._normalize_search_query_for_action(user_input, action_name="delete_task")
                    self.logger.info(f"[TASK_AGENT] Normalized search query for action inference: {normalized_query}")

                    search_request = ToolCallRequest(
                        tool_name="search_tasks",
                        arguments={"query": normalized_query, "limit": 20},
                    )
                    semantic_search_result = await mcp_server.call_tool(search_request)
                    semantic_tasks = semantic_search_result.result.get("results", []) if semantic_search_result.success and isinstance(semantic_search_result.result, dict) else []
                    if semantic_tasks:
                        tasks = semantic_tasks
                        count = semantic_search_result.result.get("count", len(tasks))
                        self.logger.info(f"[TASK_AGENT] Refined task list from normalized query: {len(tasks)} items")

                    for action_name, task_id in action_requests:
                        if task_id is not None:
                            inferred_requests.append((action_name, task_id))
                            continue

                        inferred_id = None
                        if action_name == "complete_task":
                            inferred_id = next(
                                (t.get("id") or t.get("task_id")) for t in tasks if self._task_is_pending(t)
                            ) if tasks else None
                        elif action_name == "reopen_task":
                            inferred_id = next(
                                (t.get("id") or t.get("task_id")) for t in tasks if self._task_is_completed(t)
                            ) if tasks else None
                        else:
                            if self._is_explicit_bulk_action(user_input) or len(tasks) == 1:
                                inferred_id = next(
                                    (t.get("id") or t.get("task_id")) for t in tasks if (t.get("id") or t.get("task_id")) is not None
                                ) if tasks else None
                            else:
                                inferred_id = None

                        if inferred_id is not None:
                            self.logger.info(f"[TASK_AGENT] Inferred task_id={inferred_id} for action {action_name}")
                            inferred_requests.append((action_name, inferred_id))
                        else:
                            self.logger.warning(f"[TASK_AGENT] Could not infer task_id for action {action_name}")

                    if any(action_name == "delete_task" and task_id is None for action_name, task_id in action_requests):
                        return {
                            "status": "error",
                            "message": "Multiple tasks may match this delete request. Specify a task ID or explicitly say 'delete all matching tasks'.",
                        }

                    if any(task_id is None for _, task_id in inferred_requests):
                        return {
                            "status": "error",
                            "message": "I could not infer which task to act on. Please provide the task ID.",
                        }

                    action_requests = inferred_requests

                action_results = []
                for action_name, task_id in action_requests:
                    if task_id is None:
                        continue
                    action_task = {**task, "task_id": task_id, "user_input": user_input}
                    if action_name == "complete_task":
                        action_result = await self._complete_task(action_task, mcp_server)
                    elif action_name == "reopen_task":
                        action_result = await self._reopen_task(action_task, mcp_server)
                    else:
                        action_result = await self._delete_task(action_task, mcp_server)
                    action_results.append({"action": action_name, "result": action_result})

                if len(action_results) == 1:
                    single_result = dict(action_results[0]["result"])
                    single_result.update({
                        "tasks_found": count,
                        "tasks": tasks,
                        "found_tasks": tasks,
                        "actions": action_results,
                    })
                    return single_result

                return {
                    "status": "success",
                    "message": f"Found {count} matching task(s) and executed {len(action_results)} action(s)",
                    "tasks_found": count,
                    "tasks": tasks,
                    "found_tasks": tasks,
                    "actions": action_results,
                }

            if looks_like_explicit_create_task_request(user_input):
                title, description = extract_create_task_fields(user_input)
                if title and description:
                    create_request = ToolCallRequest(
                        tool_name="create_task",
                        arguments={"title": title, "description": description}
                    )
                    self.logger.info(f"[TASK_AGENT] Creating requested task: {title}")
                    create_result = await mcp_server.call_tool(create_request)
                    if create_result.success:
                        return {
                            "status": "success",
                            "message": f"Created task '{title}'",
                            "created_task": create_result.result,
                            "tasks_found": 0,
                            "tasks": []
                        }
                    return {
                        "status": "partial_success",
                        "message": f"Task creation requested but failed: {create_result.error}",
                        "tasks_found": 0,
                        "tasks": []
                    }
                return {
                    "status": "success",
                    "message": "Task creation requested, but title and description were not provided explicitly",
                    "tasks_found": 0,
                    "tasks": []
                }

            # Step 2: Return the matching tasks without creating an extra task for normal search/summarize prompts.
            if count > 0:
                self.logger.info(f"[TASK_AGENT] Returning {count} matching tasks without creating a new task")
                return {
                    "status": "success",
                    "message": f"Found {count} matching task(s)",
                    "tasks_found": count,
                    "tasks": tasks,
                    "found_tasks": tasks,
                }

            self.logger.info(f"[TASK_AGENT] No tasks found")
            return {
                "status": "success",
                "message": f"No tasks found matching '{user_input}'" if user_input else "No tasks in system",
                "tasks_found": 0,
                "tasks": [],
            }
                
        except Exception as e:
            self.logger.error(f"[TASK_AGENT] Error in _search_and_create_summary: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
    
    async def _search_and_complete(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Search for tasks matching user input, then complete matching ones."""
        if not mcp_server:
            return {"status": "error", "message": "MCP server not available"}
        
        try:
            user_input = task.get("user_input", "")
            self.logger.info(f"[TASK_AGENT] _search_and_complete called with: {user_input}")

            # Preserve the result of an explicit search clause when it is followed
            # by a separate completion clause. The completion query is handled
            # below, but it must not replace the tasks the user asked to search for.
            display_search_result = None
            split_action_match = re.search(
                r"^(?P<search>.+?)\s+(?:and|then)\s+"
                r"(?:complete|completed|done|finish|finished|mark done|mark as done|close)\b",
                user_input,
                flags=re.IGNORECASE,
            )
            if split_action_match:
                display_query = split_action_match.group("search").strip()
                display_search_result = await self._search_and_create_summary(
                    {**task, "operation": "search_and_create", "user_input": display_query},
                    mcp_server,
                )

            normalized_query = self._normalize_search_query_for_action(user_input, action_name="complete_task")
            action_refers_to_search_results = bool(re.search(
                r"\b(?:complete|completed|done|finish|finished|mark done|mark as done|close)\s+"
                r"(?:them|these|those|it)\b",
                user_input,
                flags=re.IGNORECASE,
            ))
            if action_refers_to_search_results and display_search_result is not None:
                # "Complete them" means the tasks identified by the preceding
                # search clause, including its due-date and status constraints.
                normalized_query = display_query
                search_result = display_search_result
            else:
                search_task = {**task, "operation": "search_and_create", "user_input": normalized_query}
                self.logger.info(f"[TASK_AGENT] _search_and_complete using normalized search query: {normalized_query}")
                search_result = await self._search_and_create_summary(search_task, mcp_server)
            
            if search_result.get("status") != "success" or not search_result.get("tasks"):
                return search_result

            matching_tasks = self._filter_action_results_by_all_terms(
                search_result.get("tasks", []),
                normalized_query,
            )
            if not matching_tasks:
                response_tasks = (
                    display_search_result.get("tasks", [])
                    if display_search_result and display_search_result.get("status") == "success"
                    else []
                )
                return {
                    "status": "success",
                    "message": "No tasks matched all requested completion criteria",
                    "tasks_found": len(response_tasks),
                    "tasks": response_tasks,
                    "completed_count": 0,
                    "completed_tasks": [],
                }
            
            # Now complete the matching pending tasks
            tasks_to_complete = []
            if re.search(r"\b(pending|not done|incomplete|open)\b", user_input, flags=re.IGNORECASE):
                tasks_to_complete = [t for t in matching_tasks if not t.get("completed")]
            else:
                tasks_to_complete = matching_tasks
            
            if not tasks_to_complete:
                return {
                    "status": "success",
                    "message": "No matching tasks to complete",
                    "tasks_found": len(matching_tasks),
                    "tasks": matching_tasks,
                    "completed_count": 0,
                }
            
            # Bulk complete
            from ..mcp_server import ToolCallRequest
            completed_count = 0
            for t in tasks_to_complete:
                task_id = t.get("id") or t.get("task_id")
                if task_id is None:
                    continue
                
                try:
                    request = ToolCallRequest(tool_name="complete_task", arguments={"task_id": int(task_id)})
                    result = await mcp_server.call_tool(request)
                    if result.success:
                        completed_count += 1
                except Exception as e:
                    self.logger.debug(f"Error completing task {task_id}: {e}")
            
            response_tasks = (
                display_search_result.get("tasks", [])
                if display_search_result and display_search_result.get("status") == "success"
                else matching_tasks
            )
            return {
                "status": "success",
                "message": f"Found {len(response_tasks)} searched task(s), completed {completed_count} matching task(s)",
                "tasks_found": len(response_tasks),
                "tasks": response_tasks,
                "completed_count": completed_count,
                "completed_tasks": matching_tasks,
            }
        except Exception as e:
            self.logger.error(f"[TASK_AGENT] Error in _search_and_complete: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
    
    async def _search_and_reopen(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Search for tasks matching user input, then reopen matching ones."""
        if not mcp_server:
            return {"status": "error", "message": "MCP server not available"}
        
        try:
            user_input = task.get("user_input", "")
            self.logger.info(f"[TASK_AGENT] _search_and_reopen called with: {user_input}")
            
            normalized_query = self._normalize_search_query_for_action(user_input, action_name="reopen_task")
            search_task = {**task, "operation": "search_and_create", "user_input": normalized_query}
            self.logger.info(f"[TASK_AGENT] _search_and_reopen using normalized search query: {normalized_query}")
            search_result = await self._search_and_create_summary(search_task, mcp_server)
            
            if search_result.get("status") != "success" or not search_result.get("tasks"):
                return search_result
            
            # Now reopen the matching completed tasks
            tasks_to_reopen = [t for t in search_result.get("tasks", []) if t.get("completed")]
            
            if not tasks_to_reopen:
                return {
                    "status": "success",
                    "message": "No completed tasks to reopen",
                    "tasks_found": len(search_result.get("tasks", [])),
                    "tasks": search_result.get("tasks", []),
                    "reopened_count": 0,
                }
            
            # Bulk reopen
            from ..mcp_server import ToolCallRequest
            reopened_count = 0
            for t in tasks_to_reopen:
                task_id = t.get("id") or t.get("task_id")
                if task_id is None:
                    continue
                
                try:
                    request = ToolCallRequest(tool_name="reopen_task", arguments={"task_id": int(task_id)})
                    result = await mcp_server.call_tool(request)
                    if result.success:
                        reopened_count += 1
                except Exception as e:
                    self.logger.debug(f"Error reopening task {task_id}: {e}")
            
            return {
                "status": "success",
                "message": f"Found {len(search_result.get('tasks', []))} task(s), reopened {reopened_count}",
                "tasks_found": len(search_result.get("tasks", [])),
                "tasks": search_result.get("tasks", []),
                "reopened_count": reopened_count,
            }
        except Exception as e:
            self.logger.error(f"[TASK_AGENT] Error in _search_and_reopen: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
    
    async def _search_and_delete(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Search for tasks matching user input, then delete matching ones."""
        if not mcp_server:
            return {"status": "error", "message": "MCP server not available"}
        
        try:
            user_input = task.get("user_input", "")
            self.logger.info(f"[TASK_AGENT] _search_and_delete called with: {user_input}")
            
            # Keep an initial list/search clause separate from the delete target.
            # Example: list Q3 tasks, then delete tasks related to Performance.
            display_search_result = None
            split_action_match = re.search(
                r"^(?P<search>.+?)\s+and\s+(?:confirm\s+and\s+)?"
                r"(?:delete|remove|erase|trash|discard)\b",
                user_input,
                flags=re.IGNORECASE,
            )

            from ..mcp_server import ToolCallRequest
            if split_action_match:
                display_query = split_action_match.group("search").strip()
                display_request = ToolCallRequest(tool_name="search_tasks", arguments={"query": display_query, "limit": 10})
                display_result = await mcp_server.call_tool(display_request)
                if display_result.success and isinstance(display_result.result, dict):
                    display_search_result = self._filter_action_results_by_all_terms(
                        display_result.result.get("results", []), display_query,
                    )

            action_query = self._normalize_search_query_for_action(user_input, action_name="delete_task")
            search_request = ToolCallRequest(tool_name="search_tasks", arguments={"query": action_query, "limit": 10})
            search_result = await mcp_server.call_tool(search_request)

            if not search_result.success:
                return {"status": "error", "message": search_result.error or "Search failed"}

            search_data = {}
            if hasattr(search_result, "result"):
                search_data = search_result.result or {}
            elif isinstance(search_result, dict):
                search_data = search_result

            tasks = []
            if isinstance(search_data, dict):
                tasks = search_data.get("results") or search_data.get("tasks") or []
            elif isinstance(search_data, list):
                tasks = search_data

            tasks = self._filter_action_results_by_all_terms(tasks, action_query)

            if not tasks:
                return {
                    "status": "success",
                    "message": "No tasks matched the delete criteria.",
                    "tasks_found": len(display_search_result or []),
                    "tasks": display_search_result or [],
                    "deleted_count": 0,
                }

            # Determine which tasks to delete based on user intent
            tasks_to_delete = tasks
            
            if re.search(r"\b(completed|done|finished)\b", user_input, flags=re.IGNORECASE):
                tasks_to_delete = [t for t in tasks_to_delete if t.get("completed")]
            elif re.search(r"\b(pending|incomplete|open)\b", user_input, flags=re.IGNORECASE):
                tasks_to_delete = [t for t in tasks_to_delete if not t.get("completed")]
            
            if not tasks_to_delete:
                return {
                    "status": "success",
                    "message": "No matching tasks to delete",
                    "tasks_found": len(tasks),
                    "tasks": tasks,
                    "deleted_count": 0,
                }

            if len(tasks_to_delete) > 1 and not self._is_explicit_bulk_action(user_input):
                return {
                    "status": "error",
                    "message": "Multiple matching tasks were found. Specify a task id or say 'delete all matching tasks' to remove them all.",
                }
            
            # Bulk delete
            from ..mcp_server import ToolCallRequest
            deleted_count = 0
            for t in tasks_to_delete:
                task_id = t.get("id") or t.get("task_id")
                if task_id is None:
                    continue
                
                try:
                    request = ToolCallRequest(tool_name="delete_task", arguments={"task_id": int(task_id)})
                    result = await mcp_server.call_tool(request)
                    if result.success:
                        deleted_count += 1
                except Exception as e:
                    self.logger.debug(f"Error deleting task {task_id}: {e}")
            
            return {
                "status": "success",
                "message": f"Found {len(tasks)} task(s), deleted {deleted_count}",
                "tasks_found": len(display_search_result) if display_search_result is not None else len(tasks),
                "tasks": display_search_result if display_search_result is not None else tasks,
                "deleted_count": deleted_count,
                "deleted_tasks": tasks,
            }
        except Exception as e:
            self.logger.error(f"[TASK_AGENT] Error in _search_and_delete: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}


class ChatAgent(Agent):
    """Agent responsible for conversational AI and chat management."""
    
    def __init__(self):
        super().__init__(
            agent_id="chat_agent_001",
            role=AgentRole.CHAT_AGENT,
            name="Chat Agent",
            description="Handles conversational AI and chat operations"
        )
    
    async def process_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """Handle incoming chat messages."""
        self.logger.info(f"Processing chat message: {message.message_type}")
        
        if message.message_type == "chat_message":
            return await self._handle_chat(message)
        
        return None
    
    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute chat operations."""
        self.set_status(AgentStatus.PROCESSING)
        
        try:
            operation = task.get("operation")
            
            if operation == "send_message":
                return await self._send_message(task)
            return {"status": "error", "message": f"Unknown operation: {operation}"}
        finally:
            self.set_status(AgentStatus.IDLE)

    async def _handle_chat(self, message: AgentMessage) -> AgentMessage:
        """Handle incoming chat message."""
        content = message.content.get("text") or message.content.get("message", "")
        context = message.content.get("context")
        tool_results = message.content.get("tool_results")
        self.logger.info(
            "ChatAgent handling message: len=%s | has_context=%s | has_tool_results=%s",
            len(content),
            bool(context),
            bool(tool_results),
        )
        self.logger.info("ChatAgent forwarding to chat_with_tools for user message: %s", content[:120])

        # Ensure assistant returns natural-language output for chat agent
        # (avoid JSON proposal output when chatting with users)
        response_text = await chat_with_tools(
            user_message=content,
            context=context,
            tool_results=tool_results,
            force_natural=True,
        )
        self.logger.info(
            "ChatAgent received response length=%s from chat_with_tools",
            len(response_text),
        )
        
        response = AgentMessage(
            sender_id=self.agent_id,
            recipient_id=message.sender_id,
            message_type="chat_response",
            content={"response": response_text}
        )
        return response
    
    async def _send_message(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Send a chat message through the chat agent pipeline."""
        message = task.get("message", "")
        context = task.get("context")
        tool_results = task.get("tool_results")

        # Ask for natural-language reply for outgoing messages
        response = await chat_with_tools(
            user_message=message,
            context=context,
            tool_results=tool_results,
            force_natural=True,
        )
        return {"status": "success", "response": response}


class RAGAgent(Agent):
    """Agent responsible for Retrieval-Augmented Generation operations."""
    
    def __init__(self):
        super().__init__(
            agent_id="rag_agent_001",
            role=AgentRole.RAG_AGENT,
            name="RAG Agent",
            description="Handles Retrieval-Augmented Generation and semantic search"
        )
    
    async def process_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """Handle incoming RAG-related messages."""
        self.logger.info(f"Processing RAG message: {message.message_type}")
        
        if message.message_type == "search_query":
            return await self._handle_search(message)
        
        return None
    
    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute RAG operations."""
        self.set_status(AgentStatus.PROCESSING)
        
        try:
            operation = task.get("operation")
            mcp_server = task.get("mcp_server")
            
            if operation == "search":
                return await self._search(task, mcp_server)
            
            return {"status": "error", "message": f"Unknown operation: {operation}"}
        finally:
            self.set_status(AgentStatus.IDLE)
    
    async def _search(self, task: Dict[str, Any], mcp_server: Optional[Any] = None) -> Dict[str, Any]:
        """Execute semantic search using vector_search tool."""
        if not mcp_server:
            return {"status": "error", "message": "MCP server not available", "results": []}
        
        try:
            from ..mcp_server import ToolCallRequest
            
            query = task.get("query", "")
            limit = task.get("limit", 5)
            threshold = task.get("threshold", 0.7)
            
            request = ToolCallRequest(
                tool_name="vector_search",
                arguments={"query": query, "limit": limit, "threshold": threshold}
            )
            result = await mcp_server.call_tool(request)
            
            if result.success:
                return {
                    "status": "success",
                    "results": result.result.get("results", []),
                    "count": result.result.get("count", 0)
                }
            else:
                return {"status": "error", "message": result.error, "results": []}
        except Exception as e:
            self.logger.error(f"Error in _search: {e}")
            return {"status": "error", "message": str(e), "results": []}


class CoordinatorAgent(Agent):
    """Agent responsible for orchestrating the full multi-agent workflow."""

    def __init__(self):
        super().__init__(
            agent_id="coordinator_001",
            role=AgentRole.COORDINATOR,
            name="Coordinator",
            description="Coordinates task, chat, RAG, and analysis agents"
        )

    async def process_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """Handle incoming coordinator requests."""
        self.logger.info(f"Processing coordinator message: {message.message_type}")

        if message.message_type in {"chat_message", "orchestrate_message"}:
            return await self._handle_orchestration(message)

        return None

    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the orchestrated workflow for a user request."""
        self.set_status(AgentStatus.PROCESSING)

        try:
            operation = task.get("operation")
            if operation == "orchestrate_message":
                return await self._orchestrate_message(task)
            if operation == "send_message":
                return await self._orchestrate_message(task)
            return {"status": "error", "message": f"Unknown operation: {operation}"}
        finally:
            self.set_status(AgentStatus.IDLE)

    async def _handle_orchestration(self, message: AgentMessage) -> AgentMessage:
        """Handle a coordinator request and send a response message."""
        content = message.content.get("text") or message.content.get("message", "")
        context = message.content.get("context")
        tool_results = message.content.get("tool_results")

        result = await self._orchestrate_message(
            {
                "message": content,
                "context": context,
                "tool_results": tool_results,
            }
        )

        return AgentMessage(
            sender_id=self.agent_id,
            recipient_id=message.sender_id,
            message_type="chat_response",
            content={
                "response": result.get("response", ""),
                "workflow": result.get("workflow", []),
            },
        )

    async def _orchestrate_message(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Run the full multi-agent pipeline for one message with explicit stage handoff."""
        message = task.get("message", "")
        context = task.get("context")
        tool_results = task.get("tool_results")
        lowered = message.lower()

        workflow = []
        stage_context = context or ""
        stage_tool_results = tool_results or ""

        # Step 1: route to task operations when the request is task-specific.
        task_keywords = [
            "create task",
            "add task",
            "update task",
            "mark task",
            "complete task",
            "delete task",
            "reopen task",
            "list tasks",
            "show tasks",
            "task #",
            "task id",
        ]
        if any(keyword in lowered for keyword in task_keywords):
            task_agent = TaskAgent()
            task_payload = {"operation": "list_tasks"}
            _log_agent_event(
                task_agent.agent_id,
                "orchestration-request",
                {"agent_name": task_agent.name, "message": message, "payload": task_payload},
            )
            if any(k in lowered for k in ["create", "add", "new"]):
                task_payload = {"operation": "create_task", "message": message}
            elif any(k in lowered for k in ["complete", "mark", "done", "finish"]):
                task_payload = {"operation": "get_task", "message": message}
            elif any(k in lowered for k in ["update", "change", "rename"]):
                task_payload = {"operation": "get_task", "message": message}

            _log_agent_event(
                task_agent.agent_id,
                "calling-agent",
                {"agent_name": task_agent.name, "payload": task_payload},
            )
            task_result = await task_agent.execute(task_payload)
            _log_agent_result(task_agent.agent_id, task_result)
            workflow.append(
                {
                    "agent": task_agent.agent_id,
                    "action": task_payload.get("operation"),
                    "result": task_result,
                }
            )
            if task_result.get("status") == "success":
                stage_tool_results = (
                    stage_tool_results + "\n\n" if stage_tool_results else ""
                ) + f"Task agent result: {task_result}"

        # Step 2: route to RAG when the request asks for search/find/context.
        rag_keywords = [
            "search",
            "find",
            "related to",
            "about",
            "look for",
            "documents",
            "context",
            "retrieve",
        ]
        if any(keyword in lowered for keyword in rag_keywords):
            rag_agent = RAGAgent()
            rag_payload = {"operation": "search", "query": message}
            _log_agent_event(
                rag_agent.agent_id,
                "orchestration-request",
                {"agent_name": rag_agent.name, "message": message, "payload": rag_payload},
            )
            _log_agent_event(
                rag_agent.agent_id,
                "calling-agent",
                {"agent_name": rag_agent.name, "payload": rag_payload},
            )
            rag_result = await rag_agent.execute(rag_payload)
            _log_agent_result(rag_agent.agent_id, rag_result)
            workflow.append(
                {
                    "agent": rag_agent.agent_id,
                    "action": rag_payload.get("operation"),
                    "result": rag_result,
                }
            )
            if rag_result.get("status") == "success":
                stage_context = (
                    stage_context + "\n\n" if stage_context else ""
                ) + f"RAG results: {rag_result}"

        # Step 3: route to analysis for summaries, stats, trends, or urgency questions.
        analysis_keywords = [
            "analyze",
            "summary",
            "stats",
            "trend",
            "urgent",
            "report",
            "how many",
            "what is the most",
        ]
        if any(keyword in lowered for keyword in analysis_keywords):
            analysis_agent = AnalysisAgent()
            analysis_payload = {
                "operation": "analyze_data",
                "message": message,
                "context": stage_context,
                "tool_results": stage_tool_results,
            }
            _log_agent_event(
                analysis_agent.agent_id,
                "orchestration-request",
                {"agent_name": analysis_agent.name, "message": message, "payload": analysis_payload},
            )
            _log_agent_event(
                analysis_agent.agent_id,
                "calling-agent",
                {"agent_name": analysis_agent.name, "payload": analysis_payload},
            )
            analysis_result = await analysis_agent.execute(analysis_payload)
            _log_agent_result(analysis_agent.agent_id, analysis_result)
            workflow.append(
                {
                    "agent": analysis_agent.agent_id,
                    "action": analysis_payload.get("operation"),
                    "result": analysis_result,
                }
            )
            if analysis_result.get("status") == "success":
                stage_tool_results = (
                    stage_tool_results + "\n\n" if stage_tool_results else ""
                ) + f"Analysis result: {analysis_result}"

        # Step 4: always ask the chat agent to produce the final response.
        chat_agent = ChatAgent()
        final_prompt = (
            f"User request: {message}\n"
            f"Context: {stage_context or context or 'No extra context provided'}\n"
            f"Tool results: {stage_tool_results or tool_results or 'No tool results'}\n"
            f"Workflow steps: {workflow}"
        )
        final_payload = {
            "message": final_prompt,
            "context": stage_context or context,
            "tool_results": stage_tool_results or tool_results,
        }
        _log_agent_event(
            chat_agent.agent_id,
            "orchestration-request",
            {"agent_name": chat_agent.name, "message": message, "payload": final_payload},
        )
        _log_agent_event(
            chat_agent.agent_id,
            "calling-agent",
            {"agent_name": chat_agent.name, "payload": final_payload},
        )
        final_response_data = await chat_agent._send_message(final_payload)
        final_response_text = (
            final_response_data.get("response")
            if isinstance(final_response_data, dict)
            else final_response_data
        )
        _log_agent_result(chat_agent.agent_id, final_response_data)

        return {
            "status": "success",
            "response": final_response_text,
            "workflow": workflow,
        }


class AnalysisAgent(Agent):
    """Agent responsible for data analysis and insights generation."""
    
    def __init__(self):
        super().__init__(
            agent_id="analyzer_001",
            role=AgentRole.ANALYZER,
            name="Analysis Agent",
            description="Performs data analysis and generates insights"
        )
    
    async def process_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        return None
    
    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        self.set_status(AgentStatus.PROCESSING)
        try:
            operation = task.get("operation")
            if operation == "analyze_data":
                return await self._analyze_data(task)
            return {"status": "error", "message": f"Unknown operation: {operation}"}
        finally:
            self.set_status(AgentStatus.IDLE)
    
    async def _analyze_data(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "insights": []}


# Agent specifications for easy instantiation
TaskAgentSpec = TaskAgent
ChatAgentSpec = ChatAgent
RAGAgentSpec = RAGAgent
AnalysisAgentSpec = AnalysisAgent
CoordinatorAgentSpec = CoordinatorAgent
