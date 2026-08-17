from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class RoleSchema(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class UserSchema(BaseModel):
    id: int
    email: str
    name: str
    roles: List[RoleSchema] = []

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: Optional[str] = None
    token_type: str
    user: UserSchema


class ApiResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None
    message: Optional[str] = None
    errors: Optional[dict] = None
    pagination: Optional[dict] = None


class GoogleLoginRequest(BaseModel):
    id_token: str


class TaskBase(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = Field("", max_length=1000)

    @validator("title")
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be empty.")
        return value.strip()

    @validator("description")
    def trim_description(cls, value: Optional[str]) -> str:
        return value.strip() if value else ""


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    completed: Optional[bool] = None

    @validator("title")
    def title_must_not_be_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("Title cannot be empty.")
        return value.strip() if value is not None else None

    @validator("description")
    def trim_description(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None

    class Config:
        extra = "ignore"


class BulkUpdateRequest(BaseModel):
    task_ids: List[int]
    completed: bool


class BulkCreateRequest(BaseModel):
    tasks: List[TaskCreate]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)


class SearchResult(BaseModel):
    id: int
    title: str
    content: str
    similarity_score: float


class IndexDocumentsRequest(BaseModel):
    task_ids: Optional[List[int]] = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    use_context: bool = Field(True, description="Whether to retrieve context for the query")
    use_tools: bool = Field(True, description="Whether to enable tool calling")


class ChatResponse(BaseModel):
    message: str
    context: Optional[List[SearchResult]]
    tool_calls: Optional[List[dict]]
    response: str


class WorkflowExecuteRequest(BaseModel):
    input: str = Field(..., min_length=1, max_length=2000, description="User input/request")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional context")
