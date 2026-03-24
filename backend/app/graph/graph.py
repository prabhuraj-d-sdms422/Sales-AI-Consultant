from langgraph.graph import END, StateGraph

from app.agents.case_study import case_study_node
from app.agents.conversion import conversion_node
from app.agents.discovery import discovery_node
from app.agents.objection_handler import objection_handler_node
from app.agents.orchestrator import orchestrator_node
from app.agents.solution_advisor import solution_advisor_node
from app.guardrails.input_guardrail import input_guardrail_node
from app.guardrails.output_guardrail import output_guardrail_node
from app.graph.router import (
    route_after_guardrail,
    route_after_guardrail_targets,
    route_after_orchestrator,
)
from app.models.state import ConversationState


def build_graph():
    graph = StateGraph(ConversationState)
    graph.add_node("input_guardrail", input_guardrail_node)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("discovery", discovery_node)
    graph.add_node("solution_advisor", solution_advisor_node)
    graph.add_node("objection_handler", objection_handler_node)
    graph.add_node("conversion", conversion_node)
    graph.add_node("case_study", case_study_node)
    graph.add_node("output_guardrail", output_guardrail_node)

    graph.set_entry_point("input_guardrail")
    graph.add_conditional_edges(
        "input_guardrail",
        route_after_guardrail,
        route_after_guardrail_targets(),
    )
    graph.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
            "discovery": "discovery",
            "solution_advisor": "solution_advisor",
            "objection_handler": "objection_handler",
            "conversion": "conversion",
            "case_study": "case_study",
            "output_guardrail": "output_guardrail",
        },
    )
    for agent in [
        "discovery",
        "solution_advisor",
        "objection_handler",
        "conversion",
        "case_study",
    ]:
        graph.add_edge(agent, "output_guardrail")
    graph.add_edge("output_guardrail", END)
    return graph.compile()


conversation_graph = build_graph()
