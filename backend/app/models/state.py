from typing import Annotated, NotRequired, Optional, TypedDict, Any

from langgraph.graph.message import add_messages


class ClientProfile(TypedDict, total=False):
    name: Optional[str]
    company: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    location: Optional[str]
    industry: Optional[str]
    problem_raw: Optional[str]
    problem_understood: Optional[str]
    scale: Optional[str]
    budget_signal: Optional[str]
    technical_level: Optional[str]
    decision_maker: Optional[bool]
    urgency: Optional[str]
    existing_products: Optional[str]


class ConversationState(TypedDict):
    session_id: str
    created_at: str
    last_active: str
    messages: Annotated[list, add_messages]
    client_profile: ClientProfile
    conversation_stage: str
    current_intent: str
    intent_confidence: float
    agent_mode: str
    current_agent: str
    current_response: str
    solutions_discussed: list[str]
    objections_raised: list[str]
    input_guardrail_passed: bool
    output_guardrail_passed: bool
    guardrail_flags: list[dict]
    lead_persisted: bool
    lead_temperature: str
    escalation_requested: bool
    escalation_triggered: bool
    should_stream: bool
    conversation_ended: bool
    lead_delivered: bool

    # Token usage + costing (per session)
    # Stored in Redis and optionally archived to backend/data/Conversations/*.json
    session_token_usage: dict
    last_call_token_usage: dict

    # Set when HubSpot sync succeeds during lead delivery
    hubspot_contact_url: NotRequired[str]

    # Shareable link to the human-readable conversation viewer page
    conversation_viewer_url: NotRequired[str]

    # Accumulated issues discussed across the session (multi-problem support)
    problems_identified: NotRequired[list[str]]

    # Best-effort structured insights extracted from transcript at lead delivery time
    conversation_insights: NotRequired[dict[str, Any]]

    # Sources / provenance per assistant answer (optional; additive)
    last_answer_sources: NotRequired[list[dict]]
    answer_sources: NotRequired[list[dict]]

    # Rolling summary / memory (optional; additive)
    conversation_summary: NotRequired[str]
    summary_turns_since_update: NotRequired[int]
