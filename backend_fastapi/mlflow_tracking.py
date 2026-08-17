"""
MLflow tracking utilities for experiment management and metric logging.
Tracks Mistral LLM calls, retrieval quality, and workflow performance.
"""

import os
import time
import json
from typing import Any, Dict, Optional
from functools import wraps
import logging

logger = logging.getLogger(__name__)

try:
    import mlflow
except ImportError:
    mlflow = None
    logger.warning("mlflow is not installed; MLflow tracking will be disabled.")
else:
    try:
        import mlflow.pydantic  # type: ignore[import-not-found]
    except ImportError:
        logger.debug("mlflow.pydantic is not available in this environment; continuing without it.")

if mlflow is None:
    class _NullRun:
        pass

    class _NullMLflow:
        @staticmethod
        def set_tracking_uri(*args, **kwargs):
            return None

        @staticmethod
        def set_experiment(*args, **kwargs):
            return None

        @staticmethod
        def start_run(*args, **kwargs):
            return _NullRun()

        @staticmethod
        def set_tags(*args, **kwargs):
            return None

        @staticmethod
        def set_tag(*args, **kwargs):
            return None

        @staticmethod
        def log_param(*args, **kwargs):
            return None

        @staticmethod
        def log_metric(*args, **kwargs):
            return None

        @staticmethod
        def log_text(*args, **kwargs):
            return None

        @staticmethod
        def log_artifact(*args, **kwargs):
            return None

        @staticmethod
        def end_run(*args, **kwargs):
            return None

        @staticmethod
        def active_run(*args, **kwargs):
            return None

    mlflow = _NullMLflow()

# MLflow tracking URI
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns")
MLFLOW_EXPERIMENT_NAME = os.getenv("MLFLOW_EXPERIMENT_NAME", "task-assistant-ai")

# Mistral model configuration
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-tiny")
MISTRAL_API_KEY_PRESENT = bool(os.getenv("MISTRAL_API_KEY", "").strip())

# Initialize MLflow
if mlflow is not None:
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    try:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
    except Exception as exc:
        logger.warning("MLflow initialization failed (%s); tracking will be disabled.", exc)
        mlflow = _NullMLflow()


class MLflowTracker:
    """Context manager for MLflow run tracking."""

    def __init__(self, run_name: str, tags: Optional[Dict[str, str]] = None):
        self.run_name = run_name
        self.tags = tags or {}
        self.run = None
        self.start_time = None
        self._should_end_run = False

    def __enter__(self):
        self.start_time = time.time()
        active_run = getattr(mlflow, "active_run", None)
        if callable(active_run):
            try:
                current_run = active_run()
            except Exception:
                current_run = None
            if current_run is not None:
                logger.debug("MLflow active run detected; reusing existing run context for %s", self.run_name)
                self.run = current_run
                self._should_end_run = False
                mlflow.set_tags({
                    "mistral_model": MISTRAL_MODEL,
                    "mistral_available": str(MISTRAL_API_KEY_PRESENT),
                    **self.tags
                })
                return self.run

        self.run = mlflow.start_run(run_name=self.run_name, nested=True)
        self._should_end_run = True

        # Log system configuration
        mlflow.set_tags({
            "mistral_model": MISTRAL_MODEL,
            "mistral_available": str(MISTRAL_API_KEY_PRESENT),
            **self.tags
        })

        return self.run

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.run is None:
            return False

        if exc_type is not None:
            mlflow.set_tag("status", "error")
            mlflow.log_param("error_type", str(exc_type.__name__))
            mlflow.log_param("error_message", str(exc_val))
            logger.error(f"MLflow run {self.run_name} failed: {exc_val}")
        else:
            mlflow.set_tag("status", "success")
            elapsed = time.time() - self.start_time
            mlflow.log_metric("duration_seconds", elapsed)

        if self._should_end_run:
            mlflow.end_run()

        return False


def track_chat_request(operation_name: str = "chat"):
    """Decorator to track chat/AI requests in MLflow."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            with MLflowTracker(
                run_name=operation_name,
                tags={"operation": operation_name, "type": "ai_request"}
            ):
                # Log input parameters
                if kwargs.get("message"):
                    mlflow.log_param("message_length", len(kwargs["message"]))
                if kwargs.get("use_context"):
                    mlflow.log_param("use_context", kwargs["use_context"])
                if kwargs.get("use_tools"):
                    mlflow.log_param("use_tools", kwargs["use_tools"])
                
                result = await func(*args, **kwargs)
                
                # Log output metrics
                if isinstance(result, dict):
                    if result.get("response"):
                        mlflow.log_param("response_length", len(result["response"]))
                    if result.get("tool_calls"):
                        mlflow.log_param("tool_calls_count", len(result["tool_calls"]))
                    if result.get("context"):
                        mlflow.log_param("context_docs", len(result["context"]))
                
                return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            with MLflowTracker(
                run_name=operation_name,
                tags={"operation": operation_name, "type": "ai_request"}
            ):
                # Log input parameters
                if kwargs.get("message"):
                    mlflow.log_param("message_length", len(kwargs["message"]))
                if kwargs.get("use_context"):
                    mlflow.log_param("use_context", kwargs["use_context"])
                if kwargs.get("use_tools"):
                    mlflow.log_param("use_tools", kwargs["use_tools"])
                
                result = func(*args, **kwargs)
                
                # Log output metrics
                if isinstance(result, dict):
                    if result.get("response"):
                        mlflow.log_param("response_length", len(result["response"]))
                    if result.get("tool_calls"):
                        mlflow.log_param("tool_calls_count", len(result["tool_calls"]))
                    if result.get("context"):
                        mlflow.log_param("context_docs", len(result["context"]))
                
                return result
        
        # Return appropriate wrapper based on function signature
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def track_vector_search(query: str, results_count: int, similarity_threshold: float = 0.0):
    """Log vector search metrics to MLflow."""
    mlflow.log_param("search_query_length", len(query))
    mlflow.log_metric("retrieval_result_count", results_count)
    mlflow.log_param("similarity_threshold", similarity_threshold)


def track_workflow_execution(workflow_name: str, input_text: str, execution_time: float, agent_count: int = 0):
    """Log LangGraph workflow execution metrics to MLflow."""
    with MLflowTracker(
        run_name=f"workflow_{workflow_name}",
        tags={"workflow": workflow_name, "type": "workflow_execution"}
    ):
        mlflow.log_param("input_length", len(input_text))
        mlflow.log_metric("execution_time_seconds", execution_time)
        mlflow.log_param("agent_count", agent_count)


def log_prompt_experiment(prompt_name: str, prompt_template: str, model: str, temperature: float, metrics: Dict[str, float]):
    """Log a prompt experiment variant to MLflow."""
    with MLflowTracker(
        run_name=f"prompt_experiment_{prompt_name}",
        tags={"type": "prompt_experiment", "prompt_name": prompt_name}
    ):
        mlflow.log_param("model", model)
        mlflow.log_param("temperature", temperature)
        mlflow.log_text(prompt_template, "prompt_template.txt")
        
        for metric_name, metric_value in metrics.items():
            mlflow.log_metric(metric_name, metric_value)


def log_retrieval_quality(query: str, results: list, ground_truth_ids: Optional[list] = None):
    """Log retrieval quality metrics (precision, recall, NDCG)."""
    with MLflowTracker(
        run_name="retrieval_quality",
        tags={"type": "retrieval_evaluation"}
    ):
        mlflow.log_param("query", query)
        mlflow.log_metric("result_count", len(results))
        
        if ground_truth_ids and results:
            retrieved_ids = [r.get("id") for r in results]
            relevant = len(set(retrieved_ids) & set(ground_truth_ids))
            precision = relevant / len(retrieved_ids) if retrieved_ids else 0
            recall = relevant / len(ground_truth_ids) if ground_truth_ids else 0
            
            mlflow.log_metric("precision", precision)
            mlflow.log_metric("recall", recall)
            
            # Log result similarities
            avg_similarity = sum(r.get("similarity_score", 0) for r in results) / len(results) if results else 0
            mlflow.log_metric("avg_similarity_score", avg_similarity)


def log_mistral_call(prompt: str, response: str, model: str, temperature: float, latency: float):
    """Log Mistral API call metrics."""
    with MLflowTracker(
        run_name="mistral_call",
        tags={"type": "llm_call", "provider": "mistral"}
    ):
        mlflow.log_param("model", model)
        mlflow.log_param("temperature", temperature)
        mlflow.log_param("prompt_length", len(prompt))
        mlflow.log_param("response_length", len(response))
        mlflow.log_metric("latency_seconds", latency)
        
        # Log token estimates (rough approximation)
        prompt_tokens_estimate = len(prompt) // 4
        response_tokens_estimate = len(response) // 4
        mlflow.log_metric("prompt_tokens_estimate", prompt_tokens_estimate)
        mlflow.log_metric("response_tokens_estimate", response_tokens_estimate)


def get_active_run_id():
    """Get the current active MLflow run ID."""
    run = mlflow.active_run()
    return run.info.run_id if run else None


def log_artifact_json(artifact_name: str, data: Dict[str, Any]):
    """Log a JSON artifact to MLflow."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(data, f, indent=2)
        temp_path = f.name
    
    try:
        mlflow.log_artifact(temp_path, artifact_path=artifact_name)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
