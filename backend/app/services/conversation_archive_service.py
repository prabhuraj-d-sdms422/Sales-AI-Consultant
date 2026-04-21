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


def render_transcript_txt(*, messages: list[Any], consultant_name: str, client_name: str | None = None) -> str:
    """
    Render a readable plaintext transcript.
    Format is stable so it can be pasted into HubSpot notes or saved as a .txt file.
    """
    client = (client_name or "").strip() or "Client"
    consultant = (consultant_name or "").strip() or "AI Consultant"
    lines: list[str] = []
    lines.append(f"AI Consultant ({consultant})")
    lines.append("")
    for m in messages or []:
        rec = _to_message_record(m)
        t = (rec.get("type") or "").lower()
        content = str(rec.get("content") or "").strip()
        if not content:
            continue
        speaker = client if t == "human" else consultant if t == "ai" else "Other"
        lines.append(f"{speaker}: {content}")
        lines.append("")
    lines.append(f"Client name: {client}")
    return "\n".join(lines).strip() + "\n"


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

    # Also write a plaintext transcript alongside the JSON for easy sharing.
    try:
        # Prefer form-collected name if present; safe fallback to "Client".
        client_name = ""
        try:
            # messages don't include profile; caller can regenerate if needed.
            client_name = ""
        except Exception:
            client_name = ""
        txt = render_transcript_txt(
            messages=messages,
            consultant_name=str(settings.consultant_name),
            client_name=client_name or None,
        )
        (conversations_dir / f"{session_id}.txt").write_text(txt, encoding="utf-8")
    except Exception as e:
        logger.warning("Could not write transcript txt | session=%s | err=%s", session_id, e)
    logger.info(
        "CONVERSATION SAVED | session=%s | messages=%d | file=%s",
        session_id,
        len(messages),
        target_file,
    )
