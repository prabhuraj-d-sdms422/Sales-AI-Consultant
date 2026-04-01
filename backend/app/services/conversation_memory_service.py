"""Conversation memory: structured memory + rolling summary + recent window.

Design goals:
- Preserve existing behavior: if this fails, the chat still works.
- Reduce tokens: inject a compact memory block rather than long transcripts.
- Keep it practical: update summary occasionally, not every turn.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.models.state import ConversationState

logger = logging.getLogger(__name__)


SUMMARY_SYSTEM_PROMPT = """You summarize an ongoing sales discovery conversation.

You will be given:
- an existing summary (may be empty)
- the latest structured lead fields
- the most recent chat turns

Update the summary to keep only the most useful long-term context.

Rules:
- Output JSON only: {"summary": "<text>"}
- Keep it <= 600 characters.
- Include only stable facts: client identity, company, industry, problem, constraints, urgency/budget, what solution direction was discussed, next step.
- Do not include greetings or filler.
- Do not invent facts not present in inputs.
"""


def _to_text(msg: Any) -> str:
    c = getattr(msg, "content", msg)
    if isinstance(c, list):
        return "".join(str(x) for x in c)
    return str(c or "")


def _safe_json_obj(text: str) -> dict[str, Any]:
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


def format_structured_memory(state: ConversationState) -> str:
    """Compact, deterministic memory block built from structured state."""
    profile = dict(state.get("client_profile") or {})
    parts: list[str] = []
    if profile.get("name"):
        parts.append(f"Name: {profile.get('name')}")
    if profile.get("company"):
        parts.append(f"Company: {profile.get('company')}")
    if profile.get("industry"):
        parts.append(f"Industry: {profile.get('industry')}")
    problem = profile.get("problem_understood") or profile.get("problem_raw")
    if problem:
        parts.append(f"Problem: {problem}")
    if profile.get("urgency"):
        parts.append(f"Urgency: {profile.get('urgency')}")
    if profile.get("budget_signal"):
        parts.append(f"Budget: {profile.get('budget_signal')}")
    if state.get("solutions_discussed"):
        parts.append(f"Solutions discussed: {', '.join(state.get('solutions_discussed') or [])}")
    if state.get("objections_raised"):
        parts.append(f"Objections: {', '.join(state.get('objections_raised') or [])}")
    if state.get("conversation_stage"):
        parts.append(f"Stage: {state.get('conversation_stage')}")
    if state.get("lead_temperature"):
        parts.append(f"Lead temp: {state.get('lead_temperature')}")
    return "\n".join(parts).strip()


def format_memory_block_for_prompt(state: ConversationState) -> str:
    """Final memory block injected into agent system prompts."""
    structured = format_structured_memory(state)
    summary = (state.get("conversation_summary") or "").strip()
    block_parts: list[str] = []
    if structured:
        block_parts.append("## STRUCTURED MEMORY (authoritative)\n" + structured)
    if summary:
        block_parts.append("## ROLLING SUMMARY (compact)\n" + summary)
    if not block_parts:
        return ""
    return "\n\n".join(block_parts).strip()


def should_update_summary(state: ConversationState) -> bool:
    """
    Update occasionally:
    - only after the conversation has some length
    - every ~5 user turns
    """
    msgs = state.get("messages") or []
    if len(msgs) < 10:
        return False
    turns = int(state.get("summary_turns_since_update") or 0)
    return turns >= 5


async def update_summary_if_needed(state: ConversationState) -> dict:
    """
    Best-effort summary refresh. Returns state updates (may be empty).
    Never raises.
    """
    try:
        if not should_update_summary(state):
            # still increment turn counter at orchestrator level
            return {}

        profile = dict(state.get("client_profile") or {})
        existing_summary = (state.get("conversation_summary") or "").strip()

        # keep recent turns small; we only need a refresh window
        recent = []
        for m in (state.get("messages") or [])[-12:]:
            t = getattr(m, "type", None) or getattr(m, "_type", None)
            role = "user" if t in ("human", "user") else "assistant" if t in ("ai", "assistant") else "other"
            txt = _to_text(m).strip()
            if txt:
                recent.append(f"{role}: {txt}")
        recent_text = "\n".join(recent)

        llm = get_llm(streaming=False, temperature=0.2)
        resp = await llm.ainvoke(
            [
                SystemMessage(content=SUMMARY_SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"Existing summary:\n{existing_summary or '(empty)'}\n\n"
                        f"Structured fields:\n{json.dumps(profile, ensure_ascii=False)}\n\n"
                        f"Recent turns:\n{recent_text}"
                    )
                ),
            ]
        )
        obj = _safe_json_obj(_to_text(resp))
        summary = str(obj.get("summary") or "").strip()
        if len(summary) > 600:
            summary = summary[:600].rstrip()
        return {
            "conversation_summary": summary,
            "summary_turns_since_update": 0,
        }
    except Exception as e:
        logger.exception("Conversation summary update failed: %s", e)
        return {}
