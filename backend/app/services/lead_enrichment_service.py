"""Lead enrichment.

Goal: ensure we always capture a short problem + solutions summary even if routing/labels vary.
We intentionally keep this best-effort and non-blocking.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.models.state import ConversationState

logger = logging.getLogger(__name__)


_ENRICH_PROMPT = """You are enriching a sales lead record from a chat transcript.

Return JSON only with these keys:
{{
  "problem_summary": "1 short sentence, plain English. Empty string if unknown.",
  "solutions_summary": "1 short sentence describing what solution(s) were discussed/proposed. Empty string if none."
}}

Rules:
- Be faithful to the transcript; do not invent facts.
- Keep each field <= 160 characters.
"""


def _to_text(msg: Any) -> str:
    c = getattr(msg, "content", msg)
    if isinstance(c, list):
        return "".join(str(x) for x in c)
    return str(c or "")


def _format_recent_transcript(messages: list, limit: int = 16) -> str:
    # We only need the most recent context to summarize problem/solutions.
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


async def enrich_lead_from_conversation(state: ConversationState) -> dict[str, str]:
    """Return best-effort summaries extracted from recent conversation."""
    transcript = _format_recent_transcript(state.get("messages") or [])
    if not transcript:
        return {"problem_summary": "", "solutions_summary": ""}

    llm = get_llm(streaming=False)
    resp = await llm.ainvoke(
        [
            SystemMessage(content=_ENRICH_PROMPT),
            HumanMessage(content=transcript),
        ]
    )
    content = _to_text(resp).strip()
    obj = _parse_json_obj(content)

    problem = str(obj.get("problem_summary") or "").strip()
    solutions = str(obj.get("solutions_summary") or "").strip()
    if len(problem) > 160:
        problem = problem[:160].rstrip()
    if len(solutions) > 160:
        solutions = solutions[:160].rstrip()
    return {"problem_summary": problem, "solutions_summary": solutions}


async def enrich_lead_from_conversation_safe(state: ConversationState) -> dict[str, str]:
    try:
        return await enrich_lead_from_conversation(state)
    except Exception as e:
        logger.exception("Lead enrichment failed: %s", e)
        return {"problem_summary": "", "solutions_summary": ""}
