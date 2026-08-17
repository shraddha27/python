import traceback
import logging
from typing import Optional
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from backend_fastapi import state
from backend_fastapi.agents.agent_manager import AgentManager
from backend_fastapi.agents.agents import AnalysisAgent, ChatAgent, RAGAgent, TaskAgent
from backend_fastapi.agents.langraph_workflow import LangGraphWorkflow
from backend_fastapi.agents.routes import init_agent_manager
from backend_fastapi.models import Base, DocumentModel, Role, SessionLocal, TaskModel, User, UserRole, engine
from backend_fastapi.mcp_server import MCPServer, MCPToolRegistry
from backend_fastapi.mcp_server import set_mcp_server
from backend_fastapi.embeddings import generate_embedding
from backend_fastapi.rag_tools import (
    execute_tool,
    extract_create_task_fields,
    looks_like_explicit_create_task_request,
    looks_like_task_status_update_request,
    _detect_task_status_filter,
    list_tasks,
    normalize_task_search_query,
    filter_tasks_by_query,
    search_tasks as rag_search_tasks,
)
from backend_fastapi.search import cleanup_duplicate_documents, vector_search
from backend_fastapi.mlflow_tracking import MLflowTracker, log_artifact_json
from backend_fastapi.langsmith_tracing import is_langsmith_enabled

logger = logging.getLogger(__name__)


def startup_event():
    logger.info("Starting up Task Assistant AI backend...")
    
    # Initialize MLflow for experiment tracking
    with MLflowTracker("system_startup", tags={"type": "system_event", "event": "startup"}):
        logger.info("MLflow tracking initialized")
    
    # Log startup configuration
    langsmith_enabled = is_langsmith_enabled()
    logger.info(f"LangSmith tracing enabled: {langsmith_enabled}")
    
    db: Session = SessionLocal()
    try:
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.commit()
    except Exception:
        db.rollback()

    Base.metadata.create_all(bind=engine)

    try:
        inspector = inspect(engine)
        columns = {col['name'] for col in inspector.get_columns('tasks')}
        if 'completed_at' not in columns:
            db.execute(text('ALTER TABLE tasks ADD COLUMN completed_at TIMESTAMP NULL'))
            db.commit()
    except Exception:
        db.rollback()

    try:
        cleanup_duplicate_documents(db)
        db.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS documents_task_id_unique_idx
                ON documents (task_id)
                WHERE task_id IS NOT NULL
                """
            )
        )
        db.commit()
    except Exception:
        db.rollback()

    try:
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_documents_embedding ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

    try:
        agent_manager = AgentManager()
        agent_manager.register_agent(TaskAgent())
        agent_manager.register_agent(ChatAgent())
        agent_manager.register_agent(RAGAgent())
        agent_manager.register_agent(AnalysisAgent())
        init_agent_manager(agent_manager)
        state.agent_manager = agent_manager
    except Exception:
        traceback.print_exc()

    try:
        lg_agent_manager = AgentManager()
        lg_agent_manager.register_agent(TaskAgent())
        lg_agent_manager.register_agent(ChatAgent())
        lg_agent_manager.register_agent(RAGAgent())
        lg_agent_manager.register_agent(AnalysisAgent())

        mcp_server = MCPServer()

        async def create_task_handler(title: str, description: str = "", priority: str = "medium"):
            db = SessionLocal()
            try:
                task = TaskModel(title=title, description=description, completed=False)
                db.add(task)
                db.commit()
                db.refresh(task)
                return {"task_id": task.id, "title": title, "status": "created"}
            finally:
                db.close()

        async def search_tasks_handler(query: str = "", limit: int = 10, **kwargs):
            db = SessionLocal()
            try:
                query_text = query or kwargs.get("fields") or ""
                status_filter = _detect_task_status_filter(query_text)
                search_text = normalize_task_search_query(query_text)
                ranked_results = rag_search_tasks(query_text, db)
                if not isinstance(ranked_results, list):
                    ranked_results = []
                if status_filter is False:
                    ranked_results = [item for item in ranked_results if str(item.get("status", "")).lower() != "completed"]
                elif status_filter is True:
                    ranked_results = [item for item in ranked_results if str(item.get("status", "")).lower() == "completed"]
                if search_text and len(search_text) > 2:
                    ranked_results = filter_tasks_by_query(ranked_results, query_text)
                return {"results": ranked_results[:limit], "count": len(ranked_results[:limit])}
            except Exception as exc:
                return {"results": [], "count": 0, "error": str(exc)}
            finally:
                db.close()

        async def vector_search_handler(query: str, limit: int = 5, threshold: float = 0.7):
            db = SessionLocal()
            try:
                query_embedding = generate_embedding(query)
                docs = vector_search(db, query_embedding, limit=limit)
                results = [d for d in docs if d["similarity_score"] >= threshold]
                return {"results": results, "count": len(results)}
            finally:
                db.close()

        async def complete_task_handler(task_id: int):
            from backend_fastapi.rag_tools import complete_task as complete_task_tool
            db = SessionLocal()
            try:
                return complete_task_tool(task_id=task_id, db=db)
            finally:
                db.close()

        async def reopen_task_handler(task_id: int):
            from backend_fastapi.rag_tools import reopen_task as reopen_task_tool
            db = SessionLocal()
            try:
                return reopen_task_tool(task_id=task_id, db=db)
            finally:
                db.close()

        async def delete_task_handler(task_id: int):
            from backend_fastapi.rag_tools import delete_task as delete_task_tool
            db = SessionLocal()
            try:
                return delete_task_tool(task_id=task_id, db=db)
            finally:
                db.close()

        async def update_task_handler(task_id: int, title: Optional[str] = None, description: Optional[str] = None):
            from backend_fastapi.rag_tools import update_task as update_task_tool
            db = SessionLocal()
            try:
                return update_task_tool(task_id=task_id, title=title, description=description, db=db)
            finally:
                db.close()

        async def list_tasks_handler(limit: int = 100, offset: int = 0, completed: Optional[bool] = None):
            db = SessionLocal()
            try:
                return list_tasks(limit=limit, offset=offset, completed=completed, db=db)
            finally:
                db.close()

        create_task_def = MCPToolRegistry.create_task_tool()
        search_def = MCPToolRegistry.search_tasks_tool()
        complete_task_def = MCPToolRegistry.complete_task_tool()
        reopen_task_def = MCPToolRegistry.reopen_task_tool()
        delete_task_def = MCPToolRegistry.delete_task_tool()
        update_task_def = MCPToolRegistry.update_task_tool()
        list_tasks_def = MCPToolRegistry.list_tasks_tool()
        vector_search_def = MCPToolRegistry.vector_search_tool()

        mcp_server.register_tool(name=create_task_def["name"], description=create_task_def["description"], parameters=create_task_def["parameters"], handler=create_task_handler)
        mcp_server.register_tool(name=search_def["name"], description=search_def["description"], parameters=search_def["parameters"], handler=search_tasks_handler)
        mcp_server.register_tool(name=complete_task_def["name"], description=complete_task_def["description"], parameters=complete_task_def["parameters"], handler=complete_task_handler)
        mcp_server.register_tool(name=reopen_task_def["name"], description=reopen_task_def["description"], parameters=reopen_task_def["parameters"], handler=reopen_task_handler)
        mcp_server.register_tool(name=delete_task_def["name"], description=delete_task_def["description"], parameters=delete_task_def["parameters"], handler=delete_task_handler)
        mcp_server.register_tool(name=update_task_def["name"], description=update_task_def["description"], parameters=update_task_def["parameters"], handler=update_task_handler)
        mcp_server.register_tool(name=list_tasks_def["name"], description=list_tasks_def["description"], parameters=list_tasks_def["parameters"], handler=list_tasks_handler)
        mcp_server.register_tool(name=vector_search_def["name"], description=vector_search_def["description"], parameters=vector_search_def["parameters"], handler=vector_search_handler)

        mcp_server.register_prompt(name="task_creation", template="Create a task: {title}\nDescription: {description}\nPriority: {priority}", description="Template for creating tasks", variables=["title", "description", "priority"])
        mcp_server.register_prompt(name="search_query", template="Search for tasks containing: {query}\nLimit results to: {limit}", description="Template for searching tasks", variables=["query", "limit"])

        state.mcp_server = mcp_server
        state.langraph_workflow = LangGraphWorkflow(lg_agent_manager, mcp_server)
        set_mcp_server(mcp_server)
    except Exception:
        traceback.print_exc()
