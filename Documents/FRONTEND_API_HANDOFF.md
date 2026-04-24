# Stark Digital — Sales AI Consultant (V1)
# Frontend API Handoff

**Base URL (production):** `https://salesai.reviewtestlink.com`

This document lists the backend endpoints the frontend integrates with, plus the streaming (SSE) contract and common error/ops notes.

---

## Endpoints (summary)

- **Health**
  - `GET /health`
- **Session**
  - `POST /session/create`
  - `GET /session/config`
  - `GET /session/{session_id}`
  - `POST /session/profile`
  - `POST /session/end`
- **Chat (Server-Sent Events)**
  - `POST /chat/message`
- **Conversation Viewer (HTML page)**
  - `GET /conversation/{session_id}` *(not an API JSON response; returns HTML)*

---

## Base URLs

- **API base**: `https://salesai.reviewtestlink.com`
- **OpenAPI / Swagger (for reference)**:
  - `https://salesai.reviewtestlink.com/docs`
  - `https://salesai.reviewtestlink.com/openapi.json`

---

## Data model basics

### `session_id`
- Returned from `POST /session/create`
- Must be provided by the frontend on every chat/session call.
- Format: UUID (server uses UUID v4).

---

## Health

### `GET /health`

**Purpose**
- Load balancer / uptime checks.

**Response (200)**

```json
{ "status": "ok" }
```

---

## Session

### `POST /session/create`

**Purpose**
- Create a new session in Redis and return timing values for inactivity UX.

**Request**
- No body.

**Response (200)**

```json
{
  "session_id": "8fddb431-48ce-472a-b482-3a95ddaf4a69",
  "inactivity_prompt_minutes": 10,
  "inactivity_end_minutes": 20
}
```

**Source**
- Request/response schema: `backend/app/models/schemas.py` (`CreateSessionResponse`)
- Route: `backend/app/api/routes/session.py`

---

### `GET /session/config`

**Purpose**
- Fetch UI config used by the widget (consultant/company name + inactivity timers).

**Response (200)**

```json
{
  "inactivity_prompt_minutes": 10,
  "inactivity_end_minutes": 20,
  "consultant_name": "Alex",
  "company_name": "Stark Digital"
}
```

**Source**
- Schema: `SessionConfigResponse` (`backend/app/models/schemas.py`)

---

### `GET /session/{session_id}`

**Purpose**
- Lightweight session metadata (useful for debugging or session existence checks).

**Response (200)**

```json
{
  "session_id": "8fddb431-48ce-472a-b482-3a95ddaf4a69",
  "created_at": "2026-04-21T11:33:54.519205",
  "last_active": "2026-04-21T11:35:01.019205",
  "conversation_stage": "GREETING"
}
```

**Errors**
- `404` if session not found (expired TTL or wrong id).

---

### `POST /session/profile`

**Purpose**
- Persist visitor profile fields for lead delivery (HubSpot/Sheets/email).
- Backend **will not overwrite non-empty existing values**.

**Request**

```json
{
  "session_id": "8fddb431-48ce-472a-b482-3a95ddaf4a69",
  "name": "Brenden Mcclum",
  "email": "brenden@example.com",
  "phone": "+1 234 567 8910",
  "location": "US"
}
```

All fields except `session_id` are optional. (Schema: `SaveProfileRequest`)

**Response (200)**

```json
{ "status": "saved" }
```

**Errors**
- `404` if session not found.

---

### `POST /session/end`

**Purpose**
- Marks session ended and triggers “lead delivery” pipeline (HubSpot note + local persistence + email + optional Sheets).

**Request**

```json
{
  "session_id": "8fddb431-48ce-472a-b482-3a95ddaf4a69"
}
```

**Response (200)**

```json
{ "status": "ended" }
```

**Notes**
- This route is idempotent: if the session key is missing, it still returns `{ "status": "ended" }`.

---

## Chat (SSE streaming)

### `POST /chat/message`

**Purpose**
- Send one user message and stream the assistant reply back as Server-Sent Events.

**Request**

```json
{
  "session_id": "8fddb431-48ce-472a-b482-3a95ddaf4a69",
  "message": "Hi, I need help generating more B2B leads."
}
```

**Response**
- Content-Type: `text/event-stream`
- The server streams multiple `data: ...\n\n` events.

### SSE event types

Frontend should parse each `data:` payload as JSON. Events include:

#### 1) Token events (streamed text)

```json
{ "type": "token", "token": "Hello! " }
```

The frontend should append `token` to the current assistant message buffer.

#### 2) Sources event (optional)

Emitted after streaming text if the assistant collected sources (e.g., website research).

```json
{
  "type": "sources",
  "agent": "discovery",
  "sources": [
    { "title": "About", "url": "https://example.com/about" }
  ]
}
```

#### 3) Usage event (always emitted at end)

```json
{
  "type": "usage",
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "this_call": {
    "input_tokens": 123,
    "output_tokens": 456,
    "total_tokens": 579,
    "estimated_cost_usd": 0.0012,
    "estimated_cost_inr": 0.10
  },
  "session": {
    "total_input_tokens": 1000,
    "total_output_tokens": 2500,
    "total_tokens": 3500,
    "estimated_cost_usd": 0.0102,
    "estimated_cost_inr": 0.86,
    "usd_to_inr_rate": 94.65
  }
}
```

#### 4) Done event (always emitted at end)

```json
{ "type": "done", "session_id": "8fddb431-48ce-472a-b482-3a95ddaf4a69" }
```

#### 5) Error event (on failure)

```json
{ "type": "error", "message": "Something went wrong. Please try again." }
```

### Important streaming notes

- **The frontend must not expect a single JSON response body.** This is SSE.
- Use `fetch()` + `ReadableStream` or `EventSource`-style parsing (note: this is a POST stream, so typical `EventSource` won’t work without a proxy).
- The backend adds headers to reduce buffering:
  - `Cache-Control: no-cache`
  - `X-Accel-Buffering: no`
  - `Connection: keep-alive`

**Errors**
- `404` session not found
- `409` session ended
- `429` rate limit exceeded (see below)

---

## Conversation viewer (HTML)

### `GET /conversation/{session_id}`

**Purpose**
- A human-readable transcript page used in HubSpot notes/emails.
- Returns HTML (not JSON), meant to open in a browser.

**Example**
- `https://salesai.reviewtestlink.com/conversation/8fddb431-48ce-472a-b482-3a95ddaf4a69`

**Notes**
- Only accepts UUIDv4-looking IDs (server rejects invalid IDs).
- Requires the session JSON archive file to exist for that session id; if not found, returns 404 HTML.

---

## Common HTTP error handling

- **`404`**: session does not exist (expired, wrong id, or Redis wiped)
- **`409`**: session was ended (chat blocked)
- **`429`**: rate limit exceeded
- **`5xx`**: server error (frontend should show “try again” + keep session id)

---

## Rate limiting (backend middleware)

- Window: **60 seconds**
- Max: **120 requests per client IP per window**
- Excludes: `/health`
- On exceed: `429` with body `Rate limit exceeded`

Frontend guidance:
- If you stream tokens, avoid firing multiple `/chat/message` calls concurrently from the same browser.
- Backoff on 429 (e.g., wait 2–5 seconds and retry).

---

## CORS / browser integration notes

- CORS allowlist is configured by backend env `CORS_ORIGINS`.
- If your widget is served from a different domain, add that origin to `CORS_ORIGINS` for browser calls.

---

## Recommended frontend flow

1. **Init**
   - `POST /session/create` → store `session_id`
   - `GET /session/config` → show consultant/company names + inactivity timers
2. **Chat**
   - `POST /chat/message` (SSE) → build assistant response from token events
3. **Profile capture (as soon as you have it)**
   - `POST /session/profile` (name/email/phone/location)
4. **End session**
   - `POST /session/end` (triggers lead delivery)

---

## Quick “copy/paste” full URLs

- `https://salesai.reviewtestlink.com/health`
- `https://salesai.reviewtestlink.com/session/create`
- `https://salesai.reviewtestlink.com/session/config`
- `https://salesai.reviewtestlink.com/session/{session_id}`
- `https://salesai.reviewtestlink.com/session/profile`
- `https://salesai.reviewtestlink.com/session/end`
- `https://salesai.reviewtestlink.com/chat/message`
- `https://salesai.reviewtestlink.com/conversation/{session_id}`

