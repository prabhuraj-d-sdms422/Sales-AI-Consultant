"""Human-readable conversation viewer — renders a styled HTML chat page."""

import html as html_lib
import json
import re
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config.settings import settings

router = APIRouter()

CONVERSATIONS_DIR = Path(settings.repo_root) / "backend" / "data" / "Conversations"

# Only allow valid UUID4 format to prevent path traversal
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _fmt_dt(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%B %d, %Y at %I:%M %p UTC")
    except Exception:
        return ts or "—"


def _render_html(data: dict) -> str:
    session_id = html_lib.escape(str(data.get("session_id", "")))
    updated_at = _fmt_dt(data.get("updated_at", ""))
    messages: list[dict] = data.get("messages", [])
    token_usage: dict = data.get("token_usage") or {}
    company = html_lib.escape(settings.company_name)
    consultant = html_lib.escape(settings.consultant_name)

    # ── Build message bubbles ────────────────────────────────────────────────
    bubble_parts: list[str] = []
    for msg in messages:
        msg_type = (msg.get("type") or "").lower()
        content = (msg.get("content") or "").strip()
        if not content:
            continue

        esc = html_lib.escape(content)
        # Render **bold** markdown
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        esc = esc.replace("\n", "<br>")

        if msg_type == "human":
            bubble_parts.append(
                f'<div class="msg-row human-row">'
                f'<div class="bubble human-bubble">'
                f'<div class="sender">Visitor</div>'
                f'<div class="body">{esc}</div>'
                f"</div></div>"
            )
        elif msg_type == "ai":
            bubble_parts.append(
                f'<div class="msg-row ai-row">'
                f'<div class="bubble ai-bubble">'
                f'<div class="sender">{consultant} &middot; AI Consultant</div>'
                f'<div class="body">{esc}</div>'
                f"</div></div>"
            )

    if not bubble_parts:
        messages_html = '<p class="empty">No messages recorded for this session.</p>'
    else:
        messages_html = "\n".join(bubble_parts)

    msg_count = len([m for m in messages if (m.get("content") or "").strip()])

    # ── Token usage card ────────────────────────────────────────────────────
    token_card = ""
    if token_usage:
        model = html_lib.escape(str(token_usage.get("model", "")))
        total = token_usage.get("total_tokens", 0)
        cost_usd = token_usage.get("estimated_cost_usd", 0)
        cost_inr = token_usage.get("estimated_cost_inr", 0)
        token_card = f"""
        <div class="info-card">
            <div class="info-title">Session Details</div>
            <table class="info-table">
                <tr><td>AI Model</td><td>{model}</td></tr>
                <tr><td>Total tokens used</td><td>{total:,}</td></tr>
                <tr><td>Estimated cost</td><td>${cost_usd:.4f} &nbsp;(&#8377;{cost_inr:.2f})</td></tr>
            </table>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Conversation &mdash; {company}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                   'Helvetica Neue', Arial, sans-serif;
      background: #eef0f3;
      color: #111827;
      min-height: 100vh;
    }}

    /* ── Header ─────────────────────────────────────────────── */
    .top-bar {{
      background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
      color: #fff;
      padding: 20px 28px;
      position: sticky;
      top: 0;
      z-index: 50;
      box-shadow: 0 2px 16px rgba(0,0,0,.35);
    }}
    .top-bar h1 {{
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -.2px;
    }}
    .top-bar .sub {{
      font-size: .78rem;
      opacity: .7;
      margin-top: 3px;
    }}
    .badge {{
      display: inline-block;
      background: rgba(255,255,255,.15);
      border-radius: 20px;
      padding: 2px 10px;
      font-size: .72rem;
      margin-left: 8px;
      vertical-align: middle;
    }}

    /* ── Layout ─────────────────────────────────────────────── */
    .page {{
      max-width: 820px;
      margin: 0 auto;
      padding: 28px 16px 48px;
    }}

    /* ── Chat card ───────────────────────────────────────────── */
    .chat-card {{
      background: #fff;
      border-radius: 16px;
      box-shadow: 0 4px 24px rgba(0,0,0,.08);
      overflow: hidden;
    }}
    .chat-card-header {{
      padding: 16px 24px;
      border-bottom: 1px solid #f0f0f4;
      background: #fafafa;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .chat-card-header .label {{
      font-weight: 600;
      font-size: .95rem;
    }}
    .chat-card-header .date {{
      font-size: .78rem;
      color: #9ca3af;
    }}

    /* ── Messages ───────────────────────────────────────────── */
    .messages {{
      padding: 24px 20px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }}
    .msg-row {{ display: flex; }}
    .human-row {{ justify-content: flex-end; }}
    .ai-row    {{ justify-content: flex-start; }}

    .bubble {{
      max-width: 75%;
      padding: 11px 15px;
      border-radius: 16px;
      font-size: .9rem;
      line-height: 1.6;
      word-wrap: break-word;
    }}
    .human-bubble {{
      background: #1e3a5f;
      color: #fff;
      border-bottom-right-radius: 4px;
    }}
    .ai-bubble {{
      background: #f3f4f6;
      color: #111827;
      border: 1px solid #e5e7eb;
      border-bottom-left-radius: 4px;
    }}
    .sender {{
      font-size: .68rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .5px;
      margin-bottom: 5px;
      opacity: .6;
    }}
    .body {{ white-space: pre-wrap; word-break: break-word; }}

    .empty {{
      text-align: center;
      color: #9ca3af;
      padding: 40px 20px;
      font-size: .9rem;
    }}

    /* ── Info card ───────────────────────────────────────────── */
    .info-card {{
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 2px 12px rgba(0,0,0,.06);
      padding: 20px 24px;
      margin-top: 18px;
    }}
    .info-title {{
      font-size: .78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: .6px;
      color: #6b7280;
      margin-bottom: 12px;
    }}
    .info-table {{ width: 100%; border-collapse: collapse; font-size: .86rem; }}
    .info-table tr td {{
      padding: 5px 0;
      vertical-align: top;
    }}
    .info-table tr td:first-child {{
      color: #6b7280;
      width: 160px;
      padding-right: 12px;
    }}
    .info-table tr td:last-child {{ font-weight: 500; }}

    /* ── Footer ─────────────────────────────────────────────── */
    .footer {{
      text-align: center;
      font-family: monospace;
      font-size: .72rem;
      color: #9ca3af;
      margin-top: 22px;
      padding-bottom: 4px;
    }}

    @media (max-width: 600px) {{
      .bubble {{ max-width: 90%; }}
      .page {{ padding: 16px 8px 40px; }}
      .chat-card-header {{ flex-direction: column; align-items: flex-start; gap: 4px; }}
    }}

    @media print {{
      .top-bar {{ position: static; }}
      body {{ background: #fff; }}
      .chat-card, .info-card {{ box-shadow: none; border: 1px solid #ddd; }}
    }}
  </style>
</head>
<body>
  <div class="top-bar">
    <h1>{company} &mdash; Conversation Transcript</h1>
    <div class="sub">
      {html_lib.escape(updated_at)}
      <span class="badge">{msg_count} messages</span>
    </div>
  </div>

  <div class="page">
    <div class="chat-card">
      <div class="chat-card-header">
        <span class="label">Full Conversation</span>
        <span class="date">{html_lib.escape(updated_at)}</span>
      </div>
      <div class="messages">
        {messages_html}
      </div>
    </div>

    {token_card}

    <div class="footer">Session ID: {session_id}</div>
  </div>
</body>
</html>"""


# ── Route ────────────────────────────────────────────────────────────────────

@router.get(
    "/conversation/{session_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
    summary="View conversation transcript",
)
async def view_conversation(session_id: str) -> HTMLResponse:
    if not _UUID_RE.match(session_id):
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:60px;text-align:center'>"
            "<h2>Invalid session ID</h2></body></html>",
            status_code=400,
        )

    file_path = CONVERSATIONS_DIR / f"{session_id}.json"
    if not file_path.exists():
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:60px;text-align:center'>"
            "<h2 style='color:#374151'>Conversation not found</h2>"
            "<p style='color:#6b7280;margin-top:8px'>This conversation may have expired or the link is invalid.</p>"
            "</body></html>",
            status_code=404,
        )

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return HTMLResponse(content=_render_html(data), status_code=200)
    except Exception:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:60px;text-align:center'>"
            "<h2>Error loading conversation</h2></body></html>",
            status_code=500,
        )
