from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config.llm_provider import get_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.discovery_prompt import get_tone_calibration
from app.prompts.solution_advisor_prompt import SOLUTION_ADVISOR_PROMPT, _format_profile
from app.services.lead_service import persist_lead_incrementally


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


async def solution_advisor_node(state: ConversationState) -> dict:
    profile = dict(state.get("client_profile") or {})
    solutions_discussed = list(state.get("solutions_discussed") or [])
    tone_block = get_tone_calibration(profile)
    system_prompt = SOLUTION_ADVISOR_PROMPT.format(
        tone_calibration=tone_block,
        client_profile=_format_profile(profile),
        solutions_already_discussed=", ".join(solutions_discussed) or "none yet",
        company_name=settings.company_name,
    )
    messages = _build_messages(state, system_prompt)
    llm = get_llm(streaming=False)
    response = await llm.ainvoke(messages)
    response_text = response.content or ""
    if isinstance(response_text, list):
        response_text = "".join(str(x) for x in response_text)

    updated_solutions = solutions_discussed + [response_text[:50]]
    await persist_lead_incrementally(state["session_id"], profile, state)
    return {
        "current_response": response_text,
        "solutions_discussed": updated_solutions,
        "current_agent": "solution_advisor",
        "conversation_stage": "PROPOSAL",
        "should_stream": True,
    }
