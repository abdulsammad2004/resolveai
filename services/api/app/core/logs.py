"""Structured logging shared by the API and the worker.

Every line carries the request id plus whatever context is bound for the current request or
job (workspace_id, user_id, job name). A redaction pass scrubs emails, bearer tokens, JWTs and
API keys from every message and traceback, as a safety net: callers still log ids and counts,
never message bodies.
"""

import json
import logging
import re
import time
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [redacted]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "[jwt]"),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}"), "[api-key]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (
        re.compile(r"(?i)\b(password|token|secret|api_key|authorization)=([^\s,)&]+)"),
        r"\1=[redacted]",
    ),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


# One mutable dict per request or job. Dependencies add to it (e.g. the principal's ids), and
# because it is shared by reference, the access log written after the response sees them too.
_log_context: ContextVar[dict[str, str] | None] = ContextVar("log_context", default=None)


def start_log_context(**values: str) -> Token[dict[str, str] | None]:
    return _log_context.set({k: v for k, v in values.items() if v})


def reset_log_context(token: Token[dict[str, str] | None]) -> None:
    _log_context.reset(token)


def bind_log_context(**values: object) -> None:
    """Add ids to the current request's or job's log context (only ids, never text)."""
    current = _log_context.get()
    if current is None:
        current = {}
        _log_context.set(current)
    for key, value in values.items():
        if value is not None:
            current[key] = str(value)


def log_context() -> dict[str, str]:
    return dict(_log_context.get() or {})


_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "taskName",
}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        entry.update(log_context())
        # Structured fields passed with `extra=` (ids, durations, statuses).
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value if isinstance(value, int | float | bool) else redact(str(value))
        if record.exc_info:
            entry["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        context = " ".join(f"{k}={v}" for k, v in log_context().items())
        line = redact(super().format(record))
        return f"{line} [{context}]" if context else line


_HANDLER_NAME = "resolveai"


def configure_logging() -> None:
    """Install one handler on the root logger. Safe to call more than once."""
    settings = get_settings()
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == _HANDLER_NAME:
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JSONFormatter() if settings.log_format == "json" else TextFormatter())
    root.addHandler(handler)
    level = logging.getLevelName(settings.log_level.upper())
    # Records propagate to the root handler whatever the root level, so only "app" needs one.
    logging.getLogger("app").setLevel(level if isinstance(level, int) else logging.INFO)
    # The access log below replaces uvicorn's, which logs raw paths and query strings.
    logging.getLogger("uvicorn.access").disabled = True


class EveryNSeconds:
    """Lets a noisy warning through at most once per interval."""

    def __init__(self, interval_s: float) -> None:
        self.interval_s = interval_s
        self._last = 0.0

    def ready(self) -> bool:
        now = time.monotonic()
        if now - self._last >= self.interval_s:
            self._last = now
            return True
        return False
