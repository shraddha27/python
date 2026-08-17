"""
LangGraph-based multi-agent workflow orchestration system.
Integrates with the existing agent framework to provide coordinated task execution.
Uses sophisticated intent detection and multi-step orchestration like CoordinatorAgent.
"""

import logging
import os
import re
import time
from typing import Any, Dict, Optional, Annotated
from datetime import datetime

from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field

from .agent_base import Agent, AgentMessage, AgentRole, AgentStatus
from .agent_manager import AgentManager
from .agents import TaskAgent, ChatAgent, RAGAgent, AnalysisAgent
from ..rag_tools import (
    _detect_explicit_date_constraint,
    extract_create_task_fields,
    extract_update_task_fields,
    looks_like_task_status_update_request,
)
from ..llm_proposal import Proposal
from ..mistral_client import generate_response, chat_with_tools
from ..langsmith_tracing import trace_workflow_execution, trace_agent_execution, trace_tool_call
import json
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class WorkflowState(BaseModel):
    """State object for LangGraph workflow execution."""
    
    task_id: str = Field(default_factory=lambda: f"workflow_{datetime.utcnow().timestamp()}")
    user_input: str
    agent_messages: list[Dict[str, Any]] = Field(default_factory=list)
    task_context: Dict[str, Any] = Field(default_factory=dict)
    workflow_log: list[Dict[str, Any]] = Field(default_factory=list)  # Track all agent calls
    stage_context: str = ""  # Context passed between stages
    stage_tool_results: str = ""  # Tool results accumulated
    current_agent: Optional[str] = None
    workflow_status: str = "started"
    error_message: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    routing_decision: Optional[Dict[str, Any]] = None
    dialog_history: list[Dict[str, Any]] = Field(default_factory=list)
    last_user_input: Optional[str] = None
    last_assistant_response: Optional[str] = None
    pending_task_creation: Optional[Dict[str, Any]] = None
    pending_action: Optional[Dict[str, Any]] = None
    last_created_task: Optional[Dict[str, Any]] = None
    last_proposal: Optional[Dict[str, Any]] = None
    last_searched_tasks: list[Dict[str, Any]] = Field(default_factory=list)  # Most recent search results
    last_selected_task: Optional[Dict[str, Any]] = None  # Task user is referring to (from search)
    
    class Config:
        arbitrary_types_allowed = True


class LangGraphWorkflow:
    """
    LangGraph-based workflow orchestration for multi-agent system.
    Manages agent coordination, message passing, and workflow state.
    Uses sophisticated multi-step orchestration like CoordinatorAgent.
    """
    
    def __init__(self, agent_manager: AgentManager, mcp_server: Optional[Any] = None):
        self.agent_manager = agent_manager
        self.mcp_server = mcp_server
        self.graph = self._build_workflow_graph()
        logger.info("Initialized LangGraph workflow system with multi-step orchestration")
    
    def _build_workflow_graph(self) -> StateGraph:
        """Build the LangGraph state machine for sophisticated agent orchestration."""
        
        workflow = StateGraph(WorkflowState)
        
        # Define nodes for multi-step orchestration
        workflow.add_node("router", self._router_node)
        workflow.add_node("task_stage", self._task_stage_node)
        workflow.add_node("rag_stage", self._rag_stage_node)
        workflow.add_node("analysis_stage", self._analysis_stage_node)
        workflow.add_node("chat_final", self._chat_final_node)
        workflow.add_node("finalize", self._finalize_node)
        
        # Set entry point
        workflow.set_entry_point("router")
        
        # Router analyzes intent and decides which stages to execute
        workflow.add_conditional_edges(
            "router",
            self._route_stages,
            {
                "task_rag_analysis": "task_stage",
                "task_rag": "task_stage",
                "task_analysis": "task_stage",
                "task_only": "task_stage",
                "rag_analysis": "rag_stage",
                "rag_only": "rag_stage",
                "analysis_only": "analysis_stage",
                "chat_only": "chat_final",
                END: END,
            }
        )
        
        # Multi-step workflow chaining
        workflow.add_conditional_edges(
            "task_stage",
            self._task_stage_transition,
            {
                "rag_analysis": "rag_stage",
                "rag": "rag_stage",
                "analysis": "analysis_stage",
                "chat_final": "chat_final",
                "finalize": "finalize",
            }
        )
        
        workflow.add_conditional_edges(
            "rag_stage",
            self._rag_stage_transition,
            {
                "analysis": "analysis_stage",
                "chat_final": "chat_final",
                "finalize": "finalize",
            }
        )
        
        workflow.add_edge("analysis_stage", "chat_final")
        workflow.add_edge("chat_final", "finalize")
        workflow.add_edge("finalize", END)
        
        return workflow.compile()
    
    async def _router_node(self, state: WorkflowState) -> WorkflowState:
        """Analyze user input to determine which workflow stages to execute."""
        state.task_id = getattr(state, "task_id", f"workflow_{datetime.utcnow().timestamp()}")
        state.user_input = getattr(state, "user_input", "") or ""
        state.agent_messages = getattr(state, "agent_messages", []) or []
        state.task_context = getattr(state, "task_context", {}) or {}
        state.workflow_log = getattr(state, "workflow_log", []) or []
        state.stage_context = getattr(state, "stage_context", "") or ""
        state.stage_tool_results = getattr(state, "stage_tool_results", "") or ""
        state.current_agent = getattr(state, "current_agent", None)
        state.workflow_status = getattr(state, "workflow_status", "started")
        state.error_message = getattr(state, "error_message", None)
        state.result = getattr(state, "result", None)
        state.routing_decision = getattr(state, "routing_decision", None)
        state.dialog_history = getattr(state, "dialog_history", []) or []
        state.last_user_input = getattr(state, "last_user_input", None)
        state.last_assistant_response = getattr(state, "last_assistant_response", None)
        state.pending_task_creation = getattr(state, "pending_task_creation", None)
        state.pending_action = getattr(state, "pending_action", None)

        # Restore workflow memory from upstream context if provided.
        memory = None
        if isinstance(state.task_context, dict):
            memory = state.task_context.get("workflow_memory")
        if isinstance(memory, dict):
            state.dialog_history = memory.get("dialog_history", state.dialog_history) or state.dialog_history
            state.last_user_input = memory.get("last_user_input", state.last_user_input)
            state.last_assistant_response = memory.get("last_assistant_response", state.last_assistant_response)
            state.pending_task_creation = memory.get("pending_task_creation", state.pending_task_creation)
            state.pending_action = memory.get("pending_action", state.pending_action)
            state.last_created_task = memory.get("last_created_task", state.last_created_task)
            state.last_proposal = memory.get("last_proposal", state.last_proposal)
            state.last_searched_tasks = memory.get("last_searched_tasks", state.last_searched_tasks) or []
            state.last_selected_task = memory.get("last_selected_task", state.last_selected_task)

        if state.user_input:
            # Preserve prior user input for follow-ups; do not overwrite on simple confirmation replies.
            if not self._is_follow_up_confirmation(state.user_input) or not self._has_pending_task_creation_suggestion(state):
                state.last_user_input = state.user_input
            if not state.dialog_history or state.dialog_history[-1].get("message") != state.user_input:
                state.dialog_history.append({
                    "role": "user",
                    "message": state.user_input,
                    "timestamp": datetime.utcnow().isoformat(),
                })

        logger.info(f"Router analyzing task: {state.task_id} with input: {state.user_input}")
        
        user_input_lower = state.user_input.lower()
        
        # Define keyword groups - split phrases into individual words for better matching
        explicit_create_request = self._is_explicit_create_task_request(state.user_input)
        task_keywords = [
            "mark", "complete", "delete", "reopen",
            "list", "show", "task", "tasks", "task#", "taskid"
        ]
        rag_keywords = [
            "search", "find", "related", "about", "look", "documents", "document", "docs", "doc",
            "context", "retrieve", "documentation", "architecture", "design", "reference", "info",
            "inspect", "review", "understand", "explain", "details", "source"
        ]
        analysis_keywords = [
            "analyze", "analysis", "summary", "stats", "trend", "urgent", "report", "count",
            "summarize", "insight", "insights", "compare", "assess", "explain", "priority",
            "prioritize", "importance", "important", "estimate", "projection", "forecast"
        ]

        # Check for keyword matches (more flexible - count matching words)
        task_count = sum(1 for keyword in task_keywords if keyword in user_input_lower)
        rag_count = sum(1 for keyword in rag_keywords if keyword in user_input_lower)
        analysis_count = sum(1 for keyword in analysis_keywords if keyword in user_input_lower)

        logger.info(f"Router keyword detection - task: {task_count}, rag: {rag_count}, analysis: {analysis_count}")

        has_task = explicit_create_request or task_count >= 1
        
        # RAG detection: only trigger if it's NOT just task searching with descriptive words
        # e.g., "find tasks about design" is task searching, NOT RAG
        # but "search documentation about architecture" IS RAG
        is_task_focused_search = has_task and any(word in user_input_lower for word in ["search tasks", "find tasks", "list tasks", "show tasks", "tasks about", "tasks related"])
        has_rag = False
        if not is_task_focused_search:
            # Only trigger RAG for true document/context retrieval (not task searching)
            has_rag = rag_count >= 1 or any(word in user_input_lower for word in [
                "doc", "docs", "document", "documents", "documentation", "reference", "context",
                "retrieve", "inspect", "review", "source", "codebase", "repository", "code"
            ])
        
        has_analysis = analysis_count >= 1 or any(word in user_input_lower for word in [
            "summary", "summarize", "report", "stats", "trend", "count", "compare", "assess",
            "insight", "insights", "analyze", "analysis", "explain", "priority", "prioritize",
            "importance", "important"
        ])
        # Due-date constraints are still task-focused, not document retrieval. Keep them
        # in the task domain so route selection stays on the task_stage unless the prompt
        # explicitly requests unrelated retrieval or context.
        explicit_due_constraint = bool(_detect_explicit_date_constraint(state.user_input))
        relative_due_constraint = bool(re.search(
            r"\b(?:due\s+(?:by|on|today|tomorrow|this week|next week|today|tomorrow)|by\s+(?:today|tomorrow)|until\s+(?:today|tomorrow)|before\s+(?:today|tomorrow))\b",
            user_input_lower,
        ))
        if explicit_due_constraint or relative_due_constraint:
            # Keep task-focused due-date requests as task-related rather than RAG-related.
            has_rag = has_rag and not any(word in user_input_lower for word in ["related to", "about", "regarding"])
        wants_all_agents = any(word in user_input_lower for word in ["all agents", "all agent", "all four", "every agent", "all of them"])
        # Any compound request that mixes task, retrieval/context, and analysis/explanation
        # intent should automatically trigger the full multi-agent flow.
        # Examples: "find tasks about architecture and analyze the results",
        # "list open tasks related to design and explain them",
        # "search documentation about the API and summarize what matters".
        wants_full_flow = (
            wants_all_agents
            or (has_task and has_rag and has_analysis)
            or (has_task and has_rag and any(word in user_input_lower for word in ["analyze", "analysis", "explain", "summary", "summarize", "report", "insight", "insights", "compare", "assess"]))
            or (has_task and has_analysis and has_rag and any(word in user_input_lower for word in ["find", "search", "document", "docs", "documentation", "architecture", "design", "context", "source", "inspect", "review", "details", "info"]))
            or (has_rag and has_analysis and any(word in user_input_lower for word in ["task", "tasks", "find", "search", "show", "list", "create", "complete", "delete", "reopen"]))
            or (has_task and has_rag and any(word in user_input_lower for word in ["why", "how", "what", "which", "tell me", "describe", "explain", "priority", "importance"]))
            or (has_task and has_analysis and any(word in user_input_lower for word in ["explain", "priority", "importance", "important"])) and not any(word in user_input_lower for word in ["due", "today", "tomorrow", "open", "pending"]))
        
        signal_count = int(has_task) + int(has_rag) + int(has_analysis)
        compound_prompt = any(phrase in user_input_lower for phrase in [" and then ", " if ", " then ", " also ", " plus ", " and "])
        ambiguous_prompt = not wants_full_flow and (signal_count <= 1 or compound_prompt)

        if self._is_follow_up_confirmation(state.user_input) and (self._has_pending_task_creation_suggestion(state) or bool(state.pending_action)):
            state.current_agent = "task_only"
            state.routing_decision = {
                "mode": "follow_up_confirmation",
                "route": state.current_agent,
                "stage": state.current_agent,
                "confidence": "high",
            }
            if state.pending_action:
                logger.info("Detected follow-up confirmation for pending task action")
            else:
                logger.info("Detected follow-up confirmation for pending task creation suggestion")
        else:
            logger.info(f"Router detected: has_task={has_task}, has_rag={has_rag}, has_analysis={has_analysis}, wants_full_flow={wants_full_flow}, compound_prompt={compound_prompt}, ambiguous_prompt={ambiguous_prompt}")

            # Determine execution path
            if wants_full_flow:
                state.current_agent = "task_rag_analysis"
            elif has_task and has_rag:
                state.current_agent = "task_rag"
            elif has_task and has_analysis:
                state.current_agent = "task_analysis"
            elif has_task:
                state.current_agent = "task_only"
            elif has_rag and has_analysis:
                state.current_agent = "rag_analysis"
            elif has_rag:
                state.current_agent = "rag_only"
            elif has_analysis:
                state.current_agent = "analysis_only"
            else:
                state.current_agent = "chat_only"

            if ambiguous_prompt:
                llm_route = self._classify_route_with_llm(state.user_input, has_task, has_rag, has_analysis, compound_prompt)
                if llm_route:
                    state.current_agent = self._map_route_label_to_stage(llm_route)
                    state.routing_decision = {
                        "mode": "llm_classifier",
                        "route": llm_route,
                        "stage": state.current_agent,
                        "confidence": "high",
                    }
                    logger.info(f"LLM routing classifier selected: {llm_route} -> {state.current_agent}")
                else:
                    state.routing_decision = {
                        "mode": "rule_based",
                        "route": state.current_agent,
                        "stage": state.current_agent,
                        "confidence": "fallback",
                    }
                    logger.info("LLM routing classifier unavailable or uncertain; using rule-based route")
            else:
                state.routing_decision = {
                    "mode": "rule_based",
                    "route": state.current_agent,
                    "stage": state.current_agent,
                    "confidence": "high",
                }
        
        state.workflow_status = "routing_complete"
        logger.info(f"Router determined workflow path: {state.current_agent}")
        
        return state
    
    def _is_explicit_create_task_request(self, user_input: str) -> bool:
        """Return True for explicit task-creation requests in various formats."""
        if not user_input:
            return False

        normalized = re.sub(r"\s+", " ", user_input.strip())
        lower_text = normalized.lower()
        
        # Patterns for explicit task creation (anywhere in input)
        explicit_patterns = [
            # Detailed format: "create a task with title: X and description: Y"
            r"\b(?:create|add|make)\b(?:\s+a|\s+new)?\s*task\b.+\b(?:title|with title)\b\s*(?:as|is|=|:)?\s*.+?\b(?:and\s+)?description\b\s*(?:as|is|=|:)?\s*.+",
            # "title: X description: Y" or "title: X and description: Y"
            r"\btitle\b\s*(?:as|is|=|:)?\s*.+?\b(?:and\s+)?description\b\s*(?:as|is|=|:)?\s*.+",
            # "create task title X description Y"
            r"\b(?:create|add|make)\b(?:\s+a|\s+new)?\s*task\b.+\btitle\b.+\bdescription\b",
            # Simple format: "create a task for X" or "create a task about X"
            r"\b(?:create|add|make)\b(?:\s+a|\s+new)?\s*task\b\s+(?:for|about|titled?|on|regarding)\b.+",
            # "And another one for X" - implicit create after prior create
            r"\b(?:and\s+)?another\s+(?:one|task)\b\s+(?:for|about|titled?|on|regarding)\b.+",
        ]
        
        for pattern in explicit_patterns:
            if re.search(pattern, lower_text, flags=re.IGNORECASE | re.DOTALL):
                return True
        
        return False

    def _is_follow_up_confirmation(self, user_input: str) -> bool:
        """Accept only explicit confirmation replies for pending mutations."""
        if not user_input:
            return False

        text = re.sub(r"[^\w\s]", "", user_input.strip().lower())
        return text in {"confirm", "yes"}

    def _requires_human_confirmation(self, operation: Optional[str]) -> bool:
        """Return True for task mutations that should be confirmed before execution."""
        if not operation:
            return False
        return operation in {
            "complete_task",
            "reopen_task",
            "delete_task",
            "search_and_complete",
            "search_and_reopen",
            "search_and_delete",
        }

    def _has_pending_task_creation_suggestion(self, state: WorkflowState) -> bool:
        """Determine whether the workflow has an in-flight task creation suggestion to confirm."""
        if state.pending_task_creation:
            return True

        response = (state.last_assistant_response or "").lower()
        if re.search(r"\b(already done|done already|already completed|no confirmation required|no need to confirm|no need for confirmation)\b", response):
            return False
        return bool(re.search(r"\b(would you like|should i|do you want me to|do you want me|want me to|shall i)\b.*\b(create|make)\b.*\b(task)\b", response))

    def _infer_task_title_description_from_query(self, user_input: str) -> Dict[str, str]:
        """Extract explicit title and description from query, or infer from context."""
        if not user_input:
            return {"title": "New task", "description": "Create a new task based on the last request."}

        normalized = re.sub(r"\s+", " ", user_input.strip())

        # Reuse the canonical parser so explicit fields retain every word.
        # The prior case-insensitive lookahead incorrectly treated a capitalized
        # word (for example, "Quarterly") as the end of the description.
        title, description = extract_create_task_fields(normalized)
        if title and description:
            return {"title": title, "description": description}
        
        # Try simple format: "create a task for X", "create a task about Y"
        simple_format_match = re.search(
            r"\b(?:create|add|make|another)\b(?:\s+(?:a|new|one))?\s*(?:task)?\s+(?:for|about|titled?|on|regarding)\s+(.+?)$",
            normalized,
            flags=re.IGNORECASE
        )
        if simple_format_match:
            title = simple_format_match.group(1).strip()
            if len(title) > 80:
                title = title[:80].rsplit(" ", 1)[0] + "..."
            return {"title": title, "description": ""}
        
        # Fallback: infer from full query
        title = normalized
        description = normalized

        if len(normalized) > 120:
            title = normalized[:80].rsplit(" ", 1)[0] + "..."
            description = normalized

        if re.search(r"\b(about|related to|for|to)\b", normalized, flags=re.IGNORECASE):
            title = normalized
            if len(title) > 80:
                title = title[:80].rsplit(" ", 1)[0] + "..."

        return {"title": title, "description": description}

    def _capture_pending_task_creation_suggestion(self, state: WorkflowState, response_text: str) -> None:
        """Save a pending task creation suggestion for follow-up confirmations."""
        if not response_text or not isinstance(response_text, str):
            state.pending_task_creation = None
            return

        response_lower = response_text.lower()
        if re.search(r"\b(already done|done already|already completed|no confirmation required|no need to confirm|no need for confirmation)\b", response_lower):
            state.pending_task_creation = None
            return

        if re.search(r"\b(would you like|should i|do you want me to|do you want me|want me to|shall i)\b.*\b(create|make)\b.*\b(task)\b", response_lower) and "created" not in response_lower:
            suggestion = {
                "source_query": state.last_user_input or state.user_input,
                "suggestion_text": response_text,
            }
            task_inference = self._infer_task_title_description_from_query(suggestion["source_query"])
            suggestion.update(task_inference)
            state.pending_task_creation = suggestion
            logger.info("Stored pending task creation suggestion for later confirmation")
        else:
            state.pending_task_creation = None

    async def _create_task_from_confirmation(self, state: WorkflowState) -> Optional[Dict[str, Any]]:
        """Create a task when the user confirms a previous assistant suggestion."""
        if not self.mcp_server:
            return {"status": "error", "message": "MCP server not available"}

        source_data = state.pending_task_creation or {
            "source_query": state.last_user_input or state.user_input,
        }
        title = source_data.get("title")
        description = source_data.get("description") or source_data.get("source_query")

        if not title:
            title = (state.last_user_input or state.user_input or "New task").strip()
            if len(title) > 100:
                title = title[:96].rsplit(" ", 1)[0] + "..."

        if description is None:
            description = state.last_user_input or state.user_input or ""
        elif not description:
            description = ""

        try:
            from ..mcp_server import ToolCallRequest

            request = ToolCallRequest(
                tool_name="create_task",
                arguments={"title": title, "description": description},
            )
            result = await self.mcp_server.call_tool(request)
            if result.success:
                logger.info("Follow-up confirmation executed create_task successfully")
                # Store created task in state for follow-up actions without explicit ID
                created = result.result if isinstance(result.result, dict) else None
                if created:
                    state.last_created_task = created
                    try:
                        assistant_text = await chat_with_tools(
                            user_message=f"I created a task titled '{title}'. Summarize the created task.",
                            tool_results=json.dumps(result.result, default=str),
                            force_natural=True,
                        )
                        state.last_assistant_response = assistant_text
                        state.dialog_history.append({"role": "assistant", "message": assistant_text, "timestamp": datetime.utcnow().isoformat()})
                        state.workflow_log.append({
                            "agent": "assistant_synth",
                            "action": "synthesize_created_task",
                            "result": assistant_text,
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                    except Exception:
                        logger.debug("Assistant synthesis after create_task failed", exc_info=True)
                return {
                    "status": "success",
                    "message": f"Created task '{title}'",
                    "created_task": result.result,
                }
            return {
                "status": "error",
                "message": result.error or "Task creation failed",
            }
        except Exception as e:
            logger.error(f"Error executing follow-up create task: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def _should_use_llm_routing_classifier(self, has_task: bool, has_rag: bool, has_analysis: bool, wants_full_flow: bool, compound_prompt: bool = False) -> bool:
        """Use the LLM classifier for ambiguous or compound prompts when enabled."""
        if not os.getenv("ENABLE_LLM_ROUTING_CLASSIFIER", "true").lower() in {"1", "true", "yes", "on"}:
            return False
        if wants_full_flow:
            return False
        signal_count = int(has_task) + int(has_rag) + int(has_analysis)
        return compound_prompt or signal_count <= 1

    def _classify_route_with_llm(self, user_input: str, has_task: bool, has_rag: bool, has_analysis: bool, compound_prompt: bool = False) -> Optional[str]:
        """Ask the LLM to classify an ambiguous prompt into a routing category."""
        if not user_input or not user_input.strip():
            return None

        if not self._should_use_llm_routing_classifier(has_task, has_rag, has_analysis, False, compound_prompt):
            return None

        prompt = (
            "Classify the user request into the best routing category. Return JSON only with keys 'route' and 'confidence'.\n"
            "Route definitions:\n"
            "- task: Task management only (create, list, complete, delete tasks)\n"
            "- task_analysis: Task management + analysis (list tasks, then analyze/estimate/prioritize/report on them)\n"
            "- task_rag: Task management + document/code retrieval (find tasks related to documentation/codebase)\n"
            "- rag: Document/code retrieval only (search docs, architecture, source code)\n"
            "- rag_analysis: Document retrieval + analysis (find docs, then analyze/summarize/compare)\n"
            "- analysis: Analysis only (analyze, summarize, estimate, prioritize, report without task context)\n"
            "- task_rag_analysis: All three - tasks + documents + analysis\n"
            "- chat: General conversation, no specific domain\n"
            "Use 'uncertain' only when you cannot confidently classify.\n"
            f"User request: {user_input}"
        )

        try:
            response = generate_response(prompt, temperature=0.0)
            if not response:
                return None

            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()

            parsed = json.loads(cleaned) if cleaned.startswith("{") else None
            if isinstance(parsed, dict):
                route = str(parsed.get("route", "")).strip().lower()
                confidence = str(parsed.get("confidence", "")).strip().lower()
                if route in {"task", "rag", "analysis", "chat", "task_rag", "task_analysis", "rag_analysis", "task_rag_analysis"} and confidence not in {"low", "uncertain", "unknown"}:
                    return route
        except Exception as exc:
            logger.debug(f"LLM routing classifier failed: {exc}")

        return None

    def _map_route_label_to_stage(self, route_label: str) -> str:
        """Map a classifier label to the workflow stage names used by the graph."""
        if route_label in {"task_rag_analysis"}:
            return "task_rag_analysis"
        if route_label in {"task_rag"}:
            return "task_rag"
        if route_label in {"task_analysis"}:
            return "task_analysis"
        if route_label in {"rag_analysis"}:
            return "rag_analysis"
        if route_label == "task":
            return "task_only"
        if route_label == "rag":
            return "rag_only"
        if route_label == "analysis":
            return "analysis_only"
        if route_label == "chat":
            return "chat_only"
        return "chat_only"

    def _should_use_bulk_search_action(self, user_input: str) -> bool:
        """Decide whether a status action should search for matching tasks first.

        This uses the LLM for semantic intent when the request is broad or contextual,
        and only falls back to lightweight heuristics for common selection phrases.
        """
        if not user_input:
            return False

        normalized = re.sub(r"\s+", " ", user_input.strip())
        lower_text = normalized.lower()

        if re.search(r"\b(?:task\s*(?:with\s+)?(?:id\s*)#?|id\s*#?)(\d+)\b", normalized, flags=re.IGNORECASE):
            return False

        has_status_action = bool(re.search(r"\b(?:complete|completed|done|finish|reopen|delete|remove|erase|trash|discard)\b", lower_text))
        if not has_status_action:
            return False

        has_selection_context = bool(re.search(r"\b(?:any|all|these|them|that|the|remaining|pending|finished|completed|done|ones)\b", lower_text))
        if has_selection_context:
            return True

        # A descriptive target (such as "related to authentication") must be
        # resolved before a status mutation, even when followed by a list clause.
        if re.search(r"\b(?:related to|about|regarding|associated with)\b", lower_text):
            return True

        if not re.search(r"\b(?:task|tasks|pending|open|incomplete|related|about|documentation|auth|authentication|api|backend|frontend|database|test|review|bug|feature|design|architecture)\b", lower_text):
            return False

        try:
            prompt = (
                "Decide whether this request means to search for matching tasks first and then apply the status action to those results. "
                "Return JSON only with keys 'use_bulk_search' and 'reason'.\n"
                f"User request: {normalized}"
            )
            response = generate_response(prompt, temperature=0.0)
            if not response:
                return False

            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()

            if cleaned.startswith("{"):
                parsed = json.loads(cleaned)
                if isinstance(parsed, dict):
                    use_bulk = parsed.get("use_bulk_search")
                    if isinstance(use_bulk, bool):
                        return use_bulk
        except Exception as exc:
            logger.debug(f"Bulk action classifier failed: {exc}")

        return False

    def _route_stages(self, state: WorkflowState) -> str:
        """Route to appropriate workflow stages based on router analysis."""
        if state.current_agent:
            return state.current_agent
        return END
    
    def _normalize_next_stage(self, current_agent: Optional[str]) -> str:
        """Normalize the workflow path after a stage completes."""
        if not current_agent:
            return "chat_only"

        if current_agent == "task_rag_analysis":
            return "rag_analysis"
        if current_agent == "task_rag":
            return "rag"
        if current_agent == "task_analysis":
            return "analysis"
        if current_agent == "rag_analysis":
            return "analysis"
        if current_agent in {"rag", "task_only", "analysis_only", "chat_only"}:
            return current_agent
        return current_agent

    def _extract_task_query(self, user_input: str) -> str:
        """Extract the task-related portion of a complex user input."""
        if not user_input:
            return ""

        normalized = re.sub(r"\s+", " ", user_input.strip())
        if not normalized:
            return ""

        segments = [segment.strip(" ,.;:") for segment in re.split(r"\b(?:and then|then|and)\b", normalized, flags=re.IGNORECASE) if segment.strip()]
        if len(segments) > 1:
            task_keywords = [
                "task", "tasks", "pending", "open", "incomplete", "undone", "unfinished",
                "list", "show", "find", "search", "get", "display", "retrieve", "due",
                "today", "tomorrow", "complete", "delete", "reopen"
            ]
            analysis_keywords = ["analyze", "analysis", "summarize", "summary", "explain", "inspect", "review", "understand", "compare", "report", "priority", "importance", "important"]

            for segment in segments:
                if _detect_explicit_date_constraint(segment):
                    return segment.strip()

            for segment in segments:
                lower_segment = segment.lower()
                if any(keyword in lower_segment for keyword in task_keywords) and not any(keyword in lower_segment for keyword in analysis_keywords):
                    return segment.strip()

        task_phrase = segments[0].strip()

        # If the first segment contains both task and pending indicators, use it directly.
        if re.search(r"\b(pending|open|incomplete|undone|not done|unfinished)\b", task_phrase, flags=re.IGNORECASE) and re.search(r"\b(task|tasks)\b", task_phrase, flags=re.IGNORECASE):
            return task_phrase

        # Extract a narrower phrase around task-related keywords if present.
        match = re.search(
            r"((?:list|show|find|search|get|display|retrieve)[^\.\n]*?\b(?:pending|open|incomplete|undone|unfinished)\b[^\.\n]*?\b(?:task|tasks)\b)",
            normalized,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()

        match = re.search(r"((?:pending|open|incomplete|undone|unfinished)[^\.\n]*?\b(?:task|tasks)\b)", normalized, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()

        return task_phrase

    def _task_stage_transition(self, state: WorkflowState) -> str:
        """Determine next stage after task stage based on current execution path."""
        path = state.current_agent or "chat_only"
        logger.info(f"Task stage transition evaluating current_agent={path}")

        if path in {"task_rag_analysis", "rag_analysis"}:
            logger.info("Task stage transition -> rag_analysis (maps to rag_stage)")
            return "rag_analysis"
        if path in {"task_rag", "rag"}:
            logger.info("Task stage transition -> rag (maps to rag_stage)")
            return "rag"
        if path in {"task_analysis", "analysis"}:
            logger.info("Task stage transition -> analysis (maps to analysis_stage)")
            return "analysis"
        if path == "task_only":
            if any(word in (state.user_input or "").lower() for word in ["summary", "summarize", "report", "stats", "trend", "search", "find", "related", "about", "documentation", "architecture", "design", "context", "info", "details"]):
                logger.info("Task stage transition -> rag_analysis for contextual or analytical prompt")
                return "rag_analysis"
            logger.info("Task stage transition -> chat_final")
            return "chat_final"

        if path in {"rag_only", "analysis_only", "chat_only"} and any(word in (state.user_input or "").lower() for word in ["task", "tasks", "complete", "delete", "reopen", "list", "show", "mark"]):
            logger.info("Task-like chat prompt detected; forcing task stage first")
            return "task_stage"

        logger.info("Task stage transition -> chat_final")
        return "chat_final"

    def _rag_stage_transition(self, state: WorkflowState) -> str:
        """Determine next stage after RAG stage based on current execution path."""
        path = state.current_agent or "chat_only"
        logger.info(f"RAG stage transition evaluating current_agent={path}")

        if path == "task_rag_analysis":
            logger.info("RAG stage transition -> analysis (maps to analysis_stage)")
            return "analysis"
        if path == "task_rag":
            logger.info("RAG stage transition -> chat_final")
            return "chat_final"
        if path == "rag_analysis":
            logger.info("RAG stage transition -> analysis (maps to analysis_stage)")
            return "analysis"
        if path == "rag_only":
            logger.info("RAG stage transition -> chat_final")
            return "chat_final"

        logger.info("RAG stage transition -> chat_final")
        return "chat_final"
    
    async def _task_stage_node(self, state: WorkflowState) -> WorkflowState:
        """Execute task management stage using same logic as CoordinatorAgent."""
        logger.info(f"Executing task stage for {state.task_id}")
        
        try:
            agent_id = "task_manager_001"
            task_query = self._extract_task_query(state.user_input)
            task_status_action = looks_like_task_status_update_request(state.user_input)

            combined_search_action = bool(re.search(r"\b(list|show|find|search|look|display|get|summarize|related|about|priority|open|pending|due|today|tomorrow)\b", state.user_input, flags=re.IGNORECASE)) and bool(re.search(r"\b(complete|completed|done|finish|reopen|delete|remove|erase|trash|discard)\b", state.user_input, flags=re.IGNORECASE))

            # Check if this is an explicit create with other operations (list/search)
            has_explicit_create = self._is_explicit_create_task_request(state.user_input)
            user_input_for_list_search = state.user_input
            
            # If we have explicit create, separate it from the list/search part
            if has_explicit_create:
                # Remove the create part from input for list/search operations
                user_input_for_list_search = re.sub(
                    r"\b(?:create|add|make)\b(?:\s+a|\s+new)?\s*task.*?(?:title|with title).*?description.*",
                    "",
                    state.user_input,
                    flags=re.IGNORECASE | re.DOTALL
                ).strip()

            if state.pending_action and self._is_follow_up_confirmation(state.user_input):
                pending_action = dict(state.pending_action)
                state.pending_action = None
                state.last_assistant_response = None
                task_payload = {
                    "operation": pending_action.get("operation"),
                    "user_input": pending_action.get("user_input") or state.user_input,
                    "mcp_server": self.mcp_server,
                }
                if pending_action.get("task_id") is not None:
                    task_payload["task_id"] = pending_action.get("task_id")
                if pending_action.get("title") is not None:
                    task_payload["title"] = pending_action.get("title")
                if pending_action.get("description") is not None:
                    task_payload["description"] = pending_action.get("description")
                if pending_action.get("last_searched_tasks"):
                    task_payload["last_searched_tasks"] = pending_action.get("last_searched_tasks")
                logger.info(f"Executing pending action confirmation with payload keys: {list(task_payload.keys())}")
                state.workflow_status = "completed"
                task_result = await self.agent_manager.execute_task(agent_id, task_payload)
                state.workflow_log.append({
                    "agent": agent_id,
                    "action": f"confirm_{task_payload.get('operation', 'task_action')}",
                    "result": task_result,
                    "timestamp": datetime.utcnow().isoformat(),
                })
            elif self._is_follow_up_confirmation(state.user_input) and self._has_pending_task_creation_suggestion(state):
                follow_up_result = await self._create_task_from_confirmation(state)
                task_result = follow_up_result or {"status": "error", "message": "Follow-up confirmation failed"}
                state.workflow_log.append({
                    "agent": agent_id,
                    "action": "follow_up_create_task",
                    "result": task_result,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                if isinstance(task_result, dict) and task_result.get("status") == "success":
                    state.stage_tool_results += f"\nCreated task after confirmation: {task_result.get('created_task', {})}\n"
                    # also store created task in workflow memory for subsequent commands
                    created = task_result.get('created_task')
                    if isinstance(created, dict):
                        state.last_created_task = created
                state.pending_task_creation = None
                state.last_proposal = None
                state.pending_task_creation = None
                state.last_assistant_response = None
                # skip normal task agent execution path
                task_result = task_result
            else:
                # Determine operation and create payload (use cleaned input if explicit create present)
                task_payload = None
                check_input = user_input_for_list_search if has_explicit_create else state.user_input
                
                # Use semantic intent rather than a long hard-coded keyword list to decide whether
                # a request should search for matching tasks first and then apply the action.
                should_use_bulk_search_action = self._should_use_bulk_search_action(check_input)
                
                task_id, title, description = extract_update_task_fields(check_input)
                if task_id is not None and (title is not None or description is not None):
                    task_payload = {
                        "operation": "update_task",
                        "task_id": task_id,
                        "title": title,
                        "description": description,
                        "mcp_server": self.mcp_server,
                    }
                elif task_status_action == "complete_task":
                    if should_use_bulk_search_action:
                        # Search first, then complete from results
                        task_payload = {
                            "operation": "search_and_complete",
                            "user_input": check_input,
                            "mcp_server": self.mcp_server,
                        }
                    elif combined_search_action:
                        task_payload = {
                            "operation": "search_and_create",
                            "user_input": check_input,
                            "mcp_server": self.mcp_server,
                        }
                    else:
                        task_payload = {
                            "operation": "complete_task",
                            "user_input": check_input,
                            "mcp_server": self.mcp_server,
                        }
                elif task_status_action == "reopen_task":
                    if should_use_bulk_search_action:
                        task_payload = {
                            "operation": "search_and_reopen",
                            "user_input": check_input,
                            "mcp_server": self.mcp_server,
                        }
                    elif combined_search_action:
                        task_payload = {
                            "operation": "search_and_create",
                            "user_input": check_input,
                            "mcp_server": self.mcp_server,
                        }
                    else:
                        task_payload = {
                            "operation": "reopen_task",
                            "user_input": check_input,
                            "mcp_server": self.mcp_server,
                        }
                elif re.search(r"\b(delete|remove|erase|trash|discard)\b", check_input, flags=re.IGNORECASE):
                    if should_use_bulk_search_action:
                        task_payload = {
                            "operation": "search_and_delete",
                            "user_input": check_input,
                            "mcp_server": self.mcp_server,
                        }
                    elif combined_search_action:
                        task_payload = {
                            "operation": "search_and_create",
                            "user_input": check_input,
                            "mcp_server": self.mcp_server,
                        }
                    else:
                        task_payload = {
                            "operation": "delete_task",
                            "user_input": check_input,
                            "mcp_server": self.mcp_server,
                        }
                else:
                    task_payload = {
                        "operation": "search_and_create",
                        "user_input": check_input,
                        "mcp_server": self.mcp_server,
                    }

                # If no explicit task id in user_input but we have a recently created task, use it
                if task_payload.get("user_input") and not re.search(r"\b(?:task\s*(?:with\s+)?(?:id\s*)#?|id\s*#?)(\d+)\b", task_payload.get("user_input"), flags=re.IGNORECASE):
                    if state.last_created_task and isinstance(state.last_created_task, dict):
                        created_id = state.last_created_task.get("task_id") or state.last_created_task.get("id")
                        if created_id is not None:
                            task_payload["task_id"] = int(created_id)
                    # If no explicit task ID and operation is complete/delete/reopen with implicit selection (any/all/pending),
                    # pass the last searched tasks for bulk operations
                    elif task_payload.get("operation") in ("complete_task", "delete_task", "reopen_task") and state.last_searched_tasks:
                        if re.search(r"\b(?:any|all|these|them|that|the|remaining|pending|finished|completed|done)\b", task_payload.get("user_input", ""), flags=re.IGNORECASE):
                            task_payload["last_searched_tasks"] = state.last_searched_tasks

                if self._requires_human_confirmation(task_payload.get("operation")):
                    preview_result = await self.agent_manager.execute_task(
                        agent_id,
                        {
                            "operation": "preview_mutation",
                            "target_operation": task_payload.get("operation"),
                            "user_input": check_input,
                            "mcp_server": self.mcp_server,
                        },
                    )
                    preview_tasks = preview_result.get("tasks", []) if isinstance(preview_result, dict) else []
                    if task_payload.get("operation") in {"complete_task", "search_and_complete"}:
                        confirmed_operation = "complete_task"
                    elif task_payload.get("operation") in {"reopen_task", "search_and_reopen"}:
                        confirmed_operation = "reopen_task"
                    else:
                        confirmed_operation = "delete_task"
                    state.pending_action = {
                        "operation": confirmed_operation,
                        "user_input": check_input,
                        "task_id": task_payload.get("task_id"),
                        "title": task_payload.get("title"),
                        "description": task_payload.get("description"),
                        "last_searched_tasks": preview_tasks,
                    }
                    state.workflow_status = "awaiting_confirmation"
                    action_label = {
                        "complete_task": "completed",
                        "reopen_task": "reopened",
                        "delete_task": "deleted",
                    }[confirmed_operation]
                    state.stage_tool_results += f"\nI found {len(preview_tasks)} matching task(s) to be {action_label}. Reply 'confirm' to {action_label} them.\n"
                    for preview_task in preview_tasks:
                        preview_id = preview_task.get("id") or preview_task.get("task_id")
                        state.stage_tool_results += f"  • ID {preview_id}: {preview_task.get('title', 'Untitled')}\n"
                    state.stage_tool_results += "Reply 'confirm' to proceed.\n"
                    state.workflow_log.append({
                        "agent": agent_id,
                        "action": "pending_confirmation",
                        "result": {"status": "awaiting_confirmation", "operation": confirmed_operation, "tasks": preview_tasks},
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    task_result = {"status": "awaiting_confirmation", "operation": task_payload.get("operation")}
                else:
                    logger.info(f"Routing to agent {agent_id} with payload keys: {list(task_payload.keys())} and query: {task_query}")
                    task_result = await self.agent_manager.execute_task(agent_id, task_payload)

                    state.workflow_log.append({
                        "agent": agent_id,
                        "action": task_payload.get("operation", "search_and_create"),
                        "result": task_result,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
            
            if isinstance(task_result, dict) and task_result.get("status") in ("success", "partial_success"):
                count = task_result.get("tasks_found", task_result.get("count", 0))
                # Store the search results for potential follow-up actions (e.g., "complete any that are pending")
                tasks_list = task_result.get("tasks", [])
                if isinstance(tasks_list, list):
                    state.last_searched_tasks = tasks_list
                state.stage_tool_results += f"\n\nFound {count} tasks:\n"
                for t in task_result.get("tasks", [])[:10]:
                    task_id = t.get("id") or t.get("task_id")
                    status = "✓ Done" if t.get("completed") or str(t.get("status", "")).lower() == "completed" else "⏳ Pending"
                    title = t.get("title", "Untitled")
                    if task_id is not None:
                        state.stage_tool_results += f"  • [{status}] ID {task_id}: {title}\n"
                    else:
                        state.stage_tool_results += f"  • [{status}] {title}\n"
                summary_id = task_result.get("summary_task_id")
                if summary_id:
                    state.stage_tool_results += f"\nCreated summary task: {summary_id}\n"
                logger.info(f"Task stage completed with {count} tasks")
                # Check for any LLM proposals embedded in agent results (auto-propose)
                try:
                    await self._scan_and_execute_proposal_from_result(state, task_result)
                except Exception as e:
                    logger.debug(f"No executable proposal found in task result: {e}")
            
            # If explicit create was detected, create after list/search only when
            # the task agent has not already handled the create clause. Combined
            # search-and-create commands otherwise create the same task twice.
            task_already_created = (
                isinstance(task_result, dict)
                and bool(task_result.get("created_task") or task_result.get("created_tasks"))
            )
            if has_explicit_create and not task_already_created:
                task_details = self._infer_task_title_description_from_query(state.user_input)
                if not self.mcp_server:
                    create_result = {"status": "error", "message": "MCP server not available"}
                else:
                    try:
                        from ..mcp_server import ToolCallRequest
                        request = ToolCallRequest(
                            tool_name="create_task",
                            arguments={"title": task_details.get("title"), "description": task_details.get("description")},
                        )
                        result = await self.mcp_server.call_tool(request)
                        if result.success:
                            create_result = {
                                "status": "success",
                                "message": f"Created task '{task_details.get('title')}'",
                                "created_task": result.result,
                            }
                            state.last_created_task = result.result
                            try:
                                assistant_text = await chat_with_tools(
                                    user_message=f"I created a task titled '{task_details.get('title')}'. Summarize the created task.",
                                    tool_results=json.dumps(result.result, default=str),
                                    force_natural=True,
                                )
                                state.last_assistant_response = assistant_text
                                state.dialog_history.append({"role": "assistant", "message": assistant_text, "timestamp": datetime.utcnow().isoformat()})
                                state.workflow_log.append({
                                    "agent": "assistant_synth",
                                    "action": "synthesize_created_task",
                                    "result": assistant_text,
                                    "timestamp": datetime.utcnow().isoformat(),
                                })
                            except Exception:
                                logger.debug("Assistant synthesis after explicit create failed", exc_info=True)
                        else:
                            create_result = {
                                "status": "error",
                                "message": result.error or "Task creation failed",
                            }
                    except Exception as e:
                        logger.error(f"Error creating explicit task: {e}", exc_info=True)
                        create_result = {"status": "error", "message": str(e)}
                
                state.workflow_log.append({
                    "agent": agent_id,
                    "action": "explicit_create_task",
                    "result": create_result,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                if isinstance(create_result, dict) and create_result.get("status") == "success":
                    state.stage_tool_results += f"\nCreated task: {create_result.get('created_task', {})}\n"
        except Exception as e:
            logger.error(f"Error in task stage: {e}", exc_info=True)
            state.error_message = str(e)
            state.workflow_status = "error"
        finally:
            state.current_agent = self._normalize_next_stage(state.current_agent)
        
        return state
    
    async def _rag_stage_node(self, state: WorkflowState) -> WorkflowState:
        """Execute RAG (Retrieval-Augmented Generation) stage."""
        logger.info(f"Executing RAG stage for {state.task_id}")
        
        try:
            agent_id = "rag_agent_001"
            rag_payload = {
                "operation": "search",
                "query": state.user_input,
                "mcp_server": self.mcp_server,
            }
            logger.info(f"Routing to agent {agent_id} for RAG with query preview: {state.user_input[:100]}")
            rag_result = await self.agent_manager.execute_task(agent_id, rag_payload)
            
            state.workflow_log.append({
                "agent": agent_id,
                "action": "search",
                "result": rag_result,
                "timestamp": datetime.utcnow().isoformat(),
            })
            
            if isinstance(rag_result, dict) and rag_result.get("status") == "success":
                state.stage_context += f"\nRAG results: {rag_result}"
                logger.info(f"RAG stage succeeded: Found {rag_result.get('count', 0)} results")
                try:
                    await self._scan_and_execute_proposal_from_result(state, rag_result)
                except Exception:
                    pass
            
        except Exception as e:
            logger.error(f"Error in RAG stage: {e}", exc_info=True)
            state.error_message = str(e)
            state.workflow_status = "error"
        
        return state
    
    async def _analysis_stage_node(self, state: WorkflowState) -> WorkflowState:
        """Execute analysis stage."""
        logger.info(f"Entering analysis stage for {state.task_id} with current_agent={state.current_agent}")
        
        try:
            agent_id = "analyzer_001"
            analysis_payload = {
                "operation": "analyze_data",
                "message": state.user_input,
                "context": state.stage_context,
                "tool_results": state.stage_tool_results,
            }
            logger.info(f"Routing to agent {agent_id} for analysis")
            analysis_result = await self.agent_manager.execute_task(agent_id, analysis_payload)
            
            state.workflow_log.append({
                "agent": agent_id,
                "action": "analyze_data",
                "result": analysis_result,
                "timestamp": datetime.utcnow().isoformat(),
            })
            
            if isinstance(analysis_result, dict) and analysis_result.get("status") == "success":
                state.stage_tool_results += f"\nAnalysis: {analysis_result}"
                logger.info(f"Analysis stage succeeded")
                try:
                    await self._scan_and_execute_proposal_from_result(state, analysis_result)
                except Exception:
                    pass
            
        except Exception as e:
            logger.error(f"Error in analysis stage: {e}", exc_info=True)
            state.error_message = str(e)
            state.workflow_status = "error"
        
        return state
    
    def _format_workflow_response(self, user_input: str, context: str, tool_results_or_stages=None, stages: Optional[list[str]] = None, assistant_response: Optional[str] = None) -> str:
        """Format workflow output into a concise, user-facing summary.

        This function is backward-compatible: callers may pass either
        (user_input, context, stages_list) or (user_input, context, tool_results, stages_list).
        """
        # Allow flexible arg ordering used by older tests/callers
        if stages is None and isinstance(tool_results_or_stages, list):
            stages = tool_results_or_stages
            tool_results = ""
        else:
            tool_results = tool_results_or_stages or ""

        workflow_status = "completed"
        if assistant_response and "error" in assistant_response.lower():
            workflow_status = "error"

        # Map agent ids to human-friendly names for UI
        def _friendly(name: str) -> str:
            if not name:
                return "Unknown"
            n = name.lower()
            if "task" in n:
                return "Task Agent"
            if "rag" in n or "retrieval" in n or "document" in n:
                return "Rag Agent"
            if "analy" in n or "analysis" in n or "analyzer" in n:
                return "Analysis Agent"
            if "chat" in n or "assistant" in n:
                return "Chat Agent"
            # fallback: replace underscores and capitalize
            return " ".join([p.capitalize() for p in name.replace("_", " ").split()])

        mapped = [ _friendly(s) for s in (stages or []) ]
        path_str = " -> ".join(mapped) if mapped else "none"

        summary_lines = [
            "### Summary",
            f"- Request: {user_input}",
            f"- Path: {path_str}",
            f"- Status: {workflow_status}",
            "### Details",
        ]

        # Add tool results as bulleted details when present
        if tool_results:
            for line in str(tool_results).splitlines():
                line = line.strip()
                if not line:
                    continue
                summary_lines.append(f"• {line}")
        else:
            # if no explicit tool_results, still show executed stages as bullets
            for p in mapped:
                summary_lines.append(f"• {p}")

        return "\n".join(summary_lines)

    def _extract_user_response_text(self, response_text: str) -> str:
        """Extract the user-facing section from a chat agent response."""
        if not response_text:
            return ""

        normalized = response_text.replace("\r\n", "\n")
        match = re.search(r"###\s*Response\s*\n([\s\S]+)$", normalized, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Remove any leading debug sections that look like internal workflow metadata.
        cleaned = re.sub(r"(?i)^###\s*(Summary|Details|Analysis|Context|Results)[\s\S]*?\n\n", "", normalized).strip()
        return cleaned or normalized.strip()

    async def _chat_final_node(self, state: WorkflowState) -> WorkflowState:
        """Execute final chat agent to synthesize all results."""
        logger.info(f"Executing final chat stage for {state.task_id}")
        
        try:
            agent_id = "chat_agent_001"
            final_prompt = (
                f"User request: {state.user_input}\n"
                f"Context: {state.stage_context or state.task_context or 'No extra context'}\n"
                f"Results: {state.stage_tool_results or 'No tool results'}\n"
                f"Workflow steps: {len(state.workflow_log)} stages executed"
            )
            final_payload = {
                "operation": "send_message",
                "message": final_prompt,
                "context": state.stage_context or state.task_context,
                "tool_results": state.stage_tool_results,
            }
            logger.info(f"Routing to agent {agent_id} for final synthesis")
            final_result = await self.agent_manager.execute_task(agent_id, final_payload)
            
            state.last_assistant_response = None
            state.dialog_history.append({
                "role": "assistant",
                "message": str(final_result.get("response") if isinstance(final_result, dict) else str(final_result)),
                "timestamp": datetime.utcnow().isoformat(),
            })
            
            state.workflow_log.append({
                "agent": agent_id,
                "action": "synthesize",
                "result": final_result,
                "timestamp": datetime.utcnow().isoformat(),
            })
            
            # Normalize response whether chat agent returned dict or string
            response_text = None
            if isinstance(final_result, dict):
                response_text = final_result.get("response") or final_result.get("result") or ""
                status = final_result.get("status", "success")
            else:
                response_text = str(final_result)
                status = "success"

            if not response_text:
                logger.warning("Chat agent returned empty response; using fallback local response")
                response_text = "I could not generate a response from the chat agent. Please try again."
                status = "error"

            formatted_response = self._format_workflow_response(
                state.user_input,
                state.stage_context or state.task_context or 'No extra context',
                state.stage_tool_results or 'No tool results',
                [stage.get('agent', '') for stage in state.workflow_log if stage.get('agent')],
                assistant_response=response_text,
            )

            extracted_response = self._extract_user_response_text(response_text)
            if extracted_response:
                formatted_response = extracted_response
            else:
                formatted_response = response_text.strip()

            state.last_assistant_response = response_text.strip()
            self._capture_pending_task_creation_suggestion(state, response_text)

            state.result = {
                "status": status,
                "response": formatted_response,
                "workflow_stages": len(state.workflow_log),
            }
            # After final chat output, check if the LLM suggested a proposal and execute it automatically
            try:
                await self._scan_and_execute_proposal_from_text(state, response_text)
            except Exception:
                pass
            
        except Exception as e:
            logger.error(f"Error in chat final stage: {e}", exc_info=True)
            state.error_message = str(e)
            state.result = {
                "status": "error",
                "response": f"Error in final synthesis: {str(e)}",
                "workflow_stages": len(state.workflow_log),
            }
        
        return state

    async def _scan_and_execute_proposal_from_result(self, state: WorkflowState, result: Any) -> None:
        """Look for JSON proposal objects inside an agent result and execute the first valid one."""
        # Search string fields in the result for JSON proposals
        if not result:
            return

        # If the result contains an explicit 'proposed_tool' field, prefer that
        if isinstance(result, dict) and result.get("proposed_tool"):
            payload = result.get("proposed_tool")
            await self._validate_and_call_proposal(state, payload)
            return

        # Otherwise traverse dict values and strings
        candidates = []
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, str):
                    candidates.append(v)
                elif isinstance(v, dict):
                    # nested possible proposal
                    candidates.append(json.dumps(v))
        elif isinstance(result, str):
            candidates.append(result)

        for text in candidates:
            try:
                await self._scan_and_execute_proposal_from_text(state, text)
                return
            except Exception:
                continue

    async def _scan_and_execute_proposal_from_text(self, state: WorkflowState, text: str) -> None:
        """Extract a JSON object from text and attempt to validate/execute as a Proposal."""
        if not text or not isinstance(text, str):
            raise ValueError("No text to scan")

        # Try simple JSON extraction: look for first balanced { ... }
        start = text.find("{")
        if start == -1:
            raise ValueError("No JSON object found")

        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i+1]
                    try:
                        payload = json.loads(candidate)
                    except Exception:
                        raise
                    await self._validate_and_call_proposal(state, payload)
                    return

        raise ValueError("No balanced JSON object found")

    async def _validate_and_call_proposal(self, state: WorkflowState, payload: Any) -> None:
        """Validate payload as Proposal and call MCP server if valid."""
        if not self.mcp_server:
            raise RuntimeError("MCP server not available")

        try:
            proposal = Proposal(**payload)
        except ValidationError as ve:
            logger.debug(f"Proposal payload failed pydantic validation: {ve}")
            raise

        # Auto-populate missing required arguments from context
        # For search/vector_search tools, use user_input as query if not provided
        if proposal.tool in {"search_tasks", "vector_search"}:
            if "query" not in proposal.args and state.user_input:
                proposal.args["query"] = state.user_input
                logger.debug(f"Auto-populated query for {proposal.tool} from user input")

        # Validate against registered tools and execute via MCP server
        result = await self.mcp_server.call_proposed_tool(proposal)
        state.workflow_log.append({
            "agent": "mcp_proposal_executor",
            "action": "proposed_tool",
            "proposal": payload,
            "result": result.result if result.success else {"error": result.error},
            "timestamp": datetime.utcnow().isoformat(),
        })

        if result.success:
            state.stage_tool_results += f"\nExecuted proposed tool: {proposal.tool} -> result: {result.result}\n"
            # If a create or update occurred, synthesize a human-friendly assistant message
            try:
                if proposal.tool in {"create_task", "update_task"}:
                    assistant_text = await chat_with_tools(
                        user_message=(f"I executed {proposal.tool} with args {proposal.args}. "
                                      "Summarize the result."),
                        tool_results=json.dumps(result.result, default=str),
                        force_natural=True,
                    )
                    state.last_assistant_response = assistant_text
                    state.dialog_history.append({"role": "assistant", "message": assistant_text, "timestamp": datetime.utcnow().isoformat()})
                    state.workflow_log.append({
                        "agent": "assistant_synth",
                        "action": "synthesize_proposal_result",
                        "proposal_tool": proposal.tool,
                        "result": assistant_text,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
            except Exception:
                logger.debug("Assistant synthesis after proposal execution failed", exc_info=True)
        else:
            state.stage_tool_results += f"\nProposal rejected: {result.error}\n"
    
    async def _finalize_node(self, state: WorkflowState) -> WorkflowState:
        """Finalize workflow execution and prepare result."""
        logger.info(f"Finalizing workflow {state.task_id}")
        
        state.workflow_status = "completed"
        
        return state
    
    async def execute_workflow(
        self,
        user_input: str,
        task_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute the workflow with given input.
        
        Args:
            user_input: The user's input/request
            task_context: Additional context for the workflow
            
        Returns:
            Dictionary with workflow results
        """
        start_time = time.time()
        logger.info(f"Starting workflow execution with input: {user_input[:100]}")
        
        # Start LangSmith trace
        agent_messages = []
        
        initial_state = WorkflowState(
            user_input=user_input,
            task_context=task_context or {},
        )
        
        # Restore workflow memory fields from task_context if available
        if isinstance(task_context, dict):
            workflow_memory = task_context.get("workflow_memory", {})
            if isinstance(workflow_memory, dict):
                if workflow_memory.get("dialog_history"):
                    initial_state.dialog_history = workflow_memory["dialog_history"]
                if workflow_memory.get("last_user_input"):
                    initial_state.last_user_input = workflow_memory["last_user_input"]
                if workflow_memory.get("last_assistant_response"):
                    initial_state.last_assistant_response = workflow_memory["last_assistant_response"]
                if workflow_memory.get("pending_task_creation"):
                    initial_state.pending_task_creation = workflow_memory["pending_task_creation"]
                if workflow_memory.get("last_created_task"):
                    initial_state.last_created_task = workflow_memory["last_created_task"]
                if workflow_memory.get("last_proposal"):
                    initial_state.last_proposal = workflow_memory["last_proposal"]
                if workflow_memory.get("last_searched_tasks"):
                    initial_state.last_searched_tasks = workflow_memory["last_searched_tasks"]
                if workflow_memory.get("last_selected_task"):
                    initial_state.last_selected_task = workflow_memory["last_selected_task"]
        
        try:
            # Execute workflow
            final_state = await self.graph.ainvoke(initial_state)

            # Normalize final_state
            if isinstance(final_state, dict):
                fs = final_state
            else:
                try:
                    fs = final_state.dict()
                except Exception:
                    fs = {
                        "task_id": getattr(final_state, "task_id", None),
                        "workflow_status": getattr(final_state, "workflow_status", None),
                        "result": getattr(final_state, "result", None),
                        "workflow_log": getattr(final_state, "workflow_log", None) or [],
                        "error_message": getattr(final_state, "error_message", None),
                        "dialog_history": getattr(final_state, "dialog_history", None) or [],
                        "pending_task_creation": getattr(final_state, "pending_task_creation", None),
                        "last_user_input": getattr(final_state, "last_user_input", None),
                        "last_assistant_response": getattr(final_state, "last_assistant_response", None),
                    }

            memory_snapshot = {
                "dialog_history": fs.get("dialog_history", []) if isinstance(fs, dict) else [],
                "last_user_input": fs.get("last_user_input") if isinstance(fs, dict) else getattr(final_state, "last_user_input", None),
                "last_assistant_response": fs.get("last_assistant_response") if isinstance(fs, dict) else getattr(final_state, "last_assistant_response", None),
                "pending_task_creation": fs.get("pending_task_creation") if isinstance(fs, dict) else getattr(final_state, "pending_task_creation", None),
                "last_created_task": fs.get("last_created_task") if isinstance(fs, dict) else getattr(final_state, "last_created_task", None),
                "last_proposal": fs.get("last_proposal") if isinstance(fs, dict) else getattr(final_state, "last_proposal", None),
                "last_searched_tasks": fs.get("last_searched_tasks", []) if isinstance(fs, dict) else getattr(final_state, "last_searched_tasks", []),
                "last_selected_task": fs.get("last_selected_task") if isinstance(fs, dict) else getattr(final_state, "last_selected_task", None),
                "pending_action": fs.get("pending_action") if isinstance(fs, dict) else getattr(final_state, "pending_action", None),
            }
            if isinstance(task_context, dict):
                task_context["workflow_memory"] = memory_snapshot
            else:
                task_context = {"workflow_memory": memory_snapshot}

            agents_used = []
            for entry in fs.get("workflow_log", []) or []:
                agent_name = entry.get("agent")
                if agent_name and agent_name not in agents_used:
                    agents_used.append(agent_name)
                    agent_messages.append({"agent": agent_name, "operation": entry.get("operation")})

            # Normalize the top-level result and derive a user-facing response string
            top_result = fs.get("result")
            if isinstance(top_result, dict):
                response_text = top_result.get("response") or top_result.get("result") or ""
            else:
                response_text = str(top_result) if top_result is not None else ""

            # Trace workflow execution with LangSmith
            execution_time = time.time() - start_time
            trace_workflow_execution(
                workflow_name="langraph_workflow",
                user_input=user_input,
                agent_messages=agent_messages,
                execution_time=execution_time
            )

            return {
                "status": fs.get("workflow_status") or fs.get("status"),
                "result": top_result,
                "response": response_text,
                "workflow_stages": len(fs.get("workflow_log", []) or []),
                "agents_used": agents_used,
                "task_id": fs.get("task_id"),
                "workflow_memory": memory_snapshot,
            }
            
        except Exception as e:
            logger.error(f"Workflow execution error: {e}", exc_info=True)
            
            # Trace error with LangSmith
            execution_time = time.time() - start_time
            trace_workflow_execution(
                workflow_name="langraph_workflow",
                user_input=user_input,
                agent_messages=agent_messages,
                execution_time=execution_time
            )
            
            return {
                "status": "error",
                "result": str(e),
            }
