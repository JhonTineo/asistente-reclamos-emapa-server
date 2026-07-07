from pydantic import BaseModel


class ToolExecutionInput(BaseModel):
    tool_name: str
    params: dict


class ToolExecutionResult(BaseModel):
    tool_name: str
    success: bool
    data: str | None = None
    error: str | None = None
