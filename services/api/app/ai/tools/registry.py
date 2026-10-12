"""Tool definitions and the runtime that executes model tool calls.

The model is an untrusted planner. It only ever sees the JSON schemas of the tools a run
allows, and every call it makes goes through run_tool:

- Unknown or disallowed tools are refused.
- Arguments are parsed and validated against the tool's Pydantic model (extra fields are
  forbidden), then against the tool's business rules. Problems go back to the model as a
  clear message, never as an exception.
- workspace_id, conversation_id and ticket_id come from the ToolContext the runtime builds,
  never from the model. Tools take no URLs and build no SQL from model text.
- Read tools run, and so do internal tools (actions inside ResolveAI itself, such as handing
  the conversation to the team). Write and sensitive tools never run here: they become an
  action_requests row (status proposed) that a person must approve.
- Every call is logged in tool_calls, with emails masked.

Handlers return content that is already safe to place in a prompt (untrusted values passed
through app.ai.grounding.neutralize).
"""

import enum
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import EmbeddingClient
from app.ai.llm import ToolCallRequest, ToolSpec
from app.ai.tools.models import ToolCall, ToolCallStatus
from app.core.deps import tenant_session
from app.modules.approvals.models import ActionRequest, ActionStatus
from app.modules.audit import service as audit
from app.modules.audit.models import ActorType
from app.modules.knowledge.retrieval import RetrievedChunk

logger = logging.getLogger("app.ai.tools")

PROPOSED_MESSAGE = (
    "proposed — waiting for human approval. Nothing has been done yet. Do not tell the "
    "customer it is done; say a teammate will review the request."
)
ERROR_MESSAGE = "The tool failed. Do not retry; tell the customer a teammate will follow up."
SUMMARY_CHARS = 300


class Risk(enum.StrEnum):
    READ = "read"
    # Runs immediately, no approval: only for actions inside ResolveAI (e.g. opening a ticket
    # for this conversation), never for anything that touches money, accounts or orders.
    INTERNAL = "internal"
    WRITE = "write"
    SENSITIVE = "sensitive"


RUNS_IMMEDIATELY = frozenset({Risk.READ, Risk.INTERNAL})


@dataclass
class ToolContext:
    """Set by the runtime for one agent run. The model can't see or change any of it."""

    workspace_id: uuid.UUID
    embedder: EmbeddingClient
    conversation_id: uuid.UUID | None = None
    ticket_id: uuid.UUID | None = None
    # The ticket contact's email, when known (used by business checks, never shown).
    contact_email: str | None = None
    # True only when the customer's own request was classified as a refund request. Refunds
    # can't be proposed otherwise, whatever a document or tool result says.
    customer_asked_refund: bool = False
    # The same for cancelling an order.
    customer_asked_cancel: bool = False
    # Knowledge chunks retrieved during this run, numbered S1, S2, ... in this order.
    sources: list[RetrievedChunk] = field(default_factory=list)
    # Set by hand_off_to_team; the widget opens (or reuses) the ticket after the run.
    handoff_reason: str | None = None


@dataclass(frozen=True)
class ToolResult:
    status: ToolCallStatus
    content: str  # what the model sees (already prompt-safe)
    summary: str  # tool_calls.result_summary: a short plain-language line for the Inbox


Handler = Callable[[AsyncSession, ToolContext, Any], Awaitable[ToolResult]]
# Business rules for write/sensitive tools: an error message for the model, or None.
Check = Callable[[AsyncSession, ToolContext, Any], Awaitable[str | None]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    risk: Risk
    # Shown to the customer while the tool runs, e.g. "Checking your order…".
    status_text: str
    # Plain-language label of the call, e.g. "Refund request for order RA-10421".
    describe: Callable[[Any], str]
    handler: Handler | None = None  # read and internal tools only
    check: Check | None = None  # write/sensitive tools only

    def __post_init__(self) -> None:
        if (self.risk in RUNS_IMMEDIATELY) != (self.handler is not None):
            raise ValueError(
                f"Tool {self.name}: read/internal tools need a handler, others must not"
            )
        if self.risk not in RUNS_IMMEDIATELY and "reason" not in self.input_model.model_fields:
            raise ValueError(f"Tool {self.name}: write tools must take a reason")

    def spec(self) -> ToolSpec:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return ToolSpec(name=self.name, description=self.description, parameters=schema)


def mask_email(value: str) -> str:
    local, _, domain = value.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


def masked(arguments: dict[str, Any]) -> dict[str, Any]:
    """Arguments as stored in tool_calls: emails masked, long strings cut."""
    out: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, str) and "email" in key.lower():
            out[key] = mask_email(value)
        elif isinstance(value, str):
            out[key] = value[:500]
        else:
            out[key] = value
    return out


def idempotency_key(ticket_id: uuid.UUID, tool_name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{ticket_id}|{tool_name}|{canonical}".encode()).hexdigest()


def _validation_message(exc: ValidationError) -> str:
    problems = [
        f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}"
        for err in exc.errors()
    ]
    return "Invalid arguments. " + "; ".join(problems[:5])


def _invalid(message: str, summary: str) -> ToolResult:
    return ToolResult(ToolCallStatus.INVALID, message, summary)


async def _propose(
    db: AsyncSession, ctx: ToolContext, tool: Tool, args: BaseModel
) -> ToolResult:
    label = tool.describe(args)
    if ctx.ticket_id is None:
        return ToolResult(
            ToolCallStatus.DENIED, "This action isn't available here.", f"{label} — not allowed"
        )
    if tool.check is not None and (problem := await tool.check(db, ctx, args)):
        return _invalid(problem, f"{label} — invalid: {problem}")

    arguments = args.model_dump(mode="json")
    # The same proposal for the same ticket is stored once, however often it is made.
    inserted = await db.scalar(
        insert(ActionRequest)
        .values(
            id=uuid.uuid4(),
            workspace_id=ctx.workspace_id,
            ticket_id=ctx.ticket_id,
            conversation_id=ctx.conversation_id,
            tool_name=tool.name,
            arguments=arguments,
            risk=tool.risk.value,
            reason=str(arguments.get("reason", "")),
            status=ActionStatus.PROPOSED,
            idempotency_key=idempotency_key(ctx.ticket_id, tool.name, arguments),
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(ActionRequest.id)
    )
    if inserted is not None:
        audit.record(
            db,
            workspace_id=ctx.workspace_id,
            ticket_id=ctx.ticket_id,
            actor_type=ActorType.AI,
            actor_id=None,
            action="action.proposed",
            target_type="action_request",
            target_id=inserted,
            after={"status": ActionStatus.PROPOSED, "tool_name": tool.name},
        )
    return ToolResult(ToolCallStatus.PROPOSED, PROPOSED_MESSAGE, f"{label} — waiting for approval")


async def _execute(
    call: ToolCallRequest, tool: Tool, ctx: ToolContext
) -> tuple[ToolResult, dict[str, Any]]:
    try:
        raw = json.loads(call.arguments or "{}")
    except ValueError:
        raw = None
    if not isinstance(raw, dict):
        return _invalid("Arguments must be a JSON object.", "Invalid arguments"), {}
    try:
        args = tool.input_model.model_validate(raw)
    except ValidationError as exc:
        return _invalid(_validation_message(exc), "Invalid arguments"), masked(raw)
    logged = masked(args.model_dump(mode="json"))

    try:
        async with tenant_session(ctx.workspace_id) as db:
            if tool.risk in RUNS_IMMEDIATELY:
                assert tool.handler is not None
                return await tool.handler(db, ctx, args), logged
            return await _propose(db, ctx, tool, args), logged
    except Exception as exc:  # noqa: BLE001 - a failing tool must not end the run
        logger.warning(
            "Tool failed (tool=%s, workspace_id=%s, error=%s)",
            tool.name,
            ctx.workspace_id,
            type(exc).__name__,
        )
        return ToolResult(ToolCallStatus.ERROR, ERROR_MESSAGE, f"{tool.describe(args)} — failed"), logged


async def _record(
    ctx: ToolContext,
    tool_name: str,
    arguments: dict[str, Any],
    result: ToolResult,
    latency_ms: float,
) -> None:
    try:
        async with tenant_session(ctx.workspace_id) as db:
            db.add(
                ToolCall(
                    workspace_id=ctx.workspace_id,
                    conversation_id=ctx.conversation_id,
                    ticket_id=ctx.ticket_id,
                    tool_name=tool_name[:64],
                    arguments=arguments,
                    status=result.status.value,
                    result_summary=result.summary[:SUMMARY_CHARS],
                    latency_ms=round(latency_ms),
                )
            )
    except Exception:
        logger.exception(
            "Failed to record tool call (tool=%s, workspace_id=%s)", tool_name, ctx.workspace_id
        )


async def run_tool(
    call: ToolCallRequest, allowed: Mapping[str, Tool], ctx: ToolContext
) -> ToolResult:
    """Validate and run (read) or propose (write/sensitive) one tool call, and log it."""
    started = time.perf_counter()
    tool = allowed.get(call.name)
    if tool is None:
        result = ToolResult(
            ToolCallStatus.DENIED,
            "That tool doesn't exist. Use only the tools you were given.",
            "Tried a tool that isn't available",
        )
        arguments: dict[str, Any] = {}
    else:
        result, arguments = await _execute(call, tool, ctx)
    latency_ms = (time.perf_counter() - started) * 1000
    await _record(ctx, call.name, arguments, result, latency_ms)
    logger.info(
        "Tool call (tool=%s, status=%s, workspace_id=%s, latency_ms=%.0f)",
        call.name[:64],
        result.status.value,
        ctx.workspace_id,
        latency_ms,
    )
    return result
