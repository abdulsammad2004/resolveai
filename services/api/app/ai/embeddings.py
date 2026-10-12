"""Embedding clients. Document text is never logged; only counts, tokens and latency."""

import asyncio
import hashlib
import logging
import math
import random
import struct
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import openai
from openai import AsyncOpenAI

from app.core.config import get_settings
from app.modules.knowledge.chunking import count_tokens

logger = logging.getLogger("app.ai.embeddings")

BATCH_SIZE = 64
REQUEST_TIMEOUT_S = 30.0
MAX_RETRIES = 3
BACKOFF_BASE_S = 1.0
BACKOFF_MAX_S = 20.0


class EmbeddingError(Exception):
    """Embedding failed after retries, or the provider returned an invalid response."""


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    input_tokens: int


class EmbeddingClient(Protocol):
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class UsageReportingEmbeddingClient(EmbeddingClient, Protocol):
    """A client that also reports token usage; app.ai.usage meters these."""

    provider: str
    model: str

    async def embed_with_usage(self, texts: list[str]) -> EmbeddingResult: ...


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, openai.APITimeoutError | openai.APIConnectionError | openai.RateLimitError):
        return True
    return isinstance(exc, openai.APIStatusError) and exc.status_code >= 500


def backoff_delay(attempt: int) -> float:
    """Jittered exponential backoff for retry number `attempt` (0-based)."""
    delay = min(BACKOFF_MAX_S, BACKOFF_BASE_S * 2**attempt)
    return random.uniform(delay / 2, delay)


class OpenAIEmbeddingClient:
    provider = "openai"

    def __init__(self, api_key: str, model: str, dim: int) -> None:
        # Retries are handled here so backoff and logging are under our control.
        self._client = AsyncOpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
        self.model = model
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return (await self.embed_with_usage(texts)).vectors

    async def embed_with_usage(self, texts: list[str]) -> EmbeddingResult:
        vectors: list[list[float]] = []
        tokens = 0
        for start in range(0, len(texts), BATCH_SIZE):
            batch = await self._embed_batch(texts[start : start + BATCH_SIZE])
            vectors.extend(batch.vectors)
            tokens += batch.input_tokens
        return EmbeddingResult(vectors=vectors, input_tokens=tokens)

    async def _embed_batch(self, batch: list[str]) -> EmbeddingResult:
        attempt = 0
        while True:
            started = time.perf_counter()
            try:
                resp = await self._client.embeddings.create(
                    model=self.model, input=batch, dimensions=self.dim
                )
            except Exception as exc:
                if not is_retryable(exc) or attempt >= MAX_RETRIES:
                    logger.warning(
                        "Embedding request failed (error=%s, attempts=%d)",
                        type(exc).__name__,
                        attempt + 1,
                    )
                    raise EmbeddingError("Embedding provider request failed") from exc
                delay = backoff_delay(attempt)
                attempt += 1
                logger.info(
                    "Embedding request retry %d/%d in %.1fs (error=%s)",
                    attempt,
                    MAX_RETRIES,
                    delay,
                    type(exc).__name__,
                )
                await asyncio.sleep(delay)
                continue

            latency_ms = (time.perf_counter() - started) * 1000
            data = sorted(resp.data, key=lambda d: d.index)
            if len(data) != len(batch):
                raise EmbeddingError("Embedding provider returned the wrong number of vectors")
            vectors = [list(d.embedding) for d in data]
            if any(len(v) != self.dim for v in vectors):
                raise EmbeddingError(f"Embedding provider returned vectors not of size {self.dim}")
            tokens = getattr(resp.usage, "total_tokens", None)
            logger.info(
                "Embedded batch (model=%s, inputs=%d, tokens=%s, latency_ms=%.0f)",
                self.model,
                len(batch),
                tokens,
                latency_ms,
            )
            if tokens is None:
                tokens = sum(count_tokens(t) for t in batch)
            return EmbeddingResult(vectors=vectors, input_tokens=tokens)


class FakeEmbeddingClient:
    """Deterministic unit vectors derived from a hash of the text. No network."""

    provider = "fake"
    model = "fake-embedding"

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dim:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            # 8 unsigned 32-bit ints per digest, mapped to [-1, 1].
            values.extend(x / 2**31 - 1.0 for x in struct.unpack("<8I", digest))
            counter += 1
        values = values[: self.dim]
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_with_usage(self, texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=await self.embed(texts), input_tokens=sum(count_tokens(t) for t in texts)
        )


@lru_cache
def get_embedding_client() -> UsageReportingEmbeddingClient:
    settings = get_settings()
    if settings.embedding_provider == "fake":
        return FakeEmbeddingClient(settings.embedding_dim)
    if settings.openai_api_key is None or not settings.openai_api_key.get_secret_value():
        raise RuntimeError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
    return OpenAIEmbeddingClient(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.embedding_model,
        dim=settings.embedding_dim,
    )
