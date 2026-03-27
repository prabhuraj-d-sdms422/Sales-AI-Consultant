from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.discovery_prompt import (
    DISCOVERY_SMART_PROMPT,
    get_conversation_context,
    get_priority_question_hint,
    get_tone_calibration,
)
from app.services.lead_service import persist_lead_incrementally


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
    profile = dict(state.get("client_profile") or {})
    tone_block = get_tone_calibration(profile)
    conversation_ctx = get_conversation_context(profile)
    priority_hint = get_priority_question_hint(profile)

    system_prompt = DISCOVERY_SMART_PROMPT.format(
        consultant_name=settings.consultant_name,
        company_name=settings.company_name,
        conversation_context=conversation_ctx,
        tone_calibration=tone_block,
        priority_question_hint=priority_hint,
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
