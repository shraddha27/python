"""
Model Context Protocol (MCP) server implementation for FastAPI.
Provides standardized interface for external tools and LLM interactions.
"""

import logging
import json
import asyncio
import inspect
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
import os

from pydantic import BaseModel, Field, ValidationError
from .llm_proposal import Proposal

logger = logging.getLogger(__name__)


class ToolType(str, Enum):
    """Types of tools available in MCP."""
    FUNCTION = "function"
    RESOURCE = "resource"
    PROMPT = "prompt"


class ToolParameter(BaseModel):
    """Parameter definition for MCP tool."""
    name: str
    type: str  # "string", "number", "boolean", "object", "array"
    description: str
    required: bool = False
    enum: Optional[List[Any]] = None


class ToolDefinition(BaseModel):
    """Definition of an MCP tool."""
    name: str
    description: str
    tool_type: ToolType = ToolType.FUNCTION
    parameters: List[ToolParameter] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolCallRequest(BaseModel):
    """Request to call an MCP tool."""
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    """Result of a tool call."""
    tool_name: str
    success: bool
    result: Any
    error: Optional[str] = None


class MCPServer:
    """
    Model Context Protocol server for FastAPI.
    Manages tools, resources, and prompt templates for LLM interactions.
    """
    
    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self.tool_handlers: Dict[str, Callable] = {}
        self.resources: Dict[str, Any] = {}
        self.prompts: Dict[str, Dict[str, Any]] = {}
        logger.info("Initialized MCP server")
    
    def register_tool(
        self,
        name: str,
        description: str,
        parameters: List[Dict[str, Any]],
        handler: Callable,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register a new tool in the MCP server.
        
        Args:
            name: Tool name
            description: Tool description
            parameters: List of parameter definitions
            handler: Async callable that handles tool execution
            metadata: Additional metadata
        """
        params = [
            ToolParameter(
                name=p.get("name", ""),
                type=p.get("type", "string"),
                description=p.get("description", ""),
                required=p.get("required", False),
                enum=p.get("enum"),
            )
            for p in parameters
        ]
        
        tool_def = ToolDefinition(
            name=name,
            description=description,
            parameters=params,
            metadata=metadata or {},
        )
        
        self.tools[name] = tool_def
        self.tool_handlers[name] = handler
        
        logger.info(f"Registered MCP tool: {name}")
    
    def register_resource(
        self,
        name: str,
        resource_type: str,
        content: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a resource (data source) in MCP."""
        self.resources[name] = {
            "type": resource_type,
            "content": content,
            "metadata": metadata or {},
        }
        logger.info(f"Registered MCP resource: {name}")
    
    def register_prompt(
        self,
        name: str,
        template: str,
        description: str,
        variables: List[str],
    ) -> None:
        """Register a prompt template in MCP."""
        self.prompts[name] = {
            "template": template,
            "description": description,
            "variables": variables,
        }
        logger.info(f"Registered MCP prompt: {name}")
    
    async def call_tool(self, request: ToolCallRequest) -> ToolCallResult:
        """
        Execute a tool call.
        
        Args:
            request: Tool call request
            
        Returns:
            Tool call result
        """
        if request.tool_name not in self.tools:
            return ToolCallResult(
                tool_name=request.tool_name,
                success=False,
                result=None,
                error=f"Tool '{request.tool_name}' not found",
            )
        
        handler = self.tool_handlers.get(request.tool_name)
        if not handler:
            return ToolCallResult(
                tool_name=request.tool_name,
                success=False,
                result=None,
                error=f"No handler registered for tool '{request.tool_name}'",
            )
        
        try:
            logger.info(f"Calling MCP tool: {request.tool_name} with args: {request.arguments}")
            
            # Call handler - check if it's an async function using proper detection
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**request.arguments)
            else:
                # Call sync function and check if result is a coroutine
                result = handler(**request.arguments)
                if asyncio.iscoroutine(result):
                    result = await result
            
            return ToolCallResult(
                tool_name=request.tool_name,
                success=True,
                result=result,
            )
            
        except Exception as e:
            logger.error(f"Error calling MCP tool {request.tool_name}: {e}")
            return ToolCallResult(
                tool_name=request.tool_name,
                success=False,
                result=None,
                error=str(e),
            )

    async def call_proposed_tool(self, proposal: Proposal, user_context: Optional[str] = None) -> ToolCallResult:
        """Validate an LLM proposal then execute the proposed tool if valid.

        Returns a ToolCallResult similar to `call_tool`.
        
        Args:
            proposal: The tool proposal to execute
            user_context: Optional user input context to auto-populate missing arguments
        """
        try:
            # Auto-populate missing required arguments from context
            # For search/vector_search tools, use user_context as query if not provided
            if proposal.tool in {"search_tasks", "vector_search"}:
                if "query" not in proposal.args and user_context:
                    proposal.args["query"] = user_context
                    logger.debug(f"Auto-populated query for {proposal.tool} from user context")

            # Validate proposal against registered tools
            proposal.validate_against_tools(self.tools)

            # Basic safety: by default require explicit confirmation for destructive tools,
            # but allow overriding via environment for local/testing convenience.
            destructive_tools = {"delete_task"}
            allow_destructive = os.getenv("ALLOW_DESTRUCTIVE_PROPOSALS", "true").lower() in {"1", "true", "yes"}
            if proposal.tool in destructive_tools and not proposal.confirm and not allow_destructive:
                return ToolCallResult(
                    tool_name=proposal.tool,
                    success=False,
                    result=None,
                    error=("Destructive operation requires explicit confirmation. "
                           "Resubmit proposal with `confirm=true` to proceed."),
                )

            # Build a ToolCallRequest and reuse existing execution logic
            request = ToolCallRequest(tool_name=proposal.tool, arguments=proposal.args)
            return await self.call_tool(request)

        except ValidationError as ve:
            return ToolCallResult(
                tool_name=proposal.tool if hasattr(proposal, "tool") else "<unknown>",
                success=False,
                result=None,
                error=str(ve),
            )
        except Exception as e:
            return ToolCallResult(
                tool_name=proposal.tool if hasattr(proposal, "tool") else "<unknown>",
                success=False,
                result=None,
                error=str(e),
            )
    
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get tool definition by name."""
        return self.tools.get(name)
    
    def list_tools(self) -> List[ToolDefinition]:
        """List all registered tools."""
        return list(self.tools.values())
    
    def list_resources(self) -> List[Dict[str, Any]]:
        """List all registered resources."""
        return [
            {
                "name": name,
                **content
            }
            for name, content in self.resources.items()
        ]
    
    def list_prompts(self) -> List[Dict[str, Any]]:
        """List all registered prompt templates."""
        return [
            {
                "name": name,
                **content
            }
            for name, content in self.prompts.items()
        ]
    
    def render_prompt(self, name: str, variables: Dict[str, str]) -> Optional[str]:
        """Render a prompt template with variables."""
        prompt = self.prompts.get(name)
        if not prompt:
            return None
        
        template = prompt["template"]
        try:
            return template.format(**variables)
        except KeyError as e:
            logger.error(f"Missing variable in prompt '{name}': {e}")
            return None


# Global MCP server singleton for route access
_mcp_server: MCPServer = None


def get_mcp_server() -> MCPServer:
    """Get the global MCP server instance."""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPServer()
    return _mcp_server


def set_mcp_server(server: MCPServer) -> None:
    """Set the global MCP server instance."""
    global _mcp_server
    _mcp_server = server


class MCPToolRegistry:
    """Registry of standard MCP tools for the task management system."""
    
    @staticmethod
    def create_task_tool() -> Dict[str, Any]:
        """Create task definition for MCP."""
        return {
            "name": "create_task",
            "description": "Create a new task",
            "parameters": [
                {
                    "name": "title",
                    "type": "string",
                    "description": "Task title",
                    "required": True,
                },
                {
                    "name": "description",
                    "type": "string",
                    "description": "Task description",
                    "required": False,
                },
                {
                    "name": "priority",
                    "type": "string",
                    "description": "Task priority",
                    "required": False,
                    "enum": ["low", "medium", "high"],
                },
            ],
        }
    
    @staticmethod
    def update_task_tool() -> Dict[str, Any]:
        """Update task definition for MCP."""
        return {
            "name": "update_task",
            "description": "Update an existing task",
            "parameters": [
                {
                    "name": "task_id",
                    "type": "number",
                    "description": "Task ID",
                    "required": True,
                },
                {
                    "name": "title",
                    "type": "string",
                    "description": "New task title",
                    "required": False,
                },
                {
                    "name": "description",
                    "type": "string",
                    "description": "New task description",
                    "required": False,
                },
            ],
        }
    
    @staticmethod
    def complete_task_tool() -> Dict[str, Any]:
        """Complete task definition for MCP."""
        return {
            "name": "complete_task",
            "description": "Mark an existing task as completed",
            "parameters": [
                {
                    "name": "task_id",
                    "type": "number",
                    "description": "Task ID to mark complete",
                    "required": True,
                },
            ],
        }

    @staticmethod
    def reopen_task_tool() -> Dict[str, Any]:
        """Reopen task definition for MCP."""
        return {
            "name": "reopen_task",
            "description": "Mark an existing task as pending again",
            "parameters": [
                {
                    "name": "task_id",
                    "type": "number",
                    "description": "Task ID to reopen",
                    "required": True,
                },
            ],
        }

    @staticmethod
    def delete_task_tool() -> Dict[str, Any]:
        """Delete task definition for MCP."""
        return {
            "name": "delete_task",
            "description": "Delete an existing task",
            "parameters": [
                {
                    "name": "task_id",
                    "type": "number",
                    "description": "Task ID to delete",
                    "required": True,
                },
            ],
        }
    
    @staticmethod
    def search_tasks_tool() -> Dict[str, Any]:
        """Search tasks definition for MCP."""
        return {
            "name": "search_tasks",
            "description": "Search for tasks by query",
            "parameters": [
                {
                    "name": "query",
                    "type": "string",
                    "description": "Search query",
                    "required": True,
                },
                {
                    "name": "limit",
                    "type": "number",
                    "description": "Maximum results",
                    "required": False,
                },
            ],
        }

    @staticmethod
    def list_tasks_tool() -> Dict[str, Any]:
        """List tasks definition for MCP."""
        return {
            "name": "list_tasks",
            "description": "List tasks with optional completion filtering",
            "parameters": [
                {
                    "name": "limit",
                    "type": "number",
                    "description": "Maximum number of tasks",
                    "required": False,
                },
                {
                    "name": "offset",
                    "type": "number",
                    "description": "Task offset for pagination",
                    "required": False,
                },
                {
                    "name": "completed",
                    "type": "boolean",
                    "description": "Filter tasks by completion status",
                    "required": False,
                },
            ],
        }
    
    @staticmethod
    def vector_search_tool() -> Dict[str, Any]:
        """Vector search definition for MCP."""
        return {
            "name": "vector_search",
            "description": "Semantic search using embeddings",
            "parameters": [
                {
                    "name": "query",
                    "type": "string",
                    "description": "Search query",
                    "required": True,
                },
                {
                    "name": "limit",
                    "type": "number",
                    "description": "Maximum results",
                    "required": False,
                },
                {
                    "name": "threshold",
                    "type": "number",
                    "description": "Similarity threshold (0-1)",
                    "required": False,
                },
            ],
        }
