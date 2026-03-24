import json
import logging
import os
import re
from datetime import datetime
from functools import lru_cache
from typing import Optional

from guardrails_grhub_competitor_check import CompetitorCheck

from app.config.settings import settings
from app.models.state import ConversationState

logger = logging.getLogger(__name__)

GUARDRAIL_LOG = "data/guardrail_log.jsonl"

# ---------------------------------------------------------------------------
# Currency / specific-price regex  (Stage 1 — zero false positive risk)
# We keep regex here because every match is a clear policy violation (quoting
# prices is explicitly forbidden in the sales playbook).
# ---------------------------------------------------------------------------
_CURRENCY_PATTERNS = [
    re.compile(r"\b\d[\d,]*\.?\d*\s*(₹|\$|usd|inr|rs\.?|rupees?|dollars?)\b", re.I),
    re.compile(r"(?<!\w)(₹|\$|rs\.?|rupees?)\s*\d[\d,]*", re.I),
    re.compile(r"\b\d+\s*(lakh|lac|crore|crores)\b", re.I),
]

SAFE_FALLBACK = (
    "I'd be happy to walk you through how we approach this at Stark Digital — "
    "without going into figures here. What matters most for your situation right now?"
)


def _log_guardrail(session_id: str, flag: dict) -> None:
    os.makedirs("data", exist_ok=True)
    entry = {"session_id": session_id, "timestamp": datetime.utcnow().isoformat(), **flag}
    with open(GUARDRAIL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


@lru_cache(maxsize=1)
def _competitor_validator() -> Optional[CompetitorCheck]:
    """
    Loaded once from settings.  Returns None when the blocklist is empty
    so we skip validation gracefully.
    """
    names = [x.strip() for x in (settings.competitor_names_blocklist or "").split(",") if x.strip()]
    if not names:
        return None
    return CompetitorCheck(competitors=names)


async def output_guardrail_node(state: ConversationState) -> dict:
    """
    Output guardrail — two checks, zero extra LLM calls:

    1. Currency / price regex  : any specific figure triggers safe fallback.
    2. CompetitorCheck (Guardrails-AI): NLP-based competitor name detection
       using the blocklist from settings.COMPETITOR_NAMES_BLOCKLIST.
    """
    response = state.get("current_response") or ""
    if not response.strip():
        return {"output_guardrail_passed": True}

    # --- 1. Currency / price check ---
    for pat in _CURRENCY_PATTERNS:
        if pat.search(response):
            flag = {
                "type": "output",
                "rule": "price_or_currency",
                "action": "substitute",
                "content": response[:200],
            }
            _log_guardrail(state["session_id"], flag)
            logger.warning("Output blocked [price_or_currency] session=%s", state["session_id"])
            return {
                "output_guardrail_passed": False,
                "current_response": SAFE_FALLBACK,
                "guardrail_flags": state.get("guardrail_flags", []) + [flag],
            }

    # --- 2. Competitor mention check (Guardrails-AI CompetitorCheck) ---
    validator = _competitor_validator()
    if validator is not None:
        try:
            result = validator.validate(response, {})
            if result.outcome == "fail":
                flag = {
                    "type": "output",
                    "rule": "competitor_mention",
                    "action": "substitute",
                    "content": response[:200],
                }
                _log_guardrail(state["session_id"], flag)
                logger.warning("Output blocked [competitor_mention] session=%s", state["session_id"])
                return {
                    "output_guardrail_passed": False,
                    "current_response": SAFE_FALLBACK,
                    "guardrail_flags": state.get("guardrail_flags", []) + [flag],
                }
        except Exception:
            logger.exception("CompetitorCheck validator error — passing response through")

    return {"output_guardrail_passed": True}
