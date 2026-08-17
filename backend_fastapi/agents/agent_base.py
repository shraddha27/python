"""
Base agent class and types for the multi-agent system.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


class AgentRole(str, Enum):
    """Available agent roles in the system."""
    TASK_MANAGER = "task_manager"      # Manages task creation, updates, completion
    CHAT_AGENT = "chat_agent"          # Handles conversational AI
    RAG_AGENT = "rag_agent"            # Retrieval-Augmented Generation
    ANALYZER = "analyzer"               # Data analysis and insights
    COORDINATOR = "coordinator"         # Orchestrates multi-agent workflows


class AgentStatus(str, Enum):
    """Agent execution status."""
    IDLE = "idle"
    BUSY = "busy"
    PROCESSING = "processing"
    ERROR = "error"
    OFFLINE = "offline"


class AgentMessage(BaseModel):
    """Message passed between agents."""
    sender_id: str
    recipient_id: str
    message_type: str  # e.g., "task_request", "chat_message", "search_query"
    content: Dict[str, Any]
    timestamp: datetime = None
    
    def __init__(self, **data):
        if 'timestamp' not in data:
            data['timestamp'] = datetime.utcnow()
        super().__init__(**data)


class Agent:
    """Base class for all agents in the system."""
    
    def __init__(
        self,
        agent_id: str,
        role: AgentRole,
        name: str,
        description: str = ""
    ):
        self.agent_id = agent_id
        self.role = role
        self.name = name
        self.description = description
        self.status = AgentStatus.IDLE
        self.logger = logging.getLogger(f"Agent.{agent_id}")
        self.message_queue: List[AgentMessage] = []
        
    def get_status(self) -> Dict[str, Any]:
        """Get current agent status."""
        return {
            "agent_id": self.agent_id,
            "role": self.role.value,
            "name": self.name,
            "status": self.status.value,
        }
    
    def receive_message(self, message: AgentMessage) -> None:
        """Receive a message from another agent."""
        self.message_queue.append(message)
        self.logger.debug(f"Received message from {message.sender_id}: {message.message_type}")
    
    async def process_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """
        Process a received message. Override in subclasses.
        Returns a response message or None.
        """
        raise NotImplementedError("Subclasses must implement process_message")
    
    async def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a task. Override in subclasses.
        Returns result dictionary.
        """
        raise NotImplementedError("Subclasses must implement execute")
    
    def set_status(self, status: AgentStatus) -> None:
        """Update agent status."""
        old_status = self.status
        self.status = status
        self.logger.info(f"Status changed: {old_status.value} -> {status.value}")
