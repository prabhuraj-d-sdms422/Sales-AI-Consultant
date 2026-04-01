from fastapi import APIRouter, HTTPException

from app.config.settings import settings
from app.models.schemas import (
    CreateSessionResponse,
    EndSessionRequest,
    OkResponse,
    SaveProfileRequest,
    SessionConfigResponse,
    SessionResponse,
)
from app.services.lead_delivery_service import end_session_and_maybe_deliver
from app.services.session_service import create_session, load_state, save_state

router = APIRouter(tags=["session"])


@router.post("/create", response_model=CreateSessionResponse)
async def create_new_session():
    session_id = await create_session()
    return CreateSessionResponse(
        session_id=session_id,
        inactivity_prompt_minutes=int(settings.inactivity_prompt_minutes),
        inactivity_end_minutes=int(settings.inactivity_end_minutes),
    )


@router.get("/config", response_model=SessionConfigResponse)
async def get_session_config():
    return SessionConfigResponse(
        inactivity_prompt_minutes=int(settings.inactivity_prompt_minutes),
        inactivity_end_minutes=int(settings.inactivity_end_minutes),
    )


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


@router.post("/end", response_model=OkResponse)
async def end_session(payload: EndSessionRequest):
    state = await load_state(payload.session_id)
    if not state:
        # Idempotent end: if session is gone, treat as ok.
        return OkResponse(status="ended")

    updated = await end_session_and_maybe_deliver(state, reason="api_end")
    await save_state(payload.session_id, updated)
    return OkResponse(status="ended")


@router.post("/profile", response_model=OkResponse)
async def save_profile(payload: SaveProfileRequest):
    state = await load_state(payload.session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    profile = dict(state.get("client_profile") or {})
    for k in ("name", "email", "phone"):
        v = getattr(payload, k, None)
        if v is None:
            continue
        v = str(v).strip()
        if not v:
            continue
        # Never overwrite a non-empty existing value.
        if not (profile.get(k) or "").strip():
            profile[k] = v

    state["client_profile"] = profile
    await save_state(payload.session_id, state)
    return OkResponse(status="saved")
