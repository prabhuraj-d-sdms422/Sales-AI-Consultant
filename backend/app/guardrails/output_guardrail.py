import json
import logging
import os
import re
from datetime import datetime
from functools import lru_cache
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


def _rewrite_capability_claim_tense(text: str) -> tuple[str, dict | None]:
    """
    Use case 1 enforcement:
    Avoid implying completed delivery like "we have built".
    Rewrites those past-tense phrases into future/capability language.
    """
    original = text

    # Keep capitalization for "We ..." vs "we ..."
    text = re.sub(r"\bWe have built\b", "We can build", text)
    text = re.sub(r"\bWe['’]ve built\b", "We can build", text)
    text = re.sub(r"\bwe have built\b", "we can build", text)
    text = re.sub(r"\bwe['’]ve built\b", "we can build", text)
    text = re.sub(r"\bWe built\b", "We can build", text)
    text = re.sub(r"\bwe built\b", "we can build", text)

    text = re.sub(r"\bWe have delivered\b", "We can build", text)
    text = re.sub(r"\bWe['’]ve delivered\b", "We can build", text)
    text = re.sub(r"\bwe have delivered\b", "we can build", text)
    text = re.sub(r"\bwe['’]ve delivered\b", "we can build", text)
    text = re.sub(r"\bWe delivered\b", "We can build", text)
    text = re.sub(r"\bwe delivered\b", "we can build", text)

    if text == original:
        return text, None

    flag = {
        "type": "output",
        "rule": "claim_tense_future_enforcement",
        "action": "rewrite",
        "content": original[:200],
    }
    return text, flag


def _split_sentences(text: str) -> list[str]:
    # Lightweight sentence split; good enough for clamp logic.
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if p and p.strip()]


def _brevity_clamp(
    text: str,
    max_sentences: int = 5,
    max_chars: int = 1200,
    clamp_only_if_over_sentences: int = 7,
    clamp_only_if_over_chars: int = 1400,
) -> tuple[str, dict | None]:
    """
    Shorten long answers into crisp responses without extra LLM calls.

    Strategy:
    - Keep at most `max_sentences`
    - Preserve ONE forward-moving question (prefer the last question sentence)
    - Ensure total length <= `max_chars` (hard cap)
    """
    original = text or ""
    cleaned = " ".join(original.split())
    if not cleaned:
        return original, None

    sentence_count = len(_split_sentences(cleaned))
    # Only clamp when the output is clearly too long. If it's moderately long,
    # prefer returning the full answer over a chopped one.
    if sentence_count <= clamp_only_if_over_sentences and len(cleaned) <= clamp_only_if_over_chars:
        return original, None

    if len(cleaned) <= max_chars and sentence_count <= max_sentences:
        return original, None

    sents = _split_sentences(cleaned)
    if not sents:
        # If we can't split safely, do not risk chopping the output.
        return original, None
        flag = {
            "type": "output",
            "rule": "brevity_clamp",
            "action": "shorten",
            "content": original[:200],
        }
        return shortened, flag

    # Identify the last question sentence (if any)
    question_idx = None
    for i in range(len(sents) - 1, -1, -1):
        if "?" in sents[i]:
            question_idx = i
            break

    kept: list[str] = []
    if question_idx is None:
        kept = sents[:max_sentences]
    else:
        # Keep up to max_sentences-1 leading sentences, plus the question sentence at the end.
        lead = [s for j, s in enumerate(sents) if j != question_idx]
        kept = lead[: max(1, max_sentences - 1)] + [sents[question_idx]]

    # Ensure we don't cut mid-sentence: if too long, drop sentences (prefer dropping non-question sentences).
    shortened = " ".join(kept).strip()
    while len(shortened) > max_chars and len(kept) > 1:
        # If last sentence is a question, preserve it and drop from the front.
        if "?" in kept[-1]:
            kept.pop(0)
        else:
            kept.pop()
        shortened = " ".join(kept).strip()

    # If still too long (e.g., one very long sentence), do NOT cut mid-thought.
    # In those cases, it's better to return the full answer than an ugly fragment.
    if len(shortened) > max_chars:
        return original, None

    # Ensure we don't end on a dangling markdown fragment or clause.
    if shortened and shortened[-1] not in ".?!":
        shortened = shortened.rstrip(" ,;:") + "."

    flag = {
        "type": "output",
        "rule": "brevity_clamp",
        "action": "shorten",
        "content": original[:200],
    }
    return shortened, flag


def _log_guardrail(session_id: str, flag: dict) -> None:
    os.makedirs("data", exist_ok=True)
    entry = {"session_id": session_id, "timestamp": datetime.utcnow().isoformat(), **flag}
    with open(GUARDRAIL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


@lru_cache(maxsize=1)
def _competitor_validator():
    """
    Loaded once from settings.  Returns None when the blocklist is empty
    so we skip validation gracefully.
    """
    from guardrails.hub import CompetitorCheck

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

    updated_response = response
    new_flags: list[dict] = []

    # --- 3. Claim tense enforcement (Use case 1) ---
    updated_response, flag = _rewrite_capability_claim_tense(updated_response)
    if flag is not None:
        new_flags.append(flag)

    # --- 4. Brevity clamp (short, crisp outputs) ---
    updated_response, clamp_flag = _brevity_clamp(updated_response)
    if clamp_flag is not None:
        new_flags.append(clamp_flag)

    if new_flags:
        for f in new_flags:
            _log_guardrail(state["session_id"], f)
        return {
            "output_guardrail_passed": True,
            "current_response": updated_response,
            "guardrail_flags": state.get("guardrail_flags", []) + new_flags,
        }

    return {"output_guardrail_passed": True}
