import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.conversion_prompt import CONVERSION_PROMPT, ESCALATION_PROMPT
from app.prompts.solution_advisor_prompt import _format_profile
from app.services.email_service import notify_sales_lead_captured, save_lead_locally
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
        return
    try:
        await notify_sales_lead_captured(state)
    except Exception as e:
        logging.error(
            "SendGrid notification failed for session %s (lead files already saved): %s",
            state.get("session_id"),
            e,
        )


def _has_contact_info(profile: dict) -> bool:
    """Returns True when we have at least a name and one way to reach the client."""
    has_name = bool(profile.get("name"))
    has_contact = bool(profile.get("email") or profile.get("phone"))
    return has_name and has_contact


async def conversion_node(state: ConversationState) -> dict:
    intent = str(state.get("current_intent", ""))
    profile = dict(state.get("client_profile") or {})
    is_escalation = intent == "ESCALATION_REQUEST" or bool(state.get("escalation_requested"))

    # Trigger lead delivery when:
    # 1. Client explicitly asked for a human (escalation)
    # 2. Client shared their contact info (LEAD_INFO_SHARED)
    # 3. Client is a hot lead who confirmed interest (BUYING_SIGNAL) and we have contact info
    is_lead_info_shared = intent == "LEAD_INFO_SHARED"
    is_hot_with_contact = (
        intent in ("BUYING_SIGNAL", "LEAD_INFO_SHARED")
        and _has_contact_info(profile)
    )
    should_deliver_lead = is_escalation or is_lead_info_shared or is_hot_with_contact or bool(
        state.get("escalation_triggered")
    )

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
    if should_deliver_lead:
        logging.info(
            "LEAD DELIVERY triggered | session=%s | intent=%s | stage=%s | has_contact=%s",
            state.get("session_id"),
            intent,
            merged_for_delivery.get("conversation_stage"),
            _has_contact_info(profile),
        )
        await _trigger_lead_delivery(merged_for_delivery)  # type: ignore[arg-type]

    return {
        **updated_state_flags,
        "current_response": response_text,
        "current_agent": "conversion",
        "should_stream": True,
    }
