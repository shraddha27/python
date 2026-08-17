from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ValidationError


class Proposal(BaseModel):
    """Structured proposal the LLM must return when suggesting actions.

    Fields:
      - agent: optional agent id that should handle the operation
      - tool: name of the MCP tool to call
      - args: dict of arguments for the tool
      - intent: freeform intent label (for audit / confirmation rules)
      - confirm: whether the user already confirmed destructive action
      - user_context: optional user input/query to auto-populate missing required args
    """

    agent: Optional[str] = None
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    intent: Optional[str] = None
    confirm: bool = False
    user_context: Optional[str] = None

    def validate_against_tools(self, tools: Dict[str, Any]) -> None:
        """Validate proposal against registered tool definitions.

        Raises ValueError when invalid (to be caught as validation error).
        """
        if self.tool not in tools:
            raise ValueError(f"Tool '{self.tool}' is not registered")

        tool_def = tools[self.tool]
        # tool_def is expected to be a ToolDefinition-like object or dict
        params = getattr(tool_def, "parameters", None) or tool_def.get("parameters", [])
        missing: List[str] = []
        for p in params:
            name = p.get("name") if isinstance(p, dict) else getattr(p, "name", None)
            required = p.get("required", False) if isinstance(p, dict) else getattr(p, "required", False)
            if required and name not in self.args:
                missing.append(name)

        if missing:
            raise ValueError(f"Missing required arguments: {', '.join(missing)}")
