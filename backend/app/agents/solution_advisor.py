import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.discovery_prompt import get_tone_calibration
from app.prompts.solution_advisor_prompt import (
    SOLUTION_ADVISOR_PROMPT,
    SOLUTION_ADVISOR_RAG_PROMPT,
    _format_profile,
)
from app.services.conversation_memory_service import format_memory_block_for_prompt
from app.services.lead_service import persist_lead_incrementally
from app.services.rag_service import (
    NAMESPACE_HEALTHCARE,
    NAMESPACE_INSURANCE,
    get_industry_context_with_sources,
    get_industry_context,
    is_healthcare_context,
    is_insurance_context,
)
from app.services.token_cost_service import (
    add_usage_totals,
    extract_token_usage_from_message,
    get_active_provider_and_model,
)
from app.utils.llm_output import extract_text

logger = logging.getLogger(__name__)


def _looks_underspecified_build_intent(text: str) -> bool:
    """
    Narrow guard: catch very vague build intent so we clarify instead of guessing.
    This should only trigger when the user has not provided any concrete problem/deliverable.
    """
    t = (text or "").strip().lower()
    if not t:
        return True
    # If they wrote a longer message, assume there's enough signal.
    if len(t) >= 80:
        return False
    vague_phrases = (
        "i want to build",
        "we want to build",
        "i need to build",
        "we need to build",
        "i want to make",
        "we want to make",
        "i want to create",
        "we want to create",
        "i want to develop",
        "we want to develop",
        "i need an ai",
        "we need an ai",
        "ai solution",
        "something for my business",
        "something for our business",
    )
    return any(p in t for p in vague_phrases)


def _content(msg) -> str:
    c = getattr(msg, "content", msg)
    if isinstance(c, list):
        return "".join(str(x) for x in c)
    return str(c)


def _build_messages(state: ConversationState, system_prompt: str) -> list:
    messages = [SystemMessage(content=system_prompt)]
    for msg in (state.get("messages") or [])[-10:]:
        t = getattr(msg, "type", None)
        if t == "human":
            messages.append(HumanMessage(content=_content(msg)))
        elif t in ("ai", "assistant"):
            messages.append(AIMessage(content=_content(msg)))
    return messages


def _build_query_text(profile: dict) -> str:
    """
    Compose the semantic query from what we know about the client's problem.
    More context → better match quality from Pinecone.
    """
    parts: list[str] = []
    if profile.get("problem_understood"):
        parts.append(profile["problem_understood"])
    if profile.get("problem_raw"):
        parts.append(profile["problem_raw"])
    if profile.get("industry"):
        parts.append(f"Industry: {profile['industry']}")
    if profile.get("existing_products"):
        parts.append(profile["existing_products"])
    return " ".join(parts)


async def solution_advisor_node(state: ConversationState) -> dict:
    profile           = dict(state.get("client_profile") or {})
    solutions_discussed = list(state.get("solutions_discussed") or [])
    tone_block        = get_tone_calibration(profile)
    website_research = state.get("website_research") or None
    website_sources = list(state.get("website_sources") or [])

    # ── RAG context lookup ─────────────────────────────────────────────────────
    rag_context: str | None = None
    rag_sources: list[dict] = []
    query_text = _build_query_text(profile)

    if query_text:
        industry = profile.get("industry", "")
        # Prefer the most specific industry namespace first.
        namespace = None
        if is_insurance_context(industry=industry, problem_text=query_text):
            namespace = NAMESPACE_INSURANCE
        elif is_healthcare_context(industry=industry, problem_text=query_text):
            namespace = NAMESPACE_HEALTHCARE

        if namespace:
            logger.info(
                "RAG: domain detected (%s) for session %s — querying Pinecone.",
                namespace,
                state.get("session_id"),
            )
            rag_context, rag_sources = await get_industry_context_with_sources(
                query_text=query_text,
                namespace=namespace,
                top_k=settings.rag_top_k,
                threshold=settings.rag_similarity_threshold,
            )
            if rag_context:
                logger.info("RAG: context injected for session %s.", state.get("session_id"))
            else:
                logger.debug(
                    "RAG: no relevant matches found for session %s in namespace %s — "
                    "falling back to LLM general knowledge.",
                    state.get("session_id"),
                    namespace,
                )

    # ── Build system prompt ────────────────────────────────────────────────────
    if rag_context:
        system_prompt = SOLUTION_ADVISOR_RAG_PROMPT.format(
            tone_calibration=tone_block,
            client_profile=_format_profile(profile),
            solutions_already_discussed=", ".join(solutions_discussed) or "none yet",
            consultant_name=settings.consultant_name,
            company_name=settings.company_name,
            rag_context=rag_context,
        )
    else:
        system_prompt = SOLUTION_ADVISOR_PROMPT.format(
            tone_calibration=tone_block,
            client_profile=_format_profile(profile),
            solutions_already_discussed=", ".join(solutions_discussed) or "none yet",
            consultant_name=settings.consultant_name,
            company_name=settings.company_name,
        )

    if isinstance(website_research, dict) and website_research.get("pages"):
        # Ground recommendations in the user's public website content.
        pages = website_research.get("pages") or []
        ctx_parts: list[str] = []
        for p in pages[: settings.website_research_max_pages]:
            url = str(p.get("url") or "")
            title = str(p.get("title") or "")
            snippet = str(p.get("text_snippet") or "")
            if not url or not snippet:
                continue
            ctx_parts.append(f"URL: {url}\nTitle: {title or 'n/a'}\n{snippet}")
        website_context = "\n\n---\n\n".join(ctx_parts).strip()
        if website_context:
            system_prompt = (
                system_prompt
                + "\n\n"
                + "## WEBSITE CONTEXT (public pages provided by the client):\n"
                + website_context
            )

    # Safety net: if routing sends an underspecified ask here, force clarification.
    msgs = state.get("messages") or []
    last = msgs[-1] if msgs else None
    last_text = _content(last) if last is not None else ""
    has_problem_signal = bool(profile.get("problem_raw") or profile.get("problem_understood")) or bool(
        state.get("problems_identified")
    )
    if (not has_problem_signal) and _looks_underspecified_build_intent(last_text):
        system_prompt = (
            system_prompt
            + "\n\n"
            + "CLARIFICATION MODE (CRITICAL): The client's ask is underspecified. "
            + "Ask 1–2 short clarifying questions to understand what they want to build or what problem they're solving. "
            + "Do NOT assume the solution type. Do NOT propose a specific product yet."
        )
    memory_block = format_memory_block_for_prompt(state)
    if memory_block:
        system_prompt = system_prompt + "\n\n" + memory_block

    messages     = _build_messages(state, system_prompt)
    llm          = get_llm(streaming=False)
    response     = await llm.ainvoke(messages)
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

    updated_solutions = solutions_discussed + [response_text[:50]]
    await persist_lead_incrementally(state["session_id"], profile, state)
    website_sources_payload = [
        {"id": url, "problem_title": "Website page", "namespace": "website", "score": 1.0}
        for url in website_sources
    ]
    return {
        "current_response":    response_text,
        "solutions_discussed": updated_solutions,
        "current_agent":       "solution_advisor",
        "conversation_stage":  "PROPOSAL",
        "should_stream":       True,
        "last_answer_sources": (list(rag_sources) if isinstance(rag_sources, list) else []) + website_sources_payload,
        "session_token_usage": session_token_usage,
        "last_call_token_usage": {"provider": provider, "model": model, **usage},
    }
