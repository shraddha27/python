"""
FastAPI routes for MCP (Model Context Protocol) endpoints.
Exposes MCP tools, resources, and prompts as REST API.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from .mcp_server import MCPServer, ToolCallRequest, ToolCallResult, ToolDefinition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])

from .mcp_server import get_mcp_server, set_mcp_server
from .llm_proposal import Proposal
from .mistral_client import chat_with_tools
import json

# Note: global MCP server instance is stored in backend_fastapi.mcp_server
# Routes import the shared `get_mcp_server` and `set_mcp_server` helpers from there.


# Response models
class ToolListResponse(BaseModel):
    """Response for listing tools."""
    tools: List[Dict[str, Any]]
    count: int


class ResourceListResponse(BaseModel):
    """Response for listing resources."""
    resources: List[Dict[str, Any]]
    count: int


class PromptListResponse(BaseModel):
    """Response for listing prompts."""
    prompts: List[Dict[str, Any]]
    count: int


class ToolCallResponse(BaseModel):
    """Response for tool call."""
    tool_name: str
    success: bool
    result: Any
    error: Optional[str] = None
    assistant_response: Optional[str] = None


@router.get("/tools", response_model=ToolListResponse)
async def list_tools(mcp_server: MCPServer = Depends(get_mcp_server)):
    """List all available MCP tools."""
    tools = mcp_server.list_tools()
    return ToolListResponse(
        tools=[t.dict() for t in tools],
        count=len(tools),
    )


@router.get("/tools/{tool_name}")
async def get_tool(tool_name: str, mcp_server: MCPServer = Depends(get_mcp_server)):
    """Get a specific tool definition."""
    tool = mcp_server.get_tool(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    return tool.dict()


@router.post("/tools/call", response_model=ToolCallResponse)
async def call_tool(
    request: ToolCallRequest,
    mcp_server: MCPServer = Depends(get_mcp_server),
    natural: bool = False,
    user_message: Optional[str] = None,
):
    """Call an MCP tool. If `natural=true` is passed as a query param, also
    synthesize a natural-language assistant response based on the tool output.
    """
    try:
        result = await mcp_server.call_tool(request)
        if not result.success:
            # Return 400 for known tool errors (e.g., validation or handler returned an error)
            raise HTTPException(status_code=400, detail=result.error)

        assistant_text = None
        if natural:
            # Prepare tool result text for the assistant
            try:
                tool_result_text = json.dumps(result.result, default=str, ensure_ascii=False)
            except Exception:
                tool_result_text = str(result.result)

            prompt = user_message or f"Please summarize the results of tool {result.tool_name} and respond to the user."
            try:
                assistant_text = await chat_with_tools(user_message=prompt, context=None, tool_results=tool_result_text, force_natural=True)
            except Exception:
                assistant_text = None

        return ToolCallResponse(
            tool_name=result.tool_name,
            success=result.success,
            result=result.result,
            error=result.error,
            assistant_response=assistant_text,
        )
    except HTTPException:
        # Re-raise HTTPExceptions untouched
        raise
    except Exception as e:
        import traceback as _tb
        tb = _tb.format_exc()
        logger.exception("Unhandled exception in /api/mcp/tools/call: %s", e)
        # Surface traceback in response to help debugging in development
        raise HTTPException(status_code=500, detail=f"Internal error: {e}\n{tb}")


@router.post("/tools/propose", response_model=ToolCallResponse)
async def propose_tool(
    proposal: Proposal,
    mcp_server: MCPServer = Depends(get_mcp_server),
):
    """Accept a structured LLM proposal, validate it, and execute if allowed."""
    user_context = proposal.user_context or None
    result = await mcp_server.call_proposed_tool(proposal, user_context=user_context)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return ToolCallResponse(tool_name=result.tool_name, success=result.success, result=result.result)


@router.post("/tools/call_natural")
async def call_tool_natural(
    body: Dict[str, Any],
    mcp_server: MCPServer = Depends(get_mcp_server),
):
    """Call an MCP tool, then ask the assistant to convert the tool result into natural language.

    Body should include `tool_name`, `arguments` (optional), and optional `user_message` to guide the assistant.
    """
    tool_name = body.get("tool_name")
    arguments = body.get("arguments") or {}
    user_message = body.get("user_message") or f"Here are the results from tool {tool_name}. Please summarize and respond to the user."

    if not tool_name:
        raise HTTPException(status_code=400, detail="tool_name is required")

    request = ToolCallRequest(tool_name=tool_name, arguments=arguments)
    result = await mcp_server.call_tool(request)

    # Prepare tool results text for the assistant
    try:
        tool_result_text = json.dumps(result.result, default=str, ensure_ascii=False)
    except Exception:
        tool_result_text = str(result.result)

    # Ask the assistant to generate a natural-language response using tool results
    try:
        assistant_text = await chat_with_tools(user_message=user_message, context=None, tool_results=tool_result_text, force_natural=True)
    except Exception:
        assistant_text = None

    return {
        "tool_name": result.tool_name,
        "success": result.success,
        "result": result.result,
        "error": result.error,
        "assistant_response": assistant_text,
    }


@router.get("/resources", response_model=ResourceListResponse)
async def list_resources(mcp_server: MCPServer = Depends(get_mcp_server)):
    """List all available MCP resources."""
    resources = mcp_server.list_resources()
    return ResourceListResponse(
        resources=resources,
        count=len(resources),
    )


@router.get("/resources/{resource_name}")
async def get_resource(
    resource_name: str,
    mcp_server: MCPServer = Depends(get_mcp_server),
):
    """Get a specific resource."""
    resources = mcp_server.list_resources()
    for resource in resources:
        if resource.get("name") == resource_name:
            return resource
    raise HTTPException(status_code=404, detail=f"Resource '{resource_name}' not found")


@router.get("/prompts", response_model=PromptListResponse)
async def list_prompts(mcp_server: MCPServer = Depends(get_mcp_server)):
    """List all available MCP prompt templates."""
    prompts = mcp_server.list_prompts()
    return PromptListResponse(
        prompts=prompts,
        count=len(prompts),
    )


@router.get("/prompts/{prompt_name}")
async def get_prompt(
    prompt_name: str,
    mcp_server: MCPServer = Depends(get_mcp_server),
):
    """Get a specific prompt template."""
    prompts = mcp_server.list_prompts()
    for prompt in prompts:
        if prompt.get("name") == prompt_name:
            return prompt
    raise HTTPException(status_code=404, detail=f"Prompt '{prompt_name}' not found")


class RenderPromptRequest(BaseModel):
    """Request to render a prompt template."""
    variables: Dict[str, str]


@router.post("/prompts/{prompt_name}/render")
async def render_prompt(
    prompt_name: str,
    request: RenderPromptRequest,
    mcp_server: MCPServer = Depends(get_mcp_server),
):
    """Render a prompt template with variables."""
    rendered = mcp_server.render_prompt(prompt_name, request.variables)
    if rendered is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{prompt_name}' not found")
    return {"prompt": prompt_name, "rendered": rendered}


@router.get("/status")
async def mcp_status(mcp_server: MCPServer = Depends(get_mcp_server)):
    """Get MCP server status."""
    return {
        "status": "running",
        "tools_count": len(mcp_server.list_tools()),
        "resources_count": len(mcp_server.list_resources()),
        "prompts_count": len(mcp_server.list_prompts()),
    }
