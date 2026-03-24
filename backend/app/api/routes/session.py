from fastapi import APIRouter, HTTPException

from app.models.schemas import CreateSessionResponse, SessionResponse
from app.services.session_service import create_session, load_state

router = APIRouter(tags=["session"])


@router.post("/create", response_model=CreateSessionResponse)
async def create_new_session():
    session_id = await create_session()
    return CreateSessionResponse(session_id=session_id)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    state = await load_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(
        session_id=session_id,
        created_at=state.get("created_at"),
        last_active=state.get("last_active"),
        conversation_stage=state.get("conversation_stage"),
    )
