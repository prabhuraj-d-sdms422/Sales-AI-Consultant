import json
import logging
import os
from datetime import datetime
from functools import lru_cache

from app.models.state import ConversationState

logger = logging.getLogger(__name__)

GUARDRAIL_LOG = "data/guardrail_log.jsonl"

INPUT_BLOCKED_RESPONSE = (
    "I'm here to help with business and technology requirements. "
    "Let's keep our conversation professional. How can I help you today?"
)


def _log_guardrail(session_id: str, flag: dict) -> None:
    os.makedirs("data", exist_ok=True)
    entry = {"session_id": session_id, "timestamp": datetime.utcnow().isoformat(), **flag}
    with open(GUARDRAIL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


@lru_cache(maxsize=1)
def _toxic_validator():
    """Loaded once; Albert-based sentence-level toxicity classifier (runs on CPU)."""
    from guardrails.hub import ToxicLanguage

    return ToxicLanguage(threshold=0.7, validation_method="sentence", device="cpu")


@lru_cache(maxsize=1)
def _jailbreak_validator():
    """Loaded once; BERT-based prompt-saturation / jailbreak detector (runs on CPU)."""
    from guardrails.hub import DetectJailbreak

    return DetectJailbreak(threshold=0.81, device="cpu")


def _last_user_message(state: ConversationState) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, dict) and msg.get("role") == "user":
            return msg.get("content", "").strip()
    return ""


async def input_guardrail_node(state: ConversationState) -> dict:
    """
    Semantic input guardrail using Guardrails-AI validators (zero extra LLM calls).

    - ToxicLanguage  : blocks abusive / harmful user input (Albert, local CPU).
    - DetectJailbreak: blocks prompt-injection / jailbreak attempts (BERT, local CPU).

    Manipulation and off-topic classification is handled by the orchestrator piggyback,
    so we do NOT duplicate that check here.
    """
    user_text = _last_user_message(state)
    if not user_text:
        return {"input_guardrail_passed": True}

    # --- Toxic Language check ---
    try:
        result = _toxic_validator().validate(user_text, {})
        if result.outcome == "fail":
            flag = {"type": "input", "rule": "toxic_language", "content": user_text[:200]}
            _log_guardrail(state["session_id"], flag)
            logger.warning("Input blocked [toxic_language] session=%s", state["session_id"])
            return {
                "input_guardrail_passed": False,
                "current_response": INPUT_BLOCKED_RESPONSE,
                "guardrail_flags": state.get("guardrail_flags", []) + [flag],
            }
    except Exception:
        logger.exception("ToxicLanguage validator error — passing message through")

    # --- Jailbreak / Prompt-injection check ---
    try:
        result = _jailbreak_validator().validate(user_text, {})
        if result.outcome == "fail":
            flag = {"type": "input", "rule": "detect_jailbreak", "content": user_text[:200]}
            _log_guardrail(state["session_id"], flag)
            logger.warning("Input blocked [detect_jailbreak] session=%s", state["session_id"])
            return {
                "input_guardrail_passed": False,
                "current_response": INPUT_BLOCKED_RESPONSE,
                "guardrail_flags": state.get("guardrail_flags", []) + [flag],
            }
    except Exception:
        logger.exception("DetectJailbreak validator error — passing message through")

    return {"input_guardrail_passed": True}
