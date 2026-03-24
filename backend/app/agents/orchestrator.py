import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.config.llm_provider import get_classification_llm
from app.config.settings import settings
from app.models.state import ConversationState
from app.prompts.orchestrator_prompt import ORCHESTRATOR_SYSTEM_PROMPT
from app.services.session_service import save_state
from app.utils.intent_classes import IntentClass


def _parse_orchestrator_response(content: str) -> dict:
    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except Exception:
        pass
    return {
        "intent": "GENERAL_INQUIRY",
        "confidence": 0.5,
        "next_agent": "discovery",
        "agent_mode": "CONVERSATIONAL",
    }


def _build_classification_prompt(state: ConversationState, message: str) -> str:
    stage = state.get("conversation_stage", "GREETING")
    profile = state.get("client_profile") or {}
    known_info = [k for k, v in profile.items() if v]
    return f"""Conversation stage: {stage}
Client profile fields collected: {", ".join(known_info) if known_info else "none yet"}

Client message: "{message}"

Classify this message and determine routing. Return JSON only."""


def _sanitize_next_agent(agent: str) -> str:
    allowed = {"discovery", "solution_advisor", "objection_handler", "conversion", "case_study"}
    if agent not in allowed:
        return "discovery"
    return agent


async def orchestrator_node(state: ConversationState) -> dict:
    llm = get_classification_llm()
    msgs = state.get("messages") or []
    last = msgs[-1]
    last_message = getattr(last, "content", str(last))
    if isinstance(last_message, list):
        last_message = "".join(str(x) for x in last_message)

    classification_prompt = _build_classification_prompt(state, last_message)
    response = await llm.ainvoke(
        [
            SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT),
            HumanMessage(content=classification_prompt),
        ]
    )
    result = _parse_orchestrator_response(response.content or "")

    intent = str(result.get("intent", IntentClass.GENERAL_INQUIRY.value))
    confidence = float(result.get("confidence", 0.5))
    next_agent = _sanitize_next_agent(str(result.get("next_agent", "discovery")))
    updated_stage = str(result.get("updated_stage", state.get("conversation_stage", "GREETING")))
    agent_mode = str(result.get("agent_mode", "CONVERSATIONAL"))
    profile_updates = result.get("profile_updates") or {}
    if not isinstance(profile_updates, dict):
        profile_updates = {}
    lead_temperature = str(result.get("lead_temperature", state.get("lead_temperature", "cold")))

    if confidence < settings.intent_confidence_threshold:
        intent = IntentClass.LOW_CONFIDENCE.value
        next_agent = "discovery"
        agent_mode = "CONVERSATIONAL"

    base_profile = dict(state.get("client_profile") or {})
    merged_profile = {**base_profile, **{k: v for k, v in profile_updates.items() if v is not None}}

    # Safe fallback for manipulation/prompt-injection attempts.
    # We intentionally do not let any sales agent generate a response in this case.
    manipulation_safe_fallback = (
        "I am here to help with business and technology requirements. "
        "What challenge can I help you solve today?"
    )

    updates: dict = {
        "current_intent": intent,
        "intent_confidence": confidence,
        "current_agent": next_agent,
        "conversation_stage": updated_stage,
        "agent_mode": agent_mode,
        "client_profile": merged_profile,
        "lead_temperature": lead_temperature,
    }

    if intent == IntentClass.MANIPULATION_ATTEMPT.value:
        updates["current_response"] = manipulation_safe_fallback
    merged = {**dict(state), **updates}
    await save_state(state["session_id"], merged)
    return updates
