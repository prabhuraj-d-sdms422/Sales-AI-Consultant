import logging
from datetime import datetime
from pathlib import Path

from app.config.settings import settings
from app.db.redis_client import get_redis
from app.models.state import ConversationState
from app.services.conversation_archive_service import save_session_conversation
from app.services.email_service import notify_sales_lead_captured, save_lead_locally
from app.services.hubspot_service import sync_lead_to_hubspot_safe
from app.services.lead_enrichment_service import enrich_lead_from_conversation_safe
from app.services.sheets_service import append_lead_google_sheets, append_lead_locally

CONVERSATIONS_DIR = Path(settings.repo_root) / "backend" / "data" / "Conversations"

logger = logging.getLogger(__name__)

# Redis lock TTL in seconds — long enough to cover delivery, short enough to not block retries.
_DELIVERY_LOCK_TTL = 60


def has_minimum_delivery_data(state: ConversationState) -> bool:
    profile = dict(state.get("client_profile") or {})
    return bool((profile.get("email") or "").strip() or (profile.get("phone") or "").strip())


def _norm(s: object) -> str:
    return " ".join(str(s or "").strip().split())


def _append_unique(items: list[str] | None, new_item: object) -> list[str]:
    out = list(items or [])
    v = _norm(new_item)
    if not v:
        return out
    v_l = v.lower()
    for e in out:
        if _norm(e).lower() == v_l:
            return out
    out.append(v)
    return out


async def _acquire_delivery_lock(session_id: str) -> bool:
    """
    Atomic Redis lock to prevent race-condition double-delivery.
    Returns True if lock acquired (safe to proceed), False if another delivery is in progress.
    """
    try:
        redis = await get_redis()
        lock_key = f"delivery_lock:{session_id}"
        # SET NX EX — set only if not exists, with TTL. Returns True when key was set.
        acquired = await redis.set(lock_key, "1", nx=True, ex=_DELIVERY_LOCK_TTL)
        return bool(acquired)
    except Exception as e:
        logger.warning("Could not acquire delivery lock for session=%s: %s", session_id, e)
        # Fail open so delivery still works if Redis has a hiccup.
        return True


async def trigger_lead_delivery(state: ConversationState) -> ConversationState:
    """
    Persist lead: enrich → HubSpot → JSON/Excel/Sheets → email.
    Returns updated state with all enrichment fields merged in.
    """
    session_id = str(state.get("session_id") or "")
    delivery_state: ConversationState = dict(state)

    # ── Conversation viewer URL ────────────────────────────────────────────
    base_url = settings.app_base_url.rstrip("/")
    conversation_viewer_url = f"{base_url}/conversation/{session_id}"
    delivery_state["conversation_viewer_url"] = conversation_viewer_url

    # Ensure the conversation JSON file exists for the viewer, even when
    # SAVE_CONVERSATIONS_ENABLED is False (the file is always needed for links).
    try:
        conv_file = CONVERSATIONS_DIR / f"{session_id}.json"
        if not conv_file.exists():
            messages = delivery_state.get("messages") or []
            if messages:
                await save_session_conversation(
                    session_id,
                    messages,
                    token_usage=delivery_state.get("session_token_usage"),
                )
    except Exception as e:
        logger.warning("Could not save conversation archive for viewer | session=%s | err=%s", session_id, e)

    # ── Enrichment ────────────────────────────────────────────────
    enrichment = await enrich_lead_from_conversation_safe(delivery_state)
    # Store the full insights so email/HubSpot note always has them.
    delivery_state["conversation_insights"] = enrichment

    profile = dict(delivery_state.get("client_profile") or {})
    all_problems: list[str] = list(enrichment.get("all_problems") or [])
    all_solutions: list[str] = list(enrichment.get("all_solutions") or [])

    # Populate backward-compatible single problem field (first problem from enrichment).
    if all_problems and not (profile.get("problem_understood") or profile.get("problem_raw")):
        profile["problem_understood"] = str(all_problems[0])
    delivery_state["client_profile"] = profile

    # Accumulate all problems discovered across the session.
    problems_identified = list(delivery_state.get("problems_identified") or [])
    for p in all_problems:
        problems_identified = _append_unique(problems_identified, p)
    delivery_state["problems_identified"] = problems_identified

    # Ensure solutions_discussed is populated from enrichment when not set by agents.
    existing_solutions = list(delivery_state.get("solutions_discussed") or [])
    if not existing_solutions and all_solutions:
        delivery_state["solutions_discussed"] = [_norm(x) for x in all_solutions if _norm(x)]

    # ── External sinks ────────────────────────────────────────────
    hubspot_url = await sync_lead_to_hubspot_safe(delivery_state) or ""
    if hubspot_url:
        delivery_state["hubspot_contact_url"] = hubspot_url

    # Local persistence is the canonical record — abort further sinks only on local failure.
    try:
        await save_lead_locally(delivery_state)
    except Exception as e:
        logger.error("save_lead_locally failed | session=%s | err=%s", session_id, e)
        return delivery_state

    try:
        await append_lead_locally(delivery_state)
    except Exception as e:
        logger.error("append_lead_locally (Excel) failed | session=%s | err=%s", session_id, e)

    try:
        await append_lead_google_sheets(delivery_state)
    except Exception as e:
        logger.error("append_lead_google_sheets failed | session=%s | err=%s", session_id, e)

    try:
        await notify_sales_lead_captured(delivery_state)
    except Exception as e:
        logger.error("notify_sales_lead_captured failed | session=%s | err=%s", session_id, e)

    return delivery_state


async def deliver_now_if_possible(state: ConversationState, *, reason: str) -> ConversationState:
    """
    Deliver lead without ending the conversation (used for real-time escalation).
    Delivery happens at most once and only if minimum delivery data exists.
    """
    session_id = str(state.get("session_id") or "")
    updated: ConversationState = dict(state)

    if bool(updated.get("lead_delivered")):
        logger.info("REAL-TIME DELIVERY skipped (already delivered) | session=%s | reason=%s", session_id, reason)
        return updated
    if not has_minimum_delivery_data(updated):
        logger.info("REAL-TIME DELIVERY skipped (missing email/phone) | session=%s | reason=%s", session_id, reason)
        return updated

    if not await _acquire_delivery_lock(session_id):
        logger.info("REAL-TIME DELIVERY skipped (lock held) | session=%s | reason=%s", session_id, reason)
        return updated

    logger.info("REAL-TIME LEAD DELIVERY | session=%s | reason=%s", session_id, reason)
    delivered_state = await trigger_lead_delivery(updated)
    delivered_state["lead_delivered"] = True
    return delivered_state


async def end_session_and_maybe_deliver(state: ConversationState, *, reason: str) -> ConversationState:
    """
    Mark session ended and deliver at most once.
    Uses a Redis atomic lock to prevent concurrent duplicate deliveries.
    Delivery skipped when email/phone are both missing.
    """
    session_id = str(state.get("session_id") or "")

    # Always mark ended, regardless of delivery outcome.
    updated: ConversationState = dict(state)
    updated["conversation_ended"] = True
    updated["conversation_stage"] = updated.get("conversation_stage") or "CLOSED"

    if bool(state.get("lead_delivered")):
        logger.info("SESSION END skipped delivery (already delivered) | session=%s | reason=%s", session_id, reason)
        return updated

    if not has_minimum_delivery_data(updated):
        logger.info("SESSION ENDED (no delivery: missing email/phone) | session=%s | reason=%s", session_id, reason)
        return updated

    # Atomic lock prevents race-condition when two /session/end requests arrive simultaneously.
    if not await _acquire_delivery_lock(session_id):
        logger.info("SESSION END skipped delivery (lock held — concurrent request) | session=%s | reason=%s", session_id, reason)
        return updated

    logger.info("SESSION END → LEAD DELIVERY | session=%s | reason=%s", session_id, reason)
    delivered_state = await trigger_lead_delivery(updated)
    delivered_state["lead_delivered"] = True
    delivered_state["conversation_ended"] = True
    delivered_state["ended_at"] = datetime.utcnow().isoformat()
    return delivered_state

