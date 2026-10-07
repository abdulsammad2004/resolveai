import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import SecretStr, field_validator, model_validator
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
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
