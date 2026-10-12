import json
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-insecure-jwt-secret-change-me"
# Fixed by the document_chunks.embedding column; changing it needs a migration.
EMBEDDING_COLUMN_DIM = 1536


class Settings(BaseSettings):
    app_name: str = "ResolveAI API"
    environment: str = "development"
    debug: bool = True
    # Runtime role: no table ownership, no BYPASSRLS.
    database_url: str = (
        "postgresql+asyncpg://resolveai_app:resolveai_app@localhost:5432/resolveai"
    )
    # Owner role, used only by Alembic.
    migrations_database_url: str = (
        "postgresql+asyncpg://resolveai:resolveai@localhost:5432/resolveai"
    )
    test_database_url: str = (
        "postgresql+asyncpg://resolveai_app:resolveai_app@localhost:5432/resolveai_test"
    )
    test_migrations_database_url: str = (
        "postgresql+asyncpg://resolveai:resolveai@localhost:5432/resolveai_test"
    )
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]

    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    refresh_cookie_secure: bool = False

    # Knowledge ingestion. OPENAI_API_KEY is checked when the embedding client is built
    # (worker startup), so the API can run without it.
    openai_api_key: SecretStr | None = None
    embedding_provider: Literal["openai", "fake"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = EMBEDDING_COLUMN_DIM
    storage_backend: Literal["local"] = "local"
    local_storage_dir: str = "./storage"
    max_upload_mb: int = 20

    # Chat model. Nothing calls it yet; LLM_CHAT_MODEL is checked when a call is made.
    llm_provider: Literal["openai", "fake"] = "openai"
    llm_chat_model: str = ""
    # reasoning_effort sent with tool-calling requests. GPT-6 Sol/Luna only allow function
    # tools in Chat Completions with "none"; empty sends nothing (for models without "none").
    llm_tools_reasoning_effort: str = "none"

    # USD per million tokens, used to cost every row in llm_calls.
    embedding_price_per_mtok: Decimal = Decimal("0.02")
    llm_input_price_per_mtok: Decimal = Decimal(0)
    llm_output_price_per_mtok: Decimal = Decimal(0)

    # Retrieval: fetch top_k by cosine similarity, drop weak matches, keep the best few.
    retrieval_top_k: int = Field(default=8, ge=1, le=50)
    retrieval_min_score: float = Field(default=0.30, ge=-1.0, le=1.0)
    retrieval_keep: int = Field(default=5, ge=1, le=50)

    # Dev/demo only: lets workspace owners wipe conversations and the inbox from Settings.
    demo_tools_enabled: bool = False

    # Customer chat widget. The dev flag also allows http://localhost:3000 as a host origin.
    widget_dev_allow_localhost: bool = False
    widget_token_ttl_minutes: int = Field(default=60, ge=1, le=24 * 60)
    widget_conversation_rate_per_minute: int = Field(default=10, ge=1)
    widget_ip_rate_per_minute: int = Field(default=30, ge=1)
    widget_workspace_rate_per_minute: int = Field(default=300, ge=1)
    widget_session_ip_rate_per_minute: int = Field(default=20, ge=1)
    # Chat input + output tokens per workspace per UTC day; above it the widget replies
    # with the fallback message instead of calling the LLM.
    widget_daily_token_budget: int = Field(default=200_000, ge=0)

    # Message classification. `clef` uses Cloudflare Workers AI (@cf/cloudflare/clef-flash) and
    # falls back to the chat LLM when Cloudflare isn't configured or the call fails.
    decision_provider: Literal["clef", "llm", "fake"] = "clef"
    cloudflare_account_id: str = ""
    cloudflare_api_token: SecretStr | None = None
    clef_flash_price_per_mtok: Decimal = Decimal("0.09")
    # Below this intent confidence a message is answered from the knowledge base.
    classify_min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    # At or above this needs-human probability a message becomes a ticket.
    needs_human_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    # Rate limits (Redis sliding windows; fail open if Redis is down). Auth limits apply per
    # client IP and, for login/signup, per email as well.
    rate_limit_enabled: bool = True
    rate_limit_login_ip_per_minute: int = Field(default=20, ge=1)
    rate_limit_login_email_per_minute: int = Field(default=10, ge=1)
    rate_limit_signup_ip_per_hour: int = Field(default=30, ge=1)
    rate_limit_refresh_ip_per_minute: int = Field(default=60, ge=1)
    rate_limit_uploads_per_hour: int = Field(default=60, ge=1)
    rate_limit_regenerate_per_minute: int = Field(default=10, ge=1)
    # Every authenticated dashboard request, per user.
    rate_limit_api_user_per_minute: int = Field(default=300, ge=1)

    # Observability. LOG_FORMAT=json for structured logs, text for local reading.
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    # Bearer token for GET /metrics. Empty disables the endpoint (404).
    metrics_token: SecretStr | None = None
    # The worker refreshes a heartbeat in Redis; older than this, /health/ready reports it stale.
    worker_heartbeat_stale_s: int = Field(default=60, ge=10)
    # Optional error tracking. Needs the sentry-sdk package; empty disables it.
    sentry_dsn: SecretStr | None = None
    sentry_traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                return json.loads(v)
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @model_validator(mode="after")
    def validate_embedding_dim(self) -> "Settings":
        if self.embedding_dim != EMBEDDING_COLUMN_DIM:
            raise ValueError(
                f"EMBEDDING_DIM must be {EMBEDDING_COLUMN_DIM} to match the database column"
            )
        return self

    @model_validator(mode="after")
    def require_production_secrets(self) -> "Settings":
        if self.environment == "production":
            if not self.jwt_secret or self.jwt_secret == DEV_JWT_SECRET:
                raise ValueError("JWT_SECRET must be set in production")
            if not self.refresh_cookie_secure:
                raise ValueError("REFRESH_COOKIE_SECURE must be true in production")
            if self.widget_dev_allow_localhost:
                raise ValueError("WIDGET_DEV_ALLOW_LOCALHOST must be false in production")
            if self.demo_tools_enabled:
                raise ValueError("DEMO_TOOLS_ENABLED must be false in production")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
