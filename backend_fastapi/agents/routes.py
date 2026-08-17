"""
FastAPI routes for multi-agent system management.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from .agent_manager import AgentManager
from .agent_base import AgentRole
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Global agent manager instance
_agent_manager: Optional[AgentManager] = None


def get_agent_manager() -> AgentManager:
    """Dependency to get the global agent manager."""
    global _agent_manager
    if _agent_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent system not initialized"
        )
    return _agent_manager


def init_agent_manager(manager: AgentManager) -> None:
    """Initialize the global agent manager."""
    global _agent_manager
    _agent_manager = manager


# Request/Response models
class ExecuteTaskRequest(BaseModel):
    agent_id: str
    operation: str
    params: Dict[str, Any] = {}


class ExecuteTaskResponse(BaseModel):
    status: str
    data: Any = None
    error: Optional[str] = None


class AgentStatusResponse(BaseModel):
    agent_id: str
    role: str
    name: str
    status: str


class SystemStatusResponse(BaseModel):
    total_agents: int
    agents_by_role: Dict[str, int]
    agents: List[AgentStatusResponse]
    message_history_size: int


# Routes
@router.get("/system/status", response_model=SystemStatusResponse)
async def get_system_status(manager: AgentManager = Depends(get_agent_manager)):
    """Get system status including all active agents."""
    return manager.get_system_status()


@router.get("/agents", response_model=List[AgentStatusResponse])
async def list_agents(manager: AgentManager = Depends(get_agent_manager)):
    """List all agents in the system."""
    return [agent.get_status() for agent in manager.agents.values()]


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: str,
    manager: AgentManager = Depends(get_agent_manager)
):
    """Get specific agent details."""
    agent = manager.get_agent(agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found"
        )
    return agent.get_status()


@router.get("/agents/role/{role}")
async def get_agents_by_role(
    role: str,
    manager: AgentManager = Depends(get_agent_manager)
):
    """Get all agents with a specific role."""
    try:
        agent_role = AgentRole(role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role: {role}"
        )
    
    agents = manager.get_agents_by_role(agent_role)
    return [agent.get_status() for agent in agents]


@router.post("/execute", response_model=ExecuteTaskResponse)
async def execute_task(
    request: ExecuteTaskRequest,
    manager: AgentManager = Depends(get_agent_manager)
):
    """Execute a task on a specific agent."""
    task = {
        "operation": request.operation,
        **request.params
    }
    
    result = await manager.execute_task(request.agent_id, task)
    
    if result.get("status") == "error":
        return ExecuteTaskResponse(
            status="error",
            error=result.get("message")
        )
    
    return ExecuteTaskResponse(
        status="success",
        data=result
    )


@router.get("/message-history")
async def get_message_history(
    limit: int = 100,
    manager: AgentManager = Depends(get_agent_manager)
):
    """Get recent message history between agents."""
    return {
        "limit": limit,
        "messages": manager.get_message_history(limit)
    }
