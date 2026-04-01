import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.conversion_prompt import CONVERSION_PROMPT, ESCALATION_PROMPT
from app.prompts.solution_advisor_prompt import _format_profile
from app.services.email_service import notify_sales_lead_captured, save_lead_locally
from app.services.lead_enrichment_service import enrich_lead_from_conversation_safe
from app.services.hubspot_service import sync_lead_to_hubspot_safe
from app.services.lead_service import persist_lead_incrementally
from app.services.sheets_service import append_lead_google_sheets, append_lead_locally
from app.services.token_cost_service import (
    add_usage_totals,
    extract_token_usage_from_message,
    get_active_provider_and_model,
)


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
    """Persist lead: HubSpot first (for CRM link), then JSON/Excel/Sheets; always attempt email."""
    session_id = state.get("session_id")

    delivery_state: ConversationState = dict(state)

    def _norm(s: object) -> str:
        return " ".join(str(s or "").strip().split())

    def _append_unique(items: list[str] | None, new_item: object) -> list[str]:
        out = list(items or [])
        v = _norm(new_item)
        if not v:
            return out
        v_l = v.lower()
        for e in out:
            if _norm(e).lower() == v_l:
                return out
        out.append(v)
        return out

    # Best-effort enrichment so Sheets/HubSpot/Email always have ALL problems/solutions/metrics,
    # even when routing/labels vary or the user introduces multiple issues mid-session.
    enrichment = await enrich_lead_from_conversation_safe(delivery_state)
    delivery_state["conversation_insights"] = enrichment

    profile = dict(delivery_state.get("client_profile") or {})
    all_problems = list(enrichment.get("all_problems") or [])
    all_solutions = list(enrichment.get("all_solutions") or [])

    # Keep backward-compatible single "Problem" field populated (use first known problem).
    if all_problems and not (profile.get("problem_understood") or profile.get("problem_raw")):
        profile["problem_understood"] = str(all_problems[0])
    delivery_state["client_profile"] = profile

    # Ensure we accumulate all problems in the lead payload (state-level list).
    problems_identified = list(delivery_state.get("problems_identified") or [])
    for p in all_problems:
        problems_identified = _append_unique(problems_identified, p)
    delivery_state["problems_identified"] = problems_identified

    # Ensure solutions_discussed is populated even if solution_advisor wasn't called.
    existing = list(delivery_state.get("solutions_discussed") or [])
    if not existing and all_solutions:
        delivery_state["solutions_discussed"] = [_norm(x) for x in all_solutions if _norm(x)]

    hubspot_url = await sync_lead_to_hubspot_safe(delivery_state) or ""
    if hubspot_url:
        delivery_state["hubspot_contact_url"] = hubspot_url

    try:
        await save_lead_locally(delivery_state)
    except Exception as e:
        logging.error("save_lead_locally failed for session %s: %s", session_id, e)
    try:
        await append_lead_locally(delivery_state)
    except Exception as e:
        logging.error("append_lead_locally (Excel) failed for session %s: %s", session_id, e)
    try:
        await append_lead_google_sheets(delivery_state)
    except Exception as e:
        logging.error("append_lead_google_sheets failed for session %s: %s", session_id, e)
    try:
        await notify_sales_lead_captured(delivery_state)
    except Exception as e:
        logging.error("SendGrid notify_sales_lead_captured failed for session %s: %s", session_id, e)


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
    provider, model = get_active_provider_and_model()
    usage = extract_token_usage_from_message(response)
    session_token_usage = add_usage_totals(
        current=state.get("session_token_usage"),
        add_input_tokens=usage["input_tokens"],
        add_output_tokens=usage["output_tokens"],
        provider=provider,
        model=model,
    )
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
        "last_answer_sources": [],
        "session_token_usage": session_token_usage,
        "last_call_token_usage": {"provider": provider, "model": model, **usage},
    }
