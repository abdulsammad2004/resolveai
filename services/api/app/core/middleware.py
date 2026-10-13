import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import unhandled_error_response
from app.core.logs import reset_log_context, start_log_context
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS

REQUEST_ID_HEADER = "X-Request-ID"
# Accept caller-supplied ids only if they are short and safe to echo/log.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# Health probes and scrapes are frequent and uninteresting in the access log.
_QUIET_PATHS = frozenset({"/health", "/health/ready", "/metrics"})

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

access_logger = logging.getLogger("app.access")


def get_request_id() -> str:
    return request_id_ctx.get()


def route_template(scope: Scope) -> str:
    """The matched route as a template (e.g. /api/v1/tickets/{ticket_id}), never the raw
    path, so ids stay out of metric labels and logs. Unmatched paths share one label."""
    if scope.get("endpoint") is None:
        return "unmatched"
    params: dict[str, Any] = scope.get("path_params") or {}
    by_value = {str(value): name for name, value in params.items()}
    segments = str(scope.get("path", "")).split("/")
    return "/".join(f"{{{by_value[s]}}}" if s in by_value else s for s in segments)


class RequestIDMiddleware:
    """Pure ASGI middleware so the id is also present on error responses. Also writes the
    access log line and the HTTP metrics for every request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = ""
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else str(uuid.uuid4())

        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_ctx.set(request_id)
        log_token = start_log_context(request_id=request_id)
        started = time.perf_counter()
        status_code = 500

        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # Handled here rather than by Starlette's ServerErrorMiddleware, which sits
            # outside this middleware and would drop the request id.
            if response_started:
                raise
            response = unhandled_error_response(request_id)
            await response(scope, receive, send_with_request_id)
        finally:
            self._observe(scope, status_code, time.perf_counter() - started)
            reset_log_context(log_token)
            request_id_ctx.reset(token)

    @staticmethod
    def _observe(scope: Scope, status_code: int, elapsed: float) -> None:
        path = scope.get("path", "")
        if path == "/metrics":
            return
        method = scope.get("method", "")
        route = route_template(scope)
        HTTP_REQUESTS.inc(method=method, route=route, status=str(status_code))
        HTTP_LATENCY.observe(elapsed, method=method, route=route)
        if path in _QUIET_PATHS:
            return
        access_logger.info(
            "%s %s %s",
            method,
            route,
            status_code,
            extra={
                "method": method,
                "route": route,
                "status": status_code,
                "duration_ms": round(elapsed * 1000, 1),
            },
        )
