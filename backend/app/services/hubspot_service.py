"""HubSpot CRM — create/update contacts and attach a note (problem + solutions) on lead capture."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config.settings import settings
from app.models.state import ConversationState
from app.services.conversation_archive_service import render_transcript_txt

logger = logging.getLogger(__name__)

HUBSPOT_API = "https://api.hubapi.com"
# Note → Contact (HubSpot-defined association)
NOTE_TO_CONTACT_ASSOCIATION_TYPE_ID = 202


def _split_name(full: str) -> tuple[str, str]:
    full = (full or "").strip()
    if not full:
        return "", ""
    parts = full.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _contact_record_url(contact_id: str) -> str | None:
    portal = (settings.hubspot_portal_id or "").strip()
    if not portal or not contact_id:
        return None
    return f"https://app.hubspot.com/contacts/{portal}/record/0-1/{contact_id}"


def _build_note_html(state: ConversationState) -> str:
    profile = dict(state.get("client_profile") or {})
    location = str(profile.get("location") or "").strip()
    problem = (
        profile.get("problem_understood")
        or profile.get("problem_raw")
        or ""
    )
    insights = state.get("conversation_insights") or {}
    all_problems = list(insights.get("all_problems") or state.get("problems_identified") or [])
    all_solutions = list(insights.get("all_solutions") or state.get("solutions_discussed") or [])
    key_metrics = list(insights.get("key_metrics") or [])
    client_context = str(insights.get("client_context") or "")

    solutions = ", ".join(state.get("solutions_discussed", []) or [])
    session_id = str(state.get("session_id", "") or "")
    parts: list[str] = []

    def _p(label: str, value: object) -> None:
        esc_label = html.escape(label)
        esc_val = html.escape(str(value or ""))
        parts.append(f"<p><strong>{esc_label}</strong><br/>{esc_val}</p>")

    conversation_viewer_url = str(state.get("conversation_viewer_url") or "")

    _p("Session ID", session_id)
    if location:
        _p("Location", location)
    _p("Problem / context", str(problem))
    budget_signal = str(profile.get("budget_signal") or "").strip()
    if budget_signal:
        _p("Budget signal", budget_signal)
    urgency = str(profile.get("urgency") or "").strip()
    if urgency:
        _p("Urgency / timeline", urgency)
    _p("Solutions discussed", solutions)

    if client_context.strip():
        _p("Client context (summary)", client_context.strip())

    if all_problems:
        items = "".join(f"<li>{html.escape(str(x))}</li>" for x in all_problems if str(x).strip())
        if items:
            parts.append(f"<p><strong>Problems identified</strong></p><ol>{items}</ol>")

    if all_solutions:
        items = "".join(f"<li>{html.escape(str(x))}</li>" for x in all_solutions if str(x).strip())
        if items:
            parts.append(f"<p><strong>Solutions proposed</strong></p><ol>{items}</ol>")

    if key_metrics:
        items = "".join(f"<li>{html.escape(str(x))}</li>" for x in key_metrics if str(x).strip())
        if items:
            parts.append(f"<p><strong>Key metrics / facts</strong></p><ul>{items}</ul>")

    if conversation_viewer_url:
        esc_url = html.escape(conversation_viewer_url)
        parts.append(
            f"<p><strong>Full conversation transcript</strong><br/>"
            f"<a href='{esc_url}' target='_blank'>{esc_url}</a></p>"
        )

    # Inline plaintext transcript (collapsed) so sales can read it inside HubSpot.
    # Cap to avoid oversized notes.
    try:
        client_name = (profile.get("name") or "").strip() or "Client"
        transcript_txt = render_transcript_txt(
            messages=state.get("messages") or [],
            consultant_name=str(settings.consultant_name),
            client_name=client_name,
        )
        max_chars = 8000
        trimmed = transcript_txt[:max_chars].rstrip()
        if len(transcript_txt) > max_chars:
            trimmed += "\n\n[Transcript truncated — use the transcript link above for full conversation]\n"
        esc_transcript = html.escape(trimmed)
        parts.append(
            "<details>"
            "<summary><strong>Transcript (plaintext)</strong></summary>"
            f"<pre style='white-space:pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace;'>"
            f"{esc_transcript}"
            "</pre>"
            "</details>"
        )
    except Exception:
        pass

    return "\n".join(parts)


def _headers() -> dict[str, str]:
    token = (settings.hubspot_access_token or "").strip()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _search_contact_by_email(client: httpx.AsyncClient, email: str) -> str | None:
    email = (email or "").strip().lower()
    if not email:
        return None
    body = {
        "filterGroups": [
            {
                "filters": [
                    {
                        "propertyName": "email",
                        "operator": "EQ",
                        "value": email,
                    }
                ]
            }
        ],
        "properties": ["id", "email"],
        "limit": 1,
    }
    r = await client.post(
        f"{HUBSPOT_API}/crm/v3/objects/contacts/search",
        headers=_headers(),
        json=body,
    )
    if r.status_code != 200:
        logger.warning(
            "HubSpot contact search failed: status=%s body=%s",
            r.status_code,
            r.text[:500],
        )
        return None
    data = r.json()
    results = data.get("results") or []
    if not results:
        return None
    return str(results[0].get("id", ""))


async def _create_note_for_contact(
    client: httpx.AsyncClient, contact_id: str, note_body_html: str
) -> None:
    ts_ms = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    payload: dict[str, Any] = {
        "properties": {
            "hs_note_body": note_body_html,
            "hs_timestamp": ts_ms,
        },
        "associations": [
            {
                "to": {"id": str(contact_id)},
                "types": [
                    {
                        "associationCategory": "HUBSPOT_DEFINED",
                        "associationTypeId": NOTE_TO_CONTACT_ASSOCIATION_TYPE_ID,
                    }
                ],
            }
        ],
    }
    r = await client.post(
        f"{HUBSPOT_API}/crm/v3/objects/notes",
        headers=_headers(),
        json=payload,
    )
    if r.status_code not in (200, 201):
        logger.warning(
            "HubSpot note create failed: status=%s body=%s",
            r.status_code,
            r.text[:500],
        )


async def _upsert_contact_properties(
    client: httpx.AsyncClient,
    contact_id: str | None,
    properties: dict[str, str],
) -> str:
    if contact_id:
        r = await client.patch(
            f"{HUBSPOT_API}/crm/v3/objects/contacts/{contact_id}",
            headers=_headers(),
            json={"properties": properties},
        )
        if r.status_code == 200:
            return str(contact_id)
        logger.warning(
            "HubSpot contact PATCH failed: status=%s body=%s",
            r.status_code,
            r.text[:500],
        )
        return str(contact_id)

    r = await client.post(
        f"{HUBSPOT_API}/crm/v3/objects/contacts",
        headers=_headers(),
        json={"properties": properties},
    )
    if r.status_code not in (200, 201):
        logger.error(
            "HubSpot contact create failed: status=%s body=%s",
            r.status_code,
            r.text[:500],
        )
        return ""
    data = r.json()
    return str(data.get("id", ""))


async def sync_lead_to_hubspot(state: ConversationState) -> str | None:
    """
    Create or update a HubSpot contact and attach a note with problem + solutions.
    Returns a CRM record URL when portal id is configured, else None.
    """
    if not settings.hubspot_enabled:
        return None
    if not (settings.hubspot_access_token or "").strip():
        logger.warning("HubSpot enabled but HUBSPOT_ACCESS_TOKEN is empty.")
        return None

    profile = dict(state.get("client_profile") or {})
    email = (profile.get("email") or "").strip()
    phone = (profile.get("phone") or "").strip()
    name = (profile.get("name") or "").strip()
    company = (profile.get("company") or "").strip()
    location = (profile.get("location") or "").strip()

    if not email and not phone:
        logger.info(
            "HubSpot sync skipped: no email or phone | session=%s",
            state.get("session_id"),
        )
        return None

    first, last = _split_name(name)
    if not first:
        first = "Lead"

    properties: dict[str, str] = {
        "firstname": first,
        "lastname": last,
    }
    if company:
        properties["company"] = company
    if email:
        properties["email"] = email
    if phone:
        properties["phone"] = phone
    # Best-effort mapping; "city" is a standard HubSpot field but may not fit all formats.
    if location:
        properties["city"] = location

    async with httpx.AsyncClient(timeout=30.0) as client:
        contact_id: str | None = None
        if email:
            contact_id = await _search_contact_by_email(client, email)

        cid = await _upsert_contact_properties(client, contact_id, properties)
        if not cid:
            return None

        note_html = _build_note_html(state)
        await _create_note_for_contact(client, cid, note_html)

        return _contact_record_url(cid)


async def sync_lead_to_hubspot_safe(state: ConversationState) -> str | None:
    """Wrapper that never raises — logs and returns None on failure."""
    try:
        return await sync_lead_to_hubspot(state)
    except Exception as e:
        logger.exception("HubSpot sync failed: %s", e)
        return None
