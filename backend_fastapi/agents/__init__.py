"""
Multi-agent system for task management, AI chat, and RAG operations.
"""

from .agent_base import Agent, AgentRole, AgentStatus, AgentMessage
from .agent_manager import AgentManager
from .agents import (
    TaskAgentSpec,
    ChatAgentSpec,
    RAGAgentSpec,
    AnalysisAgentSpec,
    CoordinatorAgentSpec,
)

__all__ = [
    "Agent",
    "AgentRole",
    "AgentStatus",
    "AgentMessage",
    "AgentManager",
    "TaskAgentSpec",
    "ChatAgentSpec",
    "RAGAgentSpec",
    "AnalysisAgentSpec",
    "CoordinatorAgentSpec",
]
