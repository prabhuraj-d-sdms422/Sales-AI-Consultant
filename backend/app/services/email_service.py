"""Lead snapshots: local JSON + optional SendGrid email to sales after Excel row is written."""

import asyncio
import html
import json
import logging
import os
from datetime import datetime

from app.config.settings import settings
from app.models.state import ConversationState

LEADS_DIR = "data/leads"
logger = logging.getLogger(__name__)


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


def _lead_notification_bodies(state: ConversationState) -> tuple[str, str]:
    """Plain text and HTML bodies for the sales notification."""
    profile = dict(state.get("client_profile") or {})
    session_id = state.get("session_id", "")

    def esc(s: object) -> str:
        return html.escape(str(s) if s is not None else "")

    lines = [
        ("Session ID", session_id),
        ("Saved (UTC)", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")),
        ("Lead temperature", state.get("lead_temperature", "")),
        ("Stage", state.get("conversation_stage", "")),
        ("Escalation requested", str(state.get("escalation_requested", False))),
        ("Name", profile.get("name", "")),
        ("Company", profile.get("company", "")),
        ("Email", profile.get("email", "")),
        ("Phone", profile.get("phone", "")),
        ("Industry", profile.get("industry", "")),
        ("Problem", profile.get("problem_understood") or profile.get("problem_raw", "")),
        ("Budget signal", profile.get("budget_signal", "")),
        ("Urgency", profile.get("urgency", "")),
        ("Solutions discussed", ", ".join(state.get("solutions_discussed", []) or [])),
        ("Objections raised", ", ".join(state.get("objections_raised", []) or [])),
    ]
    plain = "\n".join(f"{k}: {v}" for k, v in lines)
    rows = "".join(f"<tr><th align='left'>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in lines)
    html_body = (
        f"<h2>New lead — {esc(settings.company_name)}</h2>"
        f"<p>A new row was added to <code>data/leads.xlsx</code>.</p>"
        f"<table border='1' cellpadding='6' cellspacing='0'>{rows}</table>"
    )
    return plain, html_body


def _send_sendgrid_sync(plain: str, html_body: str, session_id: str) -> None:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Email, Mail, MailSettings, SandBoxMode, To

    recipients = [x.strip() for x in settings.sendgrid_to_email.split(",") if x.strip()]
    if not recipients:
        return

    to_list = [To(addr) for addr in recipients]
    from_email: Email | str
    if settings.sendgrid_from_name:
        from_email = Email(settings.sendgrid_from_email, settings.sendgrid_from_name)
    else:
        from_email = settings.sendgrid_from_email

    sid_short = (session_id or "")[:12]
    subject = f"[{settings.company_name}] New lead — {sid_short}"

    message = Mail(
        from_email=from_email,
        to_emails=to_list,
        subject=subject,
        plain_text_content=plain,
        html_content=html_body,
    )
    if settings.sendgrid_sandbox_mode:
        mail_settings = MailSettings()
        mail_settings.sandbox_mode = SandBoxMode(enable=True)
        message.mail_settings = mail_settings

    sg = SendGridAPIClient(settings.sendgrid_api_key)
    response = sg.send(message)
    if response.status_code not in (200, 201, 202):
        logger.warning(
            "SendGrid non-success status=%s body=%s",
            response.status_code,
            response.body,
        )


async def notify_sales_lead_captured(state: ConversationState) -> None:
    """
    Send email via SendGrid after lead JSON + Excel persist.
    No-op when SENDGRID_API_KEY, SENDGRID_FROM_EMAIL, or SENDGRID_TO_EMAIL is missing.
    """
    if not (
        settings.sendgrid_api_key
        and settings.sendgrid_from_email.strip()
        and settings.sendgrid_to_email.strip()
    ):
        return

    plain, html_body = _lead_notification_bodies(state)
    session_id = str(state.get("session_id", ""))

    await asyncio.to_thread(_send_sendgrid_sync, plain, html_body, session_id)
    logger.info("SendGrid lead notification sent | session=%s", session_id)
