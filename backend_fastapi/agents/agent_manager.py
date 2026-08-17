"""
Agent Manager - Orchestrates all agents in the system.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from .agent_base import Agent, AgentMessage, AgentRole, AgentStatus

logger = logging.getLogger(__name__)


class AgentManager:
    """
    Central coordinator for managing multiple agents.
    Handles agent registration, message routing, and workflow orchestration.
    """
    
    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.agents_by_role: Dict[AgentRole, List[str]] = {}
        self.message_history: List[AgentMessage] = []
        self.max_history = 1000  # Keep last N messages
        
    def register_agent(self, agent: Agent) -> None:
        """Register an agent in the system."""
        self.agents[agent.agent_id] = agent
        
        if agent.role not in self.agents_by_role:
            self.agents_by_role[agent.role] = []
        self.agents_by_role[agent.role].append(agent.agent_id)
        
        logger.info(f"Registered agent: {agent.agent_id} (role: {agent.role.value})")
    
    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """Get an agent by ID."""
        return self.agents.get(agent_id)
    
    def get_agents_by_role(self, role: AgentRole) -> List[Agent]:
        """Get all agents with a specific role."""
        agent_ids = self.agents_by_role.get(role, [])
        return [self.agents[aid] for aid in agent_ids if aid in self.agents]
    
    async def send_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """Send a message from one agent to another."""
        recipient = self.get_agent(message.recipient_id)
        if not recipient:
            logger.warning(f"Recipient agent {message.recipient_id} not found")
            return None

        logger.info(
            "Routing agent message: sender=%s -> recipient=%s | type=%s | content_keys=%s",
            message.sender_id,
            message.recipient_id,
            message.message_type,
            list(message.content.keys()) if isinstance(message.content, dict) else type(message.content).__name__,
        )
        
        # Store message in history
        self.message_history.append(message)
        if len(self.message_history) > self.max_history:
            self.message_history.pop(0)
        
        # Deliver message
        recipient.receive_message(message)
        logger.info(
            "Delivered message to %s; queue_size=%s",
            recipient.agent_id,
            len(recipient.message_queue),
        )
        
        # Process and return response
        response = await recipient.process_message(message)
        
        if response:
            logger.info(
                "Agent %s produced response for %s: type=%s",
                recipient.agent_id,
                message.sender_id,
                response.message_type,
            )
            self.message_history.append(response)
            if len(self.message_history) > self.max_history:
                self.message_history.pop(0)
        
        return response
    
    async def execute_task(
        self, 
        agent_id: str, 
        task: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a task on a specific agent."""
        agent = self.get_agent(agent_id)
        if not agent:
            logger.warning("execute_task requested for unknown agent: %s", agent_id)
            return {"status": "error", "message": f"Agent {agent_id} not found"}

        logger.info(
            "Executing task on agent=%s | operation=%s | task_keys=%s",
            agent_id,
            task.get("operation"),
            list(task.keys()),
        )
        logger.info("LLM/orchestrator payload for agent %s: %s", agent_id, task)
        
        agent.set_status(AgentStatus.PROCESSING)
        try:
            result = await agent.execute(task)
            logger.info(
                "Task completed on agent=%s | status=%s",
                agent_id,
                result.get("status") if isinstance(result, dict) else type(result).__name__,
            )
            agent.set_status(AgentStatus.IDLE)
            return result
        except Exception as e:
            logger.error(f"Error executing task on agent {agent_id}: {e}", exc_info=True)
            agent.set_status(AgentStatus.ERROR)
            return {"status": "error", "message": str(e)}
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get status of all agents in the system."""
        return {
            "total_agents": len(self.agents),
            "agents_by_role": {
                role.value: len(agent_ids)
                for role, agent_ids in self.agents_by_role.items()
            },
            "agents": [agent.get_status() for agent in self.agents.values()],
            "message_history_size": len(self.message_history),
        }
    
    def get_message_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent message history."""
        history = self.message_history[-limit:]
        return [
            {
                "sender": msg.sender_id,
                "recipient": msg.recipient_id,
                "type": msg.message_type,
                "timestamp": msg.timestamp.isoformat(),
            }
            for msg in history
        ]
