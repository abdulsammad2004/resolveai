import re
import uuid
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import unhandled_error_response

REQUEST_ID_HEADER = "X-Request-ID"
# Accept caller-supplied ids only if they are short and safe to echo/log.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    return request_id_ctx.get()


class RequestIDMiddleware:
    """Pure ASGI middleware so the id is also present on error responses."""

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

        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
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
            request_id_ctx.reset(token)
