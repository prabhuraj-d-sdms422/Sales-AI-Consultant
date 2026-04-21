from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.discovery_prompt import get_tone_calibration
from app.prompts.objection_handler_prompt import OBJECTION_HANDLER_PROMPT
from app.prompts.solution_advisor_prompt import _format_profile
from app.services.conversation_memory_service import format_memory_block_for_prompt
from app.services.lead_service import persist_lead_incrementally
from app.services.token_cost_service import (
    add_usage_totals,
    extract_token_usage_from_message,
    get_active_provider_and_model,
)
from app.utils.llm_output import extract_text


def _content(msg) -> str:
    c = getattr(msg, "content", msg)
    if isinstance(c, list):
        return "".join(str(x) for x in c)
    return str(c)


def _build_messages(state: ConversationState, system_prompt: str) -> list:
    messages = [SystemMessage(content=system_prompt)]
    for msg in (state.get("messages") or [])[-8:]:
        t = getattr(msg, "type", None)
        if t == "human":
            messages.append(HumanMessage(content=_content(msg)))
        elif t in ("ai", "assistant"):
            messages.append(AIMessage(content=_content(msg)))
    return messages


async def objection_handler_node(state: ConversationState) -> dict:
    profile = dict(state.get("client_profile") or {})
    objections_raised = list(state.get("objections_raised") or [])
    msgs = state.get("messages") or []
    last_message = _content(msgs[-1]) if msgs else ""
    tone_block = get_tone_calibration(profile)
    system_prompt = OBJECTION_HANDLER_PROMPT.format(
        company_name=settings.company_name,
        client_profile=_format_profile(profile),
        objections_raised=", ".join(objections_raised) or "none yet",
        current_objection=last_message,
        tone_calibration=tone_block,
    )
    memory_block = format_memory_block_for_prompt(state)
    if memory_block:
        system_prompt = system_prompt + "\n\n" + memory_block
    messages = _build_messages(state, system_prompt)
    llm = get_llm(streaming=False, temperature=0.2)
    response = await llm.ainvoke(messages)
    provider, model = get_active_provider_and_model()
    usage = extract_token_usage_from_message(response)
    session_token_usage = add_usage_totals(
        current=state.get("session_token_usage"),
        add_input_tokens=usage["input_tokens"],
        add_output_tokens=usage["output_tokens"],
        provider=provider,
        model=model,
    )
    response_text = extract_text(getattr(response, "content", response))

    updated_objections = objections_raised + [last_message[:80]]
    await persist_lead_incrementally(state["session_id"], profile, state)
    return {
        "current_response": response_text,
        "objections_raised": updated_objections,
        "current_agent": "objection_handler",
        "conversation_stage": "OBJECTION",
        "should_stream": True,
        "last_answer_sources": [],
        "session_token_usage": session_token_usage,
        "last_call_token_usage": {"provider": provider, "model": model, **usage},
    }
