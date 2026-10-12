"""Document ingestion job: read -> parse -> chunk -> embed -> store.

Runs as the app role with app.workspace_id set, so RLS applies exactly as in the API.
Logs carry ids and counts only, never filenames or document text.
"""

import asyncio
import hashlib
import logging
import time
import uuid
from typing import Any

from arq import Retry
from sqlalchemy import delete, insert, select

from app.ai.embeddings import EmbeddingClient, get_embedding_client
from app.ai.usage import LLMPurpose, MeteredEmbeddingClient
from app.core.deps import tenant_session
from app.core.storage import Storage, StorageError, get_storage
from app.modules.knowledge.chunking import chunk_sections
from app.modules.knowledge.models import Document, DocumentChunk, DocumentStatus
from app.modules.knowledge.parsing import ParseError, parse_document

logger = logging.getLogger("app.workers.ingestion")

MAX_TRIES = 3
JOB_TIMEOUT_S = 600
# Finish (or give up) before arq cancels the job, so the failure can be recorded.
WORK_TIMEOUT_S = JOB_TIMEOUT_S - 30
RETRY_DELAY_S = 10
FINAL_FAILURE_MESSAGE = "Processing failed after several attempts. Try reindexing later."


class PermanentIngestError(Exception):
    """A failure that retrying cannot fix. The message is shown to users."""


async def ingest_document(ctx: dict[str, Any], document_id: str, workspace_id: str) -> str:
    doc_id = uuid.UUID(document_id)
    ws_id = uuid.UUID(workspace_id)
    storage: Storage = ctx.get("storage") or get_storage()
    embedder: EmbeddingClient = ctx.get("embedder") or get_embedding_client()
    job_try: int = ctx.get("job_try", 1)

    try:
        async with asyncio.timeout(WORK_TIMEOUT_S):
            return await _ingest(doc_id, ws_id, storage, embedder)
    except PermanentIngestError as exc:
        logger.warning("Ingestion failed permanently (document_id=%s)", doc_id)
        await _mark_failed(doc_id, ws_id, str(exc))
        return "failed"
    except Exception as exc:
        if job_try < MAX_TRIES:
            logger.warning(
                "Ingestion attempt %d/%d failed, will retry (document_id=%s, error=%s)",
                job_try,
                MAX_TRIES,
                doc_id,
                type(exc).__name__,
            )
            raise Retry(defer=RETRY_DELAY_S * job_try) from exc
        logger.exception("Ingestion failed after %d attempts (document_id=%s)", job_try, doc_id)
        await _mark_failed(doc_id, ws_id, FINAL_FAILURE_MESSAGE)
        raise


async def _ingest(
    doc_id: uuid.UUID, ws_id: uuid.UUID, storage: Storage, embedder: EmbeddingClient
) -> str:
    started = time.perf_counter()

    async with tenant_session(ws_id) as db:
        doc = await db.scalar(
            select(Document).where(Document.workspace_id == ws_id, Document.id == doc_id)
        )
        if doc is None:
            logger.info("Document no longer exists, skipping (document_id=%s)", doc_id)
            return "missing"
        # content_hash is fixed per document row, so `ready` means this content is indexed.
        # Reindex resets the status to `uploaded` to force a rerun.
        if doc.status == DocumentStatus.READY:
            logger.info("Document already ready, skipping (document_id=%s)", doc_id)
            return "skipped"
        doc.status = DocumentStatus.PROCESSING
        doc.error = None
        storage_key, mime_type, content_hash = doc.storage_key, doc.mime_type, doc.content_hash

    try:
        data = await storage.read(storage_key)
    except StorageError as exc:
        raise PermanentIngestError("The uploaded file is missing. Please upload it again.") from exc
    if hashlib.sha256(data).hexdigest() != content_hash:
        raise PermanentIngestError("The stored file is corrupted. Please upload it again.")

    try:
        # CPU-bound; keep the worker's event loop responsive.
        sections = await asyncio.to_thread(parse_document, data, mime_type)
    except ParseError as exc:
        raise PermanentIngestError(str(exc)) from exc
    chunks = await asyncio.to_thread(chunk_sections, sections)
    if not chunks:
        raise PermanentIngestError("The document contains no extractable text.")

    # Every provider call is recorded in llm_calls (tokens and cost, never text).
    metered = MeteredEmbeddingClient(
        embedder, workspace_id=ws_id, purpose=LLMPurpose.EMBED_DOCUMENT
    )
    embeddings = await metered.embed([c.content for c in chunks])
    if len(embeddings) != len(chunks):
        raise RuntimeError("Embedding count does not match chunk count")

    async with tenant_session(ws_id) as db:
        # Row lock serialises concurrent jobs for the same document.
        doc = await db.scalar(
            select(Document)
            .where(Document.workspace_id == ws_id, Document.id == doc_id)
            .with_for_update()
        )
        if doc is None:
            logger.info("Document deleted during ingestion (document_id=%s)", doc_id)
            return "missing"
        await db.execute(
            delete(DocumentChunk).where(
                DocumentChunk.workspace_id == ws_id, DocumentChunk.document_id == doc_id
            )
        )
        await db.execute(
            insert(DocumentChunk),
            [
                {
                    "id": uuid.uuid4(),
                    "workspace_id": ws_id,
                    "document_id": doc_id,
                    "chunk_index": index,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                    "embedding": vector,
                    "meta": chunk.metadata,
                }
                for index, (chunk, vector) in enumerate(zip(chunks, embeddings, strict=True))
            ],
        )
        doc.status = DocumentStatus.READY
        doc.chunk_count = len(chunks)
        doc.error = None

    logger.info(
        "Document ingested (document_id=%s, workspace_id=%s, chunks=%d, tokens=%d, ms=%.0f)",
        doc_id,
        ws_id,
        len(chunks),
        sum(c.token_count for c in chunks),
        (time.perf_counter() - started) * 1000,
    )
    return "ready"


async def _mark_failed(doc_id: uuid.UUID, ws_id: uuid.UUID, message: str) -> None:
    async with tenant_session(ws_id) as db:
        doc = await db.scalar(
            select(Document).where(Document.workspace_id == ws_id, Document.id == doc_id)
        )
        if doc is not None:
            doc.status = DocumentStatus.FAILED
            doc.error = message[:500]
