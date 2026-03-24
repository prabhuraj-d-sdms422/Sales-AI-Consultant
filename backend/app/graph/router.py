from langgraph.graph import END

from app.models.state import ConversationState


def route_after_guardrail(state: ConversationState) -> str:
    if not state.get("input_guardrail_passed", True):
        return "end"
    return "orchestrator"


def route_after_guardrail_targets() -> dict:
    return {"orchestrator": "orchestrator", "end": END}


def route_after_orchestrator(state: ConversationState) -> str:
    # If the orchestrator classifies the user intent as manipulation/prompt-injection,
    # skip all downstream agents and directly render the output guardrail node
    # (which will stream the safe fallback from state).
    if state.get("current_intent") == "MANIPULATION_ATTEMPT":
        return "output_guardrail"

    agent = state.get("current_agent", "discovery")
    routing_map = {
        "discovery": "discovery",
        "solution_advisor": "solution_advisor",
        "objection_handler": "objection_handler",
        "conversion": "conversion",
        "case_study": "case_study",
    }
    return routing_map.get(agent, "discovery")
