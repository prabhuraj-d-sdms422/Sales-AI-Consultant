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
from app.services.lead_service import persist_lead_incrementally
from app.services.rag_service import (
    NAMESPACE_HEALTHCARE,
    get_industry_context,
    is_healthcare_context,
)
from app.services.token_cost_service import (
    add_usage_totals,
    extract_token_usage_from_message,
    get_active_provider_and_model,
)

logger = logging.getLogger(__name__)


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

    # ── RAG context lookup ─────────────────────────────────────────────────────
    rag_context: str | None = None
    query_text = _build_query_text(profile)

    if query_text and is_healthcare_context(
        industry=profile.get("industry", ""),
        problem_text=query_text,
    ):
        logger.info(
            "RAG: healthcare domain detected for session %s — querying Pinecone.",
            state.get("session_id"),
        )
        rag_context = await get_industry_context(
            query_text=query_text,
            namespace=NAMESPACE_HEALTHCARE,
            top_k=settings.rag_top_k,
            threshold=settings.rag_similarity_threshold,
        )
        if rag_context:
            logger.info(
                "RAG: context injected for session %s.", state.get("session_id")
            )
        else:
            logger.debug(
                "RAG: no relevant healthcare matches found for session %s — "
                "falling back to LLM general knowledge.",
                state.get("session_id"),
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
    response_text = response.content or ""
    if isinstance(response_text, list):
        response_text = "".join(str(x) for x in response_text)

    updated_solutions = solutions_discussed + [response_text[:50]]
    await persist_lead_incrementally(state["session_id"], profile, state)
    return {
        "current_response":    response_text,
        "solutions_discussed": updated_solutions,
        "current_agent":       "solution_advisor",
        "conversation_stage":  "PROPOSAL",
        "should_stream":       True,
        "session_token_usage": session_token_usage,
        "last_call_token_usage": {"provider": provider, "model": model, **usage},
    }
