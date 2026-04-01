"""Lead enrichment.

Goal: capture ALL problems + ALL solutions (and key metrics) from a transcript so the
sales team sees the complete picture even when clients mention multiple issues.

This is best-effort and non-blocking.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.models.state import ConversationState

logger = logging.getLogger(__name__)


_ENRICH_PROMPT = """You are enriching a sales lead record from a chat transcript.

Return JSON only with these keys:
{
  "all_problems": ["<problem 1>", "<problem 2>", "..."],
  "all_solutions": ["<solution 1>", "<solution 2>", "..."],
  "key_metrics": ["<metric 1>", "<metric 2>", "..."],
  "client_context": "<1-2 sentences. Plain English.>"
}

Rules:
- Be faithful to the transcript; do not invent facts.
- Capture multiple distinct problems if present (e.g., user says "also..." or changes topic).
- "all_solutions" should include what the assistant proposed (products/systems/approaches).
- "key_metrics" should include concrete numbers and facts (e.g., denial %, bed count, volumes).
- Keep items concise; avoid duplicates.
"""


def _to_text(msg: Any) -> str:
    c = getattr(msg, "content", msg)
    if isinstance(c, list):
        return "".join(str(x) for x in c)
    return str(c or "")


def _format_recent_transcript(messages: list, limit: int = 40) -> str:
    # Use a longer window because multi-problem conversations may span more turns.
    recent = list(messages or [])[-limit:]
    lines: list[str] = []
    for m in recent:
        t = getattr(m, "type", None) or getattr(m, "_type", None)
        role = "user" if t in ("human", "user") else "assistant" if t in ("ai", "assistant") else "other"
        txt = _to_text(m).strip()
        if not txt:
            continue
        lines.append(f"{role}: {txt}")
    return "\n".join(lines).strip()


def _parse_json_obj(text: str) -> dict[str, Any]:
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            obj = json.loads(text[start:end])
            if isinstance(obj, dict):
                return obj
    except Exception:
        pass
    return {}


def _as_list_of_strings(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        out: list[str] = []
        for x in v:
            s = str(x or "").strip()
            if s:
                out.append(s)
        return out
    s = str(v or "").strip()
    return [s] if s else []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items or []:
        k = " ".join(str(it).strip().lower().split())
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(str(it).strip())
    return out


async def enrich_lead_from_conversation(state: ConversationState) -> dict[str, Any]:
    """Return best-effort structured insights extracted from recent conversation."""
    transcript = _format_recent_transcript(state.get("messages") or [])
    if not transcript:
        return {"all_problems": [], "all_solutions": [], "key_metrics": [], "client_context": ""}

    llm = get_llm(streaming=False)
    resp = await llm.ainvoke(
        [
            SystemMessage(content=_ENRICH_PROMPT),
            HumanMessage(content=transcript),
        ]
    )
    content = _to_text(resp).strip()
    obj = _parse_json_obj(content)

    all_problems = _dedupe(_as_list_of_strings(obj.get("all_problems")))
    all_solutions = _dedupe(_as_list_of_strings(obj.get("all_solutions")))
    key_metrics = _dedupe(_as_list_of_strings(obj.get("key_metrics")))
    client_context = str(obj.get("client_context") or "").strip()
    if len(client_context) > 600:
        client_context = client_context[:600].rstrip()

    return cast(
        dict[str, Any],
        {
            "all_problems": all_problems,
            "all_solutions": all_solutions,
            "key_metrics": key_metrics,
            "client_context": client_context,
        },
    )


async def enrich_lead_from_conversation_safe(state: ConversationState) -> dict[str, Any]:
    try:
        return await enrich_lead_from_conversation(state)
    except Exception as e:
        logger.exception("Lead enrichment failed: %s", e)
        return {"all_problems": [], "all_solutions": [], "key_metrics": [], "client_context": ""}
