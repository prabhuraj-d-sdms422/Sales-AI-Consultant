import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.conversion_prompt import CONVERSION_PROMPT, ESCALATION_PROMPT
from app.prompts.solution_advisor_prompt import _format_profile
from app.services.email_service import save_lead_locally
from app.services.lead_service import persist_lead_incrementally
from app.services.sheets_service import append_lead_locally


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


async def _trigger_lead_delivery(state: ConversationState) -> None:
    try:
        await save_lead_locally(state)
        await append_lead_locally(state)
    except Exception as e:
        logging.error("Lead delivery failed for session %s: %s", state.get("session_id"), e)


async def conversion_node(state: ConversationState) -> dict:
    intent = str(state.get("current_intent", ""))
    profile = dict(state.get("client_profile") or {})
    is_escalation = intent == "ESCALATION_REQUEST" or bool(state.get("escalation_requested"))

    if is_escalation:
        system_prompt = ESCALATION_PROMPT.format(
            consultant_name=settings.consultant_name,
            company_name=settings.company_name,
            sales_phone_number=settings.sales_phone_number,
            client_name=profile.get("name", ""),
        )
        updated_state_flags = {
            "escalation_requested": True,
            "escalation_triggered": True,
            "conversation_stage": "ESCALATION",
        }
    else:
        system_prompt = CONVERSION_PROMPT.format(
            consultant_name=settings.consultant_name,
            company_name=settings.company_name,
            sales_phone_number=settings.sales_phone_number,
            client_profile=_format_profile(profile),
            lead_temperature=state.get("lead_temperature", "warm"),
        )
        updated_state_flags = {"conversation_stage": "CONVERSION"}

    messages = _build_messages(state, system_prompt)
    llm = get_llm(streaming=False)
    response = await llm.ainvoke(messages)
    response_text = response.content or ""
    if isinstance(response_text, list):
        response_text = "".join(str(x) for x in response_text)

    await persist_lead_incrementally(state["session_id"], profile, state)
    merged_for_delivery = {
        **dict(state),
        **updated_state_flags,
        "current_response": response_text,
        "current_agent": "conversion",
    }
    if is_escalation or bool(state.get("escalation_triggered")):
        await _trigger_lead_delivery(merged_for_delivery)  # type: ignore[arg-type]

    return {
        **updated_state_flags,
        "current_response": response_text,
        "current_agent": "conversion",
        "should_stream": True,
    }
