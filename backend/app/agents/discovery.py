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
from app.services.conversation_memory_service import format_memory_block_for_prompt
from app.services.lead_service import persist_lead_incrementally
from app.services.website_research_service import WebsiteResearchService, looks_like_website_analysis_request
from app.services.token_cost_service import (
    add_usage_totals,
    extract_token_usage_from_message,
    get_active_provider_and_model,
)
from app.utils.llm_output import extract_text


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

    hr_email = str(settings.hr_email or "").strip() or "hr@starkdigital.net"
    hr_phone = str(settings.hr_phone_number or "").strip()
    hr_contact_block = f"Email: {hr_email}"
    if hr_phone:
        hr_contact_block += f"\nPhone/WhatsApp: {hr_phone}"

    website_context = "None"
    website_sources: list[str] = []
    website_research: dict | None = None
    msgs = state.get("messages") or []
    last = msgs[-1] if msgs else None
    last_text = _content(last) if last is not None else ""
    if settings.website_research_enabled and looks_like_website_analysis_request(last_text):
        svc = WebsiteResearchService(
            max_pages=settings.website_research_max_pages,
            timeout_seconds=settings.website_research_timeout_seconds,
            max_bytes_per_page=settings.website_research_max_bytes_per_page,
            max_chars_per_page=settings.website_research_max_chars_per_page,
        )
        try:
            result = await svc.research_from_text(last_text)
            if result is not None and result.pages:
                website_sources = result.sources
                website_context = result.summary_text
                website_research = {
                    "start_url": result.start_url,
                    "pages": [
                        {
                            "url": p.url,
                            "title": p.title,
                            "text_snippet": p.text_snippet,
                            "word_count": p.word_count,
                        }
                        for p in result.pages
                    ],
                }
        except Exception:
            # If website fetch fails, proceed with normal discovery.
            website_context = "None"

    system_prompt = DISCOVERY_SMART_PROMPT.format(
        consultant_name=settings.consultant_name,
        company_name=settings.company_name,
        conversation_context=conversation_ctx,
        website_context=website_context,
        hr_contact_block=hr_contact_block,
        tone_calibration=tone_block,
        priority_question_hint=priority_hint,
    )
    memory_block = format_memory_block_for_prompt(state)
    if memory_block:
        system_prompt = system_prompt + "\n\n" + memory_block

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
    response_text = extract_text(getattr(response, "content", response))

    await persist_lead_incrementally(state["session_id"], profile, state)
    sources_payload = [
        {"id": url, "problem_title": "Website page", "namespace": "website", "score": 1.0}
        for url in website_sources
    ]
    return {
        "current_response": response_text,
        "client_profile": profile,
        "current_agent": "discovery",
        "should_stream": True,
        "last_answer_sources": sources_payload,
        "website_research": website_research,
        "website_sources": website_sources,
        "session_token_usage": session_token_usage,
        "last_call_token_usage": {"provider": provider, "model": model, **usage},
    }
