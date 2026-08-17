"""
LangSmith integration for tracing LangGraph workflows and LLM calls.
Provides detailed visibility into agent execution, tool calls, and decision making.
"""

import os
from typing import Optional, Dict, Any, List
import logging
from datetime import datetime

try:
    import langsmith
    from langsmith.client import Client
except ImportError:  # pragma: no cover - optional dependency in local/test environments
    langsmith = None
    Client = None

logger = logging.getLogger(__name__)

# LangSmith configuration from environment
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT_NAME = os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGSMITH_PROJECT_NAME", "task-assistant-ai")
LANGSMITH_ENDPOINT = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")

# Initialize LangSmith client
client = None

if LANGSMITH_API_KEY:
    try:
        client = Client(
            api_key=LANGSMITH_API_KEY,
            endpoint=LANGSMITH_ENDPOINT
        )
        logger.info(f"LangSmith initialized with project: {LANGSMITH_PROJECT_NAME}")
    except Exception as e:
        logger.warning(f"Failed to initialize LangSmith: {e}")
else:
    logger.info("LangSmith API key not configured - tracing disabled")


class LangSmithTracer:
    """Context manager for LangSmith run tracing."""
    
    def __init__(
        self,
        name: str,
        run_type: str = "chain",
        inputs: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.run_type = run_type
        self.inputs = inputs or {}
        self.tags = tags or []
        self.metadata = metadata or {}
        self.run = None
    
    def __enter__(self):
        if client is None:
            return None
        
        try:
            self.run = client.create_run(
                name=self.name,
                run_type=self.run_type,
                inputs=self.inputs,
                tags=self.tags,
                extra={"metadata": self.metadata}
            )
            return self.run
        except Exception as e:
            logger.warning(f"Failed to create LangSmith run: {e}")
            return None
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.run is None or client is None:
            return
        
        try:
            outputs = None
            if exc_type is not None:
                client.update_run(
                    self.run.id,
                    end_time=datetime.utcnow(),
                    error=str(exc_val),
                    extra={"error_type": exc_type.__name__}
                )
            else:
                client.update_run(
                    self.run.id,
                    end_time=datetime.utcnow(),
                    outputs=outputs
                )
        except Exception as e:
            logger.warning(f"Failed to update LangSmith run: {e}")


def trace_workflow_execution(
    workflow_name: str,
    user_input: str,
    agent_messages: Optional[List[Dict]] = None,
    execution_time: Optional[float] = None,
    agent_count: Optional[int] = None,
):
    """Trace a LangGraph workflow execution."""
    if client is None:
        return
    
    try:
        with LangSmithTracer(
            name=f"workflow_{workflow_name}",
            run_type="chain",
            inputs={"user_input": user_input},
            tags=["workflow", workflow_name],
            metadata={
                "workflow": workflow_name,
                "timestamp": datetime.utcnow().isoformat(),
                "execution_time": execution_time,
                "agent_count": agent_count,
            }
        ) as run:
            if run and agent_messages:
                # Log agent execution details
                for msg in agent_messages:
                    logger.debug(f"Workflow step: {msg}")
    except Exception as e:
        logger.warning(f"Failed to trace workflow: {e}")


def trace_agent_execution(
    agent_name: str,
    operation: str,
    inputs: Dict[str, Any],
    output: Optional[Dict[str, Any]] = None,
    execution_time: Optional[float] = None,
):
    """Trace an individual agent execution."""
    if client is None:
        return
    
    try:
        with LangSmithTracer(
            name=f"{agent_name}_{operation}",
            run_type="agent",
            inputs=inputs,
            tags=["agent", agent_name, operation],
            metadata={
                "agent": agent_name,
                "operation": operation,
                "timestamp": datetime.utcnow().isoformat(),
                "execution_time": execution_time,
            }
        ):
            pass
    except Exception as e:
        logger.warning(f"Failed to trace agent execution: {e}")


def trace_tool_call(
    tool_name: str,
    tool_input: Dict[str, Any],
    tool_output: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
):
    """Trace a tool invocation."""
    if client is None:
        return
    
    try:
        with LangSmithTracer(
            name=f"tool_{tool_name}",
            run_type="tool",
            inputs=tool_input,
            tags=["tool", tool_name],
            metadata={
                "tool": tool_name,
                "timestamp": datetime.utcnow().isoformat(),
                "error": error,
            }
        ):
            pass
    except Exception as e:
        logger.warning(f"Failed to trace tool call: {e}")


def trace_llm_call(
    model: str,
    prompt: str,
    response: Optional[str] = None,
    temperature: Optional[float] = None,
    tokens_used: Optional[Dict[str, int]] = None,
):
    """Trace an LLM API call to Mistral."""
    if client is None:
        return
    
    try:
        with LangSmithTracer(
            name=f"llm_{model}",
            run_type="llm",
            inputs={"prompt": prompt, "temperature": temperature},
            tags=["llm", model],
            metadata={
                "model": model,
                "temperature": temperature,
                "tokens": tokens_used,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ):
            pass
    except Exception as e:
        logger.warning(f"Failed to trace LLM call: {e}")


def trace_vector_search(
    query: str,
    results_count: int,
    top_similarity: Optional[float] = None,
    execution_time: Optional[float] = None,
):
    """Trace a vector search operation."""
    if client is None:
        return
    
    try:
        with LangSmithTracer(
            name="vector_search",
            run_type="tool",
            inputs={"query": query},
            tags=["search", "vector", "retrieval"],
            metadata={
                "query_length": len(query),
                "results_count": results_count,
                "top_similarity": top_similarity,
                "execution_time": execution_time,
                "timestamp": datetime.utcnow().isoformat(),
            }
        ):
            pass
    except Exception as e:
        logger.warning(f"Failed to trace vector search: {e}")


def get_project_runs(limit: int = 10):
    """Fetch recent runs from the LangSmith project."""
    if client is None:
        return []
    
    try:
        runs = client.list_runs(
            project_name=LANGSMITH_PROJECT_NAME,
            limit=limit
        )
        return list(runs)
    except Exception as e:
        logger.warning(f"Failed to fetch LangSmith runs: {e}")
        return []


def get_run_details(run_id: str):
    """Fetch detailed information about a specific run."""
    if client is None:
        return None
    
    try:
        run = client.read_run(run_id)
        return {
            "id": run.id,
            "name": run.name,
            "run_type": run.run_type,
            "status": run.status,
            "inputs": run.inputs,
            "outputs": run.outputs,
            "error": run.error,
            "start_time": run.start_time.isoformat() if run.start_time else None,
            "end_time": run.end_time.isoformat() if run.end_time else None,
            "execution_time": (run.end_time - run.start_time).total_seconds() if run.end_time and run.start_time else None,
        }
    except Exception as e:
        logger.warning(f"Failed to fetch run details: {e}")
        return None


def is_langsmith_enabled() -> bool:
    """Check if LangSmith is properly configured and available."""
    return client is not None
