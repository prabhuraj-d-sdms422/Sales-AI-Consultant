import json
import uuid
from datetime import datetime

from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict

from app.config.settings import settings
from app.db.redis_client import get_redis
from app.utils.conversation_stages import ConversationStage


def _messages_to_serializable(messages: list) -> list:
    out: list = []
    for m in messages:
        if isinstance(m, BaseMessage):
            out.append(message_to_dict(m))
        elif isinstance(m, dict):
            out.append(m)
        else:
            out.append(m)
    return out


def _messages_from_serializable(data: list) -> list:
    if not data:
        return []
    try:
        return messages_from_dict(data)
    except Exception:
        from langchain_core.messages import AIMessage, HumanMessage

        rebuilt = []
        for item in data:
            if isinstance(item, dict) and item.get("type") == "human":
                rebuilt.append(HumanMessage(content=item.get("data", {}).get("content", "")))
            elif isinstance(item, dict) and item.get("type") == "ai":
                rebuilt.append(AIMessage(content=item.get("data", {}).get("content", "")))
        return rebuilt


def _serialize_state(state: dict) -> dict:
    s = dict(state)
    msgs = state.get("messages") or []
    s["messages"] = _messages_to_serializable(msgs)
    return s


def _deserialize_state(data: dict) -> dict:
    s = dict(data)
    s["messages"] = _messages_from_serializable(data.get("messages") or [])
    return s


async def create_session() -> str:
    session_id = str(uuid.uuid4())
    initial_state = {
        "session_id": session_id,
        "created_at": datetime.utcnow().isoformat(),
        "last_active": datetime.utcnow().isoformat(),
        "messages": [],
        "client_profile": {},
        "conversation_stage": ConversationStage.GREETING.value,
        "current_intent": "",
        "intent_confidence": 0.0,
        "agent_mode": "CONVERSATIONAL",
        "current_agent": "discovery",
        "current_response": "",
        "solutions_discussed": [],
        "objections_raised": [],
        "input_guardrail_passed": True,
        "output_guardrail_passed": True,
        "guardrail_flags": [],
        "lead_persisted": False,
        "lead_delivered": False,
        "lead_temperature": "cold",
        "escalation_requested": False,
        "escalation_triggered": False,
        "should_stream": True,
        "conversation_ended": False,
        # Rolling summary / memory (optional)
        "conversation_summary": "",
        "summary_turns_since_update": 0,
        # Website research (optional)
        "website_research": None,
        "website_sources": [],
        "website_last_fetched_at": "",
    }
    await save_state(session_id, initial_state)
    return session_id


async def save_state(session_id: str, state: dict) -> None:
    redis = await get_redis()
    payload = _serialize_state(state)
    payload["last_active"] = datetime.utcnow().isoformat()
    await redis.setex(
        f"session:{session_id}",
        settings.redis_ttl_seconds,
        json.dumps(payload, default=str),
    )


async def load_state(session_id: str) -> dict | None:
    redis = await get_redis()
    data = await redis.get(f"session:{session_id}")
    if not data:
        return None
    return _deserialize_state(json.loads(data))
