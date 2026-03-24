# AI Sales Consultant (Stark Digital)

V1 implementation per **AI_Sales_Consultant_Cursor_Plan_v5**: multi-agent **LangGraph** sales flow, **FastAPI** + **SSE** streaming, **Redis** session state, leads in **local JSON** + **Excel** (`openpyxl`). No PostgreSQL / SendGrid / Google Sheets / Calendly in V1.

## What you’re building

- **Orchestrator**: intent + routing (no user-facing text).
- **Discovery** (conversational + structured), **Solution Advisor**, **Objection Handler**, **Conversion** (+ escalation phone).
- **Case study** agent: scaffold only (dormant).
- **Guardrails (Phase 1)**: input uses Guardrails-AI validators (`ToxicLanguage`, `DetectJailbreak`) (no LLM calls); output uses deterministic currency regex + Guardrails-AI `CompetitorCheck` (no Stage-2 LLM validation).
- **Demo UI**: React + Vite + Tailwind (`frontend/`).

## Performance / UX targets (V1)

- **Streaming**: responses streamed over **SSE** in small chunks (`STREAM_TOKEN_BUFFER`, default 20).
- **Intent confidence**: below `INTENT_CONFIDENCE_THRESHOLD` (default 0.70) → treat as `LOW_CONFIDENCE` and route to discovery.
- **Session TTL**: Redis `REDIS_TTL_SECONDS` (default 24h).

## Quick start (local)

1. **Redis** (required for sessions):

   ```bash
   docker compose up -d redis
   ```

2. **Backend** (from repo root):

   ```bash
   cd backend
   python -m venv ../venv && source ../venv/bin/activate  # or use your venv
   pip install -r requirements.txt
   cp ../.env.example ../.env   # if you don’t already have .env
   export PYTHONPATH=.
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Frontend**:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

4. Open `http://localhost:5173` — set `VITE_API_URL` if the API is not on `http://localhost:8000`.

## Tests

```bash
cd backend
PYTHONPATH=. pytest tests/ -v
```

Uses **fakeredis** in `tests/conftest.py` so tests don’t require a live Redis.

## Docker (full stack)

- **Dev**: `docker compose up` — Redis, backend (reload), Vite dev server.
- **Prod-style**: `docker compose -f docker-compose.prod.yml up --build`

## Critical V1 rules (from the plan)

- Use **`settings`** (`app.config.settings`) — do not read `os.environ` directly in app code.
- **Escalation**: use **`SALES_PHONE_NUMBER`** only — no `booking_link` in V1.
- **Leads**: `persist_lead_incrementally()` after agent turns; escalation triggers **JSON + Excel** snapshot/append via `email_service` / `sheets_service`.
- **Do not** route to **case_study** in production orchestration (graph supports it but prompts restrict `next_agent`).

## Phase 2 (deferred)

PostgreSQL, SendGrid, Google Sheets, Calendly, RAG/Pinecone for advisors — see plan Section 21.
