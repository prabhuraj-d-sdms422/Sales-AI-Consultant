"""
V1: Lead data saved to local JSON in data/leads/.
Updated after EVERY turn.
"""

import json
import os
from datetime import datetime

LEADS_DIR = "data/leads"


async def persist_lead_incrementally(session_id: str, profile: dict, state: dict) -> None:
    """Save/update lead JSON after every turn. Never overwrites existing values with None."""
    os.makedirs(LEADS_DIR, exist_ok=True)
    filepath = os.path.join(LEADS_DIR, f"{session_id}.json")
    if os.path.exists(filepath):
        with open(filepath, encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = {"session_id": session_id, "created_at": datetime.utcnow().isoformat()}

    existing_profile = existing.get("client_profile", {})
    for key, value in profile.items():
        if value is not None:
            existing_profile[key] = value
    existing["client_profile"] = existing_profile
    existing["lead_temperature"] = state.get("lead_temperature", existing.get("lead_temperature", "cold"))
    existing["conversation_stage"] = state.get("conversation_stage", "")
    existing["solutions_discussed"] = state.get("solutions_discussed", [])
    existing["objections_raised"] = state.get("objections_raised", [])
    existing["escalation_requested"] = state.get("escalation_requested", False)
    existing["updated_at"] = datetime.utcnow().isoformat()
    existing["lead_persisted"] = True

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, default=str)
