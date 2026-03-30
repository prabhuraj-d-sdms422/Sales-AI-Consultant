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

## Installation and setup (step by step)

### Prerequisites

- **Python** 3.11+ (recommended: install `python3.11-venv` on Ubuntu so `python3 -m venv` includes `pip`; if `ensurepip` fails, create the venv with `python3 -m venv venv --without-pip` and bootstrap pip with [get-pip.py](https://bootstrap.pypa.io/get-pip.py)).
- **Node.js** 18+ (for the frontend).
- **Docker** (optional but recommended for Redis via Compose).

### 1. Clone and Python virtual environment

From the repository root:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` pins **`transformers` 4.x** on purpose: the Guardrails Hub **DetectJailbreak** validator downloads a Hugging Face model whose config is incompatible with **transformers 5.x** strict validation. Do not upgrade `transformers` to 5.x unless upstream fixes that model or the validator.

### 2. Application environment variables (`.env`)

Copy the example file to `.env` at the **repository root** (the backend loads it via `app.config.settings`). If you are still in `backend/` after step 1:

```bash
cd ..                  # repository root
cp .env.example .env
```

Edit `.env` and set at least the keys for the LLM provider you use (`LLM_PROVIDER` is `anthropic`, `openai`, or `gemini`).

| Variable | Purpose |
|----------|---------|
| `LLM_PROVIDER` | Which LLM backend to use: `anthropic`, `openai`, or `gemini`. |
| `ANTHROPIC_API_KEY` | API key from [Anthropic Console](https://console.anthropic.com/) (if using Claude). |
| `OPENAI_API_KEY` | API key from [OpenAI](https://platform.openai.com/) (if using OpenAI). |
| `GEMINI_API_KEY` | API key from [Google AI Studio](https://aistudio.google.com/) (if using Gemini). |
| `REDIS_HOST`, `REDIS_PORT` | Must match your Redis instance (see below). |
| `CORS_ORIGINS` | Frontend origins, e.g. `http://localhost:5173`. |
| `COMPETITOR_NAMES_BLOCKLIST` | Optional; comma-separated lowercase names for output **CompetitorCheck** (defaults exist in code if omitted). |

Optional / Phase 2: `PINECONE_*`, `SENDGRID_*`, etc., as described in `.env.example`.

**Security:** never commit `.env`, never paste real keys into tickets or chat logs. Rotate any key that may have been exposed.

### 3. Guardrails Hub API key (CLI — separate from `.env`)

Hub validators (`toxic_language`, `detect_jailbreak`, `competitor_check`) are installed with the **Guardrails CLI**. Installing from the Hub requires a **Guardrails Hub API key**, not your LLM keys.

1. Create or copy an API key from **[Guardrails Hub — API keys](https://guardrailsai.com/hub/keys)**.
2. With the backend venv **activated**, run:

   ```bash
   guardrails configure
   ```

3. Paste your API key when prompted (you can enable or disable remote inferencing and metrics as you prefer).

If `guardrails hub install` returns **401 Unauthorized** or **invalid token**, run `guardrails configure` again with a fresh key.

### 4. Optional: Hugging Face token (model downloads)

During Hub install, models are downloaded from the **Hugging Face Hub**. Without a token you may see rate-limit warnings. To use higher limits:

1. Create a token at **[Hugging Face — Settings → Access Tokens](https://huggingface.co/settings/tokens)**.
2. Before running the install script (same shell session):

   ```bash
   export HF_TOKEN=hf_your_token_here
   ```

   On Windows (cmd): `set HF_TOKEN=hf_your_token_here`.

### 5. Install Guardrails Hub validators (large download)

From the **repository root** (not `backend/`), with the venv activated and `guardrails` on your `PATH`:

```bash
bash scripts/install_guardrails_hub.sh
```

This installs `toxic_language`, `detect_jailbreak`, and `competitor_check`, and updates `.guardrails/hub_registry.json`. Expect large downloads (PyTorch, transformer weights).

**Troubleshooting**

- **`StrictDataclassFieldValidationError` / `id2label`**: your environment pulled **transformers 5.x**. Reinstall deps from `backend/requirements.txt` so `transformers>=4.46,<5.0`, then run the script again.
- **`401` / Unauthorized** from Guardrails: run `guardrails configure` with a valid Hub API key (section 3).

### 6. Redis

Sessions require Redis. If you use the bundled **Docker** service from the repo root:

```bash
docker compose up -d redis
```

`docker-compose.yml` maps the container to the host as **`6381` → 6379** (`"6381:6379"`). If you run **uvicorn on your machine** (not inside the `backend` container), set in `.env`:

- `REDIS_HOST=localhost`
- `REDIS_PORT=6381`

If you use a **local** `redis-server` on the default port instead, use `REDIS_PORT=6379`.

**`Connection refused` / `Error 111 connecting to localhost:6380` (or another port):** either Redis is not running, or `REDIS_PORT` does not match where Redis listens. Start Redis (`docker compose up -d redis` or your OS service), then align `.env`. Verify with `redis-cli -p 6381 ping` (or your chosen port) — expect `PONG`.

### 6.1 Google Sheets (optional lead tracker)

By default we write captured leads to **local Excel** (`backend/data/leads.xlsx`). If you want a live, shareable tracker, you can also append the same lead row to a **Google Sheet**.

#### A. Google Cloud setup

- Create / pick a Google Cloud project
- Enable **Google Sheets API**
- Create a **Service Account** and download its JSON key file
- Create a Google Sheet (or choose one) and copy its **Spreadsheet ID** from the URL
- Share the sheet with the service account’s `client_email` (from the JSON) as **Editor**

#### B. Put credentials in the repo (never commit)

Place the JSON at (default):

- `credentials/google_sheets_credentials.json`

This folder is ignored by git via `.gitignore`.

#### C. Configure `.env`

```env
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SHEETS_CREDENTIALS_FILE=credentials/google_sheets_credentials.json
GOOGLE_SHEETS_SPREADSHEET_ID=your_spreadsheet_id_here
GOOGLE_SHEETS_WORKSHEET_NAME=Leads
```

#### D. What happens at runtime

When a lead is captured, the backend will:

- save JSON in `backend/data/leads/{session_id}.json`
- append a row in `backend/data/leads.xlsx`
- **append the same row to Google Sheets** (best-effort; failures are logged, local files are still saved)

### 7. Run the backend

From `backend/` with `PYTHONPATH` set so `app` resolves:

```bash
cd backend
source venv/bin/activate
export PYTHONPATH=.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 8. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. If the API is not on `http://localhost:8000`, set `VITE_API_URL` accordingly.

---

## Quick reference (after first-time setup)

1. **Redis**: `docker compose up -d redis` (if using Compose).
2. **Backend**: `cd backend && source venv/bin/activate && export PYTHONPATH=. && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
3. **Frontend**: `cd frontend && npm run dev`

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
