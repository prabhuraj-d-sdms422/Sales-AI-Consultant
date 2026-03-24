"""V1: Saves final lead snapshot to local JSON. Phase 2: Replace with SendGrid."""

import json
import os
from datetime import datetime

from app.models.state import ConversationState

LEADS_DIR = "data/leads"


async def save_lead_locally(state: ConversationState) -> None:
    os.makedirs(LEADS_DIR, exist_ok=True)
    profile = state.get("client_profile", {})
    lead_data = {
        "session_id": state.get("session_id"),
        "saved_at": datetime.utcnow().isoformat(),
        "lead_temperature": state.get("lead_temperature", "cold"),
        "conversation_stage": state.get("conversation_stage"),
        "client_profile": profile,
        "solutions_discussed": state.get("solutions_discussed", []),
        "objections_raised": state.get("objections_raised", []),
        "escalation_requested": state.get("escalation_requested", False),
    }
    filepath = os.path.join(LEADS_DIR, f"{state['session_id']}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(lead_data, f, indent=2, default=str)
