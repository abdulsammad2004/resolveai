import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, status

from app.core.config import get_settings

ACCESS_TOKEN_TYPE = "access"
WIDGET_TOKEN_TYPE = "widget"

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, workspace_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "wid": str(workspace_id),
        "role": role,
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _unauthorized(message: str = "Invalid or expired token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "wid", "role", "type", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized() from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise _unauthorized()
    try:
        uuid.UUID(payload["sub"])
        uuid.UUID(payload["wid"])
    except (ValueError, TypeError) as exc:
        raise _unauthorized() from exc
    return payload


def create_widget_token(
    workspace_id: uuid.UUID, conversation_id: uuid.UUID, contact_id: uuid.UUID
) -> str:
    """Token for the customer chat widget: one conversation, no user, no role."""
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "wid": str(workspace_id),
        "conversation_id": str(conversation_id),
        "contact_id": str(contact_id),
        "type": WIDGET_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.widget_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_widget_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["wid", "conversation_id", "contact_id", "type", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized() from exc

    if payload.get("type") != WIDGET_TOKEN_TYPE:
        raise _unauthorized()
    try:
        for claim in ("wid", "conversation_id", "contact_id"):
            uuid.UUID(payload[claim])
    except (ValueError, TypeError) as exc:
        raise _unauthorized() from exc
    return payload


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash). Only the hash is ever stored."""
    raw_token = secrets.token_urlsafe(48)
    return raw_token, hash_refresh_token(raw_token)
