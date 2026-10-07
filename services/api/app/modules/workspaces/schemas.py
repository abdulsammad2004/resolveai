import json
import uuid
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.workspaces.models import Role

MAX_ALLOWED_ORIGINS = 50
MAX_SETTINGS_BYTES = 16_384


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


class WorkspaceWithRole(WorkspaceOut):
    role: Role


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class WorkspaceSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    widget_public_key: str
    allowed_origins: list[str]
    settings: dict[str, Any]


class WorkspaceSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    allowed_origins: list[str] | None = Field(default=None, max_length=MAX_ALLOWED_ORIGINS)
    settings: dict[str, Any] | None = None

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        cleaned: list[str] = []
        for origin in v:
            origin = origin.strip().rstrip("/").lower()
            parts = urlsplit(origin)
            if (
                parts.scheme not in ("http", "https")
                or not parts.hostname
                or parts.path
                or parts.query
                or parts.fragment
                or parts.username
            ):
                raise ValueError("each origin must look like https://example.com[:port]")
            if origin not in cleaned:
                cleaned.append(origin)
        return cleaned

    @field_validator("settings")
    @classmethod
    def validate_settings_size(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and len(json.dumps(v)) > MAX_SETTINGS_BYTES:
            raise ValueError(f"settings must be at most {MAX_SETTINGS_BYTES} bytes of JSON")
        return v


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
