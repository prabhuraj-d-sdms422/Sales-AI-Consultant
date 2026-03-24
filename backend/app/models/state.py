from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class ClientProfile(TypedDict, total=False):
    name: Optional[str]
    company: Optional[str]
    email: Optional[str]
    phone: Optional[str]
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
