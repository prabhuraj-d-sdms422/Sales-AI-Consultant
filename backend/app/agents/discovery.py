from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.discovery_prompt import (
    DISCOVERY_CONVERSATIONAL_PROMPT,
    DISCOVERY_STRUCTURED_PROMPT,
    get_tone_calibration,
)
from app.services.lead_service import persist_lead_incrementally


def _get_missing_fields(profile: dict) -> list[str]:
    priority_order = [
        "industry",
        "problem_raw",
        "scale",
        "budget_signal",
        "decision_maker",
        "urgency",
    ]
    return [f for f in priority_order if not profile.get(f)]


def _format_profile(profile: dict) -> str:
    filled = {k: v for k, v in profile.items() if v}
    return "\n".join(f"- {k}: {v}" for k, v in filled.items()) if filled else "No information collected yet"


def _build_messages(state: ConversationState, system_prompt: str) -> list:
    messages = [SystemMessage(content=system_prompt)]
    for msg in (state.get("messages") or [])[-10:]:
        t = getattr(msg, "type", None) or getattr(msg, "_type", None)
        if t == "human":
            messages.append(HumanMessage(content=_content(msg)))
        elif t in ("ai", "assistant"):
            messages.append(AIMessage(content=_content(msg)))
    return messages


def _content(msg) -> str:
    c = getattr(msg, "content", msg)
    if isinstance(c, list):
        return "".join(str(x) for x in c)
    return str(c)


async def discovery_node(state: ConversationState) -> dict:
    mode = state.get("agent_mode", "CONVERSATIONAL")
    profile = dict(state.get("client_profile") or {})
    tone_block = get_tone_calibration(profile)
    if mode == "CONVERSATIONAL":
        system_prompt = DISCOVERY_CONVERSATIONAL_PROMPT.format(
            tone_calibration=tone_block,
            consultant_name=settings.consultant_name,
            company_name=settings.company_name,
        )
    else:
        missing_fields = _get_missing_fields(profile)
        system_prompt = DISCOVERY_STRUCTURED_PROMPT.format(
            tone_calibration=tone_block,
            consultant_name=settings.consultant_name,
            company_name=settings.company_name,
            client_profile=_format_profile(profile),
            missing_fields=", ".join(missing_fields),
            priority_field=missing_fields[0] if missing_fields else "problem_understood",
        )

    messages = _build_messages(state, system_prompt)
    llm = get_llm(streaming=False)
    response = await llm.ainvoke(messages)
    response_text = response.content or ""
    if isinstance(response_text, list):
        response_text = "".join(str(x) for x in response_text)

    await persist_lead_incrementally(state["session_id"], profile, state)
    return {
        "current_response": response_text,
        "client_profile": profile,
        "current_agent": "discovery",
        "should_stream": True,
    }
