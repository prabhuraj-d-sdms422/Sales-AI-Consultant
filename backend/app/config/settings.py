from pathlib import Path
from typing import ClassVar, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Load the root repo `.env` no matter where the server is started from.
    repo_root: ClassVar[Path] = Path(__file__).resolve().parents[3]
    model_config = SettingsConfigDict(
        env_file=str(repo_root / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True
    cors_origins: str = "http://localhost:5173"

    # LLM
    llm_provider: Literal["anthropic", "openai", "gemini"] = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    llm_temperature: float = 0.3
    # Max *generated* tokens per model call. Too low → replies stop mid-sentence/word.
    # Override with LLM_MAX_TOKENS in .env (e.g. 4096 for long solution-advisor turns).
    llm_max_tokens: int = 4096
    llm_streaming: bool = True

    # Pricing / cost estimation
    # NOTE: Token counts come from provider usage metadata (real). Only USD->INR conversion depends on this rate.
    usd_to_inr_rate: float = 83.5

    # Vector DB (abstraction only — not called in V1)
    vector_db_provider: Literal["pinecone", "pgvector"] = "pinecone"
    pinecone_api_key: str = ""
    pinecone_environment: str = ""
    pinecone_index_name: str = "stark-ai-consultant"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    redis_ttl_seconds: int = 86400

    # Guardrails
    intent_confidence_threshold: float = 0.70
    stream_token_buffer: int = 20

    # Google Sheets — lead tracker (Phase 2 style, safe optional)
    # If disabled or missing config, the app will keep writing local Excel only.
    google_sheets_enabled: bool = False
    google_sheets_credentials_file: str = "credentials/google_sheets_credentials.json"
    google_sheets_spreadsheet_id: str = ""
    google_sheets_worksheet_name: str = "Leads"

    # SendGrid — lead notifications (after JSON + Excel save). Leave API key empty to disable.
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""
    sendgrid_from_name: str = "Stark Digital AI Sales Consultant"
    sendgrid_to_email: str = ""  # comma-separated recipient addresses
    sendgrid_sandbox_mode: bool = False  # True = SendGrid accepts but does not deliver (testing)

    # HubSpot CRM — optional; Private App access token (not OAuth in .env for server-side)
    hubspot_enabled: bool = False
    hubspot_access_token: str = ""
    # Portal / Hub ID from your HubSpot URL: app.hubspot.com/contacts/<PORTAL>/...
    # Accept a common typo too (UBSPOT_PORTAL_ID) so prod doesn't silently miss links.
    hubspot_portal_id: str = Field(
        default="",
        validation_alias=AliasChoices("HUBSPOT_PORTAL_ID", "UBSPOT_PORTAL_ID"),
    )

    # Identity
    consultant_name: str = "Alex"
    company_name: str = "Stark Digital"
    sales_phone_number: str = ""
    session_timeout_minutes: int = 30
    save_conversations_enabled: bool = False

    # Public base URL of this server — used to build conversation viewer links
    # in emails, Google Sheets, and HubSpot notes.
    # Set to your deployed domain in production, e.g. https://api.yourdomain.com
    app_base_url: str = "http://localhost:8000"

    # Inactivity UX (frontend timers; backend sweep uses session_timeout_minutes)
    inactivity_prompt_minutes: int = Field(
        default=10,
        validation_alias=AliasChoices("INACTIVITY_PROMPT_MINUTES"),
    )
    inactivity_end_minutes: int = Field(
        default=20,
        validation_alias=AliasChoices("INACTIVITY_END_MINUTES"),
    )

    # Output guardrail — competitor names (lowercase), comma-separated in env
    competitor_names_blocklist: str = "tcs,infosys,wipro,accenture,cognizant"

    # RAG — Pinecone similarity search
    # all-MiniLM-L6-v2 cosine scores range 0.5-0.75 even for strong matches.
    # 0.55 filters irrelevant results while capturing spot-on domain matches.
    rag_similarity_threshold: float = 0.55
    rag_top_k: int = 3

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors(cls, v: str | list[str]) -> str:
        if isinstance(v, list):
            return ",".join(v)
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
