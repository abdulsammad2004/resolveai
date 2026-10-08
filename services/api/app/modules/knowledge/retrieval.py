"""Tenant-scoped semantic search over document chunks.

Runs inside the caller's tenant transaction, so RLS applies on top of the explicit
workspace filter. Query text is never logged.
"""

import logging
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import EmbeddingClient
from app.ai.usage import LLMPurpose, MeteredEmbeddingClient
from app.core.config import get_settings
from app.modules.knowledge.models import Document, DocumentChunk, DocumentStatus

logger = logging.getLogger("app.knowledge.retrieval")

# Candidates the HNSW scan considers. Must be >= top_k; higher trades speed for recall.
HNSW_EF_SEARCH = 100


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    heading_path: list[str]
    page_number: int | None
    content: str
    score: float


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk]
    query_tokens: int


def _heading_path(meta: dict) -> list[str]:
    value = meta.get("heading_path")
    if isinstance(value, list):
        return [str(h) for h in value]
    if isinstance(value, str) and value:
        return [value]
    return []


def _page_number(meta: dict) -> int | None:
    value = meta.get("page_number")
    return value if isinstance(value, int) else None


async def retrieve(
    db: AsyncSession,
    query: str,
    top_k: int | None = None,
    *,
    workspace_id: uuid.UUID,
    embedder: EmbeddingClient,
    min_score: float | None = None,
    keep: int | None = None,
) -> RetrievalResult:
    """Embed `query`, fetch the `top_k` nearest ready chunks, drop weak ones, keep the best.

    Score is cosine similarity (1 - cosine distance). An empty list is a normal result:
    callers should escalate rather than answer without sources.
    """
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k
    min_score = settings.retrieval_min_score if min_score is None else min_score
    keep = keep or settings.retrieval_keep

    metered = MeteredEmbeddingClient(
        embedder, workspace_id=workspace_id, purpose=LLMPurpose.EMBED_QUERY
    )
    [vector] = await metered.embed([query])
    started = time.perf_counter()

    # Transaction-local, like the tenant context. Iterative scans keep the HNSW index
    # useful when the status/workspace filters remove many of the nearest candidates.
    await db.execute(
        text(
            "SELECT set_config('hnsw.ef_search', :ef, true),"
            " set_config('hnsw.iterative_scan', 'relaxed_order', true)"
        ),
        {"ef": str(max(HNSW_EF_SEARCH, top_k))},
    )

    distance = DocumentChunk.embedding.cosine_distance(vector).label("distance")
    rows = (
        await db.execute(
            select(
                DocumentChunk.id,
                DocumentChunk.document_id,
                Document.title,
                DocumentChunk.meta,
                DocumentChunk.content,
                distance,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.workspace_id == workspace_id,
                Document.workspace_id == workspace_id,
                Document.status == DocumentStatus.READY,
            )
            .order_by(distance)
            .limit(top_k)
        )
    ).all()

    candidates = [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            document_title=row.title,
            heading_path=_heading_path(row.meta),
            page_number=_page_number(row.meta),
            content=row.content,
            score=round(1.0 - float(row.distance), 4),
        )
        for row in rows
    ]
    # relaxed_order may return near-ties slightly out of order; sort exactly here.
    candidates.sort(key=lambda c: c.score, reverse=True)
    kept = [c for c in candidates if c.score >= min_score][:keep]

    logger.info(
        "Retrieval (workspace_id=%s, candidates=%d, kept=%d, top_score=%s, ms=%.0f)",
        workspace_id,
        len(candidates),
        len(kept),
        candidates[0].score if candidates else None,
        (time.perf_counter() - started) * 1000,
    )
    return RetrievalResult(chunks=kept, query_tokens=metered.input_tokens)
