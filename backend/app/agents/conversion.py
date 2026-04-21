import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.conversion_prompt import CONVERSION_PROMPT, ESCALATION_PROMPT
from app.prompts.solution_advisor_prompt import _format_profile
from app.services.conversation_memory_service import format_memory_block_for_prompt
from app.services.lead_delivery_service import deliver_now_if_possible, end_session_and_maybe_deliver
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


async def conversion_node(state: ConversationState) -> dict:
    intent = str(state.get("current_intent", ""))
    profile = dict(state.get("client_profile") or {})
    is_escalation = intent == "ESCALATION_REQUEST" or bool(state.get("escalation_requested"))
    is_conversation_ended = intent == "CONVERSATION_ENDED"

    # Only escalation is real-time. End-of-conversation delivery is handled by session end.
    should_deliver_now = is_escalation or bool(state.get("escalation_triggered"))

    if is_escalation:
        # Build a definitive contact-status note so the LLM never re-asks for details we already have.
        _email = (profile.get("email") or "").strip()
        _phone = (profile.get("phone") or "").strip()
        if _email or _phone:
            _parts = []
            if _email:
                _parts.append(f"email: {_email}")
            if _phone:
                _parts.append(f"phone: {_phone}")
            contact_note = (
                f"Contact details already collected ({', '.join(_parts)}). "
                "DO NOT ask for contact details. Confirm the team will reach out using these details."
            )
        else:
            contact_note = (
                "No contact details collected yet. "
                "Offer to take their phone number or email so the team can follow up."
            )
        system_prompt = ESCALATION_PROMPT.format(
            consultant_name=settings.consultant_name,
            company_name=settings.company_name,
            sales_phone_number=settings.sales_phone_number,
            client_name=profile.get("name", ""),
            contact_note=contact_note,
        )
        updated_state_flags = {
            "escalation_requested": True,
            "escalation_triggered": True,
            "conversation_stage": "ESCALATION",
        }
    elif is_conversation_ended:
        # Keep this deterministic (and cheap) so session closing never depends on LLM availability.
        system_prompt = ""
        updated_state_flags = {
            "conversation_stage": "CLOSED",
            "conversation_ended": True,
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
    memory_block = format_memory_block_for_prompt(state)
    if memory_block:
        system_prompt = system_prompt + "\n\n" + memory_block

    response_text: str
    provider: str
    model: str
    usage: dict

    if is_conversation_ended:
        response_text = (
            "Thanks for chatting with us — happy to help. "
            "If you’d like, share any final details and we’ll follow up shortly. Goodbye."
        )
        provider, model = get_active_provider_and_model()
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "estimated_cost_usd": 0.0, "estimated_cost_inr": 0.0, "usd_to_inr_rate": float(getattr(settings, "usd_to_inr_rate", 0.0) or 0.0)}
    else:
        messages = _build_messages(state, system_prompt)
        llm = get_llm(streaming=False)
        response = await llm.ainvoke(messages)
        provider, model = get_active_provider_and_model()
        usage = extract_token_usage_from_message(response)
        response_text = extract_text(getattr(response, "content", response))
    session_token_usage = add_usage_totals(
        current=state.get("session_token_usage"),
        add_input_tokens=usage["input_tokens"],
        add_output_tokens=usage["output_tokens"],
        provider=provider,
        model=model,
    )

    await persist_lead_incrementally(state["session_id"], profile, state)
    merged_for_delivery = {
        **dict(state),
        **updated_state_flags,
        "current_response": response_text,
        "current_agent": "conversion",
    }
    if should_deliver_now:
        logging.info(
            "LEAD DELIVERY triggered (real-time) | session=%s | intent=%s | stage=%s",
            state.get("session_id"),
            intent,
            merged_for_delivery.get("conversation_stage"),
        )
        # Escalation remains real-time (does not end session).
        delivered = await deliver_now_if_possible(merged_for_delivery, reason="escalation")  # type: ignore[arg-type]
        merged_for_delivery.update(delivered)
    elif is_conversation_ended:
        # Explicit wrap-up: end the session and deliver once (if email/phone exists).
        delivered = await end_session_and_maybe_deliver(
            merged_for_delivery, reason="conversation_ended_intent"  # type: ignore[arg-type]
        )
        merged_for_delivery.update(delivered)

    return {
        **updated_state_flags,
        "current_response": response_text,
        "current_agent": "conversion",
        "should_stream": True,
        "last_answer_sources": [],
        "session_token_usage": session_token_usage,
        "last_call_token_usage": {"provider": provider, "model": model, **usage},
        "conversation_ended": bool(merged_for_delivery.get("conversation_ended", False)),
        "lead_delivered": bool(merged_for_delivery.get("lead_delivered", False)),
    }
