import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")

_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
}


def error_code(status_code: int) -> str:
    if status_code in _CODES:
        return _CODES[status_code]
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_")
    except ValueError:
        return "error"


def error_response(
    status_code: int,
    message: str,
    request_id: str,
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code or error_code(status_code),
                "message": message,
                "request_id": request_id,
            }
        },
        headers=headers,
    )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(
        exc.status_code,
        message,
        _request_id(request),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Field locations and messages only; never echo submitted values (may hold PII/passwords).
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    message = "; ".join(parts) or "Request validation failed"
    return error_response(422, message, _request_id(request))


def unhandled_error_response(request_id: str) -> JSONResponse:
    logger.exception("Unhandled error (request_id=%s)", request_id)
    return error_response(500, "Internal server error", request_id)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
