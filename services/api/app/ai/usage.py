"""Metering for every model call: one llm_calls row per provider call.

Rows carry ids, token counts, cost and latency only. Prompt, document and reply text is
never stored here. Rows are written in their own tenant transaction, so a call is recorded
even if the caller's transaction later rolls back; a failed write is logged, never raised.
"""

import enum
import logging
import time
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.ai.embeddings import BATCH_SIZE, EmbeddingClient
from app.ai.llm import ChatMessage, ModelT, StreamUsage, UsageReportingLLMClient, parse_structured
from app.core.config import get_settings
from app.core.database import Base, IdMixin, TimestampMixin
from app.core.deps import tenant_session
from app.core.middleware import get_request_id

logger = logging.getLogger("app.ai.usage")

MTOK = Decimal(1_000_000)
COST_QUANTUM = Decimal("0.00000001")


class LLMPurpose(enum.StrEnum):
    EMBED_DOCUMENT = "embed_document"
    EMBED_QUERY = "embed_query"
    CHAT = "chat"
    CLASSIFY = "classify"


class LLMCallStatus(enum.StrEnum):
    OK = "ok"
    ERROR = "error"


class LLMCall(IdMixin, TimestampMixin, Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'error')", name="status"),
        Index("ix_llm_calls_workspace_id_created_at", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 8), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


def embedding_cost(input_tokens: int) -> Decimal:
    price = get_settings().embedding_price_per_mtok
    return (Decimal(input_tokens) * price / MTOK).quantize(COST_QUANTUM)


def chat_cost(input_tokens: int, output_tokens: int) -> Decimal:
    settings = get_settings()
    cost = (
        Decimal(input_tokens) * settings.llm_input_price_per_mtok
        + Decimal(output_tokens) * settings.llm_output_price_per_mtok
    ) / MTOK
    return cost.quantize(COST_QUANTUM)


def _error_type(exc: BaseException) -> str:
    # Our client errors wrap the provider exception; the cause is the useful type.
    return type(exc.__cause__ or exc).__name__[:100]


async def record_llm_call(
    *,
    workspace_id: uuid.UUID,
    purpose: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
    latency_ms: float,
    status: LLMCallStatus,
    error_type: str | None = None,
    prompt_version: str | None = None,
    request_id: str | None = None,
) -> None:
    try:
        async with tenant_session(workspace_id) as db:
            db.add(
                LLMCall(
                    workspace_id=workspace_id,
                    purpose=purpose,
                    provider=provider,
                    model=model,
                    prompt_version=prompt_version,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    latency_ms=round(latency_ms),
                    status=status.value,
                    error_type=error_type,
                    request_id=request_id or get_request_id() or None,
                )
            )
    except Exception:
        logger.exception(
            "Failed to record llm call (workspace_id=%s, purpose=%s)", workspace_id, purpose
        )


class MeteredEmbeddingClient:
    """Wraps an embedding client for one workspace and purpose; one row per provider batch."""

    def __init__(
        self,
        inner: EmbeddingClient,
        *,
        workspace_id: uuid.UUID,
        purpose: LLMPurpose,
        request_id: str | None = None,
    ) -> None:
        self.inner = inner
        self.dim = inner.dim
        self.workspace_id = workspace_id
        self.purpose = purpose
        self.request_id = request_id
        self.input_tokens = 0  # running total across calls through this wrapper

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(await self._embed_batch(texts[start : start + BATCH_SIZE]))
        return vectors

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        provider = getattr(self.inner, "provider", "unknown")
        model = getattr(self.inner, "model", "unknown")
        started = time.perf_counter()
        try:
            with_usage = getattr(self.inner, "embed_with_usage", None)
            if with_usage is not None:
                result = await with_usage(batch)
                vectors, tokens = result.vectors, result.input_tokens
            else:
                vectors, tokens = await self.inner.embed(batch), 0
        except Exception as exc:
            await self._record(provider, model, 0, started, LLMCallStatus.ERROR, _error_type(exc))
            raise
        self.input_tokens += tokens
        await self._record(provider, model, tokens, started, LLMCallStatus.OK, None)
        return vectors

    async def _record(
        self,
        provider: str,
        model: str,
        tokens: int,
        started: float,
        status: LLMCallStatus,
        error_type: str | None,
    ) -> None:
        await record_llm_call(
            workspace_id=self.workspace_id,
            purpose=self.purpose.value,
            provider=provider,
            model=model,
            input_tokens=tokens,
            output_tokens=0,
            cost_usd=embedding_cost(tokens),
            latency_ms=(time.perf_counter() - started) * 1000,
            status=status,
            error_type=error_type,
            request_id=self.request_id,
        )


class MeteredLLMClient:
    """Wraps a chat client for one workspace, purpose and prompt version; one row per call."""

    def __init__(
        self,
        inner: UsageReportingLLMClient,
        *,
        workspace_id: uuid.UUID,
        purpose: LLMPurpose,
        prompt_version: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.inner = inner
        self.workspace_id = workspace_id
        self.purpose = purpose
        self.prompt_version = prompt_version
        self.request_id = request_id

    async def _record(
        self,
        started: float,
        input_tokens: int,
        output_tokens: int,
        status: LLMCallStatus,
        error_type: str | None = None,
    ) -> None:
        await record_llm_call(
            workspace_id=self.workspace_id,
            purpose=self.purpose.value,
            provider=self.inner.provider,
            model=self.inner.model or "unset",
            prompt_version=self.prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=chat_cost(input_tokens, output_tokens),
            latency_ms=(time.perf_counter() - started) * 1000,
            status=status,
            error_type=error_type,
            request_id=self.request_id,
        )

    async def _complete(
        self, messages: list[ChatMessage], schema: type[BaseModel] | None
    ) -> str:
        started = time.perf_counter()
        try:
            completion = await self.inner.complete_with_usage(messages, schema)
        except Exception as exc:
            await self._record(started, 0, 0, LLMCallStatus.ERROR, _error_type(exc))
            raise
        await self._record(
            started, completion.input_tokens, completion.output_tokens, LLMCallStatus.OK
        )
        return completion.text

    async def complete(self, messages: list[ChatMessage]) -> str:
        return await self._complete(messages, None)

    async def complete_structured(
        self, messages: list[ChatMessage], schema: type[ModelT]
    ) -> ModelT:
        return parse_structured(await self._complete(messages, schema), schema)

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        started = time.perf_counter()
        usage = StreamUsage()
        error_type: str | None = None
        try:
            async for piece in self.inner.stream_with_usage(messages, usage):
                yield piece
        except Exception as exc:
            error_type = _error_type(exc)
            raise
        finally:
            ok = usage.done and error_type is None
            await self._record(
                started,
                usage.input_tokens,
                usage.output_tokens,
                LLMCallStatus.OK if ok else LLMCallStatus.ERROR,
                None if ok else (error_type or "StreamIncomplete"),
            )
