import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, message_to_dict

from app.config.settings import settings

logger = logging.getLogger(__name__)


def _to_message_record(message: Any) -> dict:
    if isinstance(message, BaseMessage):
        serialized = message_to_dict(message)
        msg_type = serialized.get("type", "unknown")
        content = serialized.get("data", {}).get("content", "")
        return {"type": msg_type, "content": content, "raw": serialized}

    if isinstance(message, dict):
        msg_type = message.get("type", "unknown")
        content = message.get("data", {}).get("content", message.get("content", ""))
        return {"type": msg_type, "content": content, "raw": message}

    return {"type": "unknown", "content": str(message), "raw": {"value": str(message)}}


async def save_session_conversation(
    session_id: str,
    messages: list[Any],
    *,
    token_usage: dict | None = None,
) -> None:
    root_path = Path(settings.repo_root)
    conversations_dir = root_path / "backend" / "data" / "Conversations"
    conversations_dir.mkdir(parents=True, exist_ok=True)

    payload: dict = {
        "session_id": session_id,
        "updated_at": datetime.utcnow().isoformat(),
        "message_count": len(messages),
        "messages": [_to_message_record(m) for m in messages],
    }
    if token_usage:
        payload["token_usage"] = token_usage

    target_file = conversations_dir / f"{session_id}.json"
    target_file.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    logger.info(
        "CONVERSATION SAVED | session=%s | messages=%d | file=%s",
        session_id,
        len(messages),
        target_file,
    )
