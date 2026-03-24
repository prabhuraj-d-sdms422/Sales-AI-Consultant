"""V1: Appends lead row to local Excel. Phase 2: Replace with Google Sheets API."""

import os
from datetime import datetime

from openpyxl import Workbook, load_workbook

from app.models.state import ConversationState

EXCEL_PATH = "data/leads.xlsx"
HEADERS = [
    "Timestamp",
    "Lead Temp",
    "Name",
    "Company",
    "Email",
    "Phone",
    "Industry",
    "Problem",
    "Budget Signal",
    "Urgency",
    "Decision Maker",
    "Solutions Discussed",
    "Objections Raised",
    "Stage",
    "Session ID",
]


async def append_lead_locally(state: ConversationState) -> None:
    os.makedirs("data", exist_ok=True)
    profile = state.get("client_profile", {})
    row = [
        datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        str(state.get("lead_temperature", "cold")).upper(),
        profile.get("name", ""),
        profile.get("company", ""),
        profile.get("email", ""),
        profile.get("phone", ""),
        profile.get("industry", ""),
        profile.get("problem_understood") or profile.get("problem_raw", ""),
        profile.get("budget_signal", ""),
        profile.get("urgency", ""),
        str(profile.get("decision_maker", "")),
        ", ".join(state.get("solutions_discussed", []) or []),
        ", ".join(state.get("objections_raised", []) or []),
        state.get("conversation_stage", ""),
        state.get("session_id", ""),
    ]
    if os.path.exists(EXCEL_PATH):
        wb = load_workbook(EXCEL_PATH)
        ws = wb.active
    else:
        wb = Workbook()
        ws = wb.active
        ws.append(HEADERS)
    ws.append(row)
    wb.save(EXCEL_PATH)
