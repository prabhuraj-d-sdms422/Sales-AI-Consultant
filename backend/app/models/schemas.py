from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


class EndSessionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


class SaveProfileRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    name: str | None = None
    email: str | None = None
    phone: str | None = None


class OkResponse(BaseModel):
    status: str = "ok"


class CreateSessionResponse(BaseModel):
    session_id: str
    inactivity_prompt_minutes: int
    inactivity_end_minutes: int


class SessionResponse(BaseModel):
    session_id: str
    created_at: str | None = None
    last_active: str | None = None
    conversation_stage: str | None = None


class SessionConfigResponse(BaseModel):
    inactivity_prompt_minutes: int
    inactivity_end_minutes: int
