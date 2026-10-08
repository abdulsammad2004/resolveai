"""Knowledge documents: upload, list, get, delete, reindex.

Every query filters by workspace_id explicitly; RLS enforces the same rule underneath.
Operations that must commit before a side effect (enqueue, file delete) open their own
tenant session so the commit happens inside this module, not after the response.
"""

import base64
import binascii
import hashlib
import json
import logging
import unicodedata
import uuid
from datetime import datetime
from pathlib import PurePath

from fastapi import HTTPException, status
from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import Principal, tenant_session
from app.core.storage import Storage, new_storage_key
from app.modules.knowledge.models import Document, DocumentStatus
from app.modules.knowledge.parsing import UnsupportedFileType, detect_mime_type

logger = logging.getLogger("app.knowledge")

MAX_NAME_LENGTH = 255


class DuplicateDocumentError(Exception):
    def __init__(self, existing_id: uuid.UUID) -> None:
        super().__init__("Document already exists")
        self.existing_id = existing_id


def clean_filename(raw: str | None) -> str:
    """Keep only a display-safe base name; it is never used as a storage path."""
    name = PurePath((raw or "").replace("\\", "/")).name
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip()
    return name[-MAX_NAME_LENGTH:] or "document"


def default_title(title: str | None, filename: str) -> str:
    """Use the given title, or the filename without its extension when the title is empty
    or the literal "string" (the placeholder API docs send for an untouched field)."""
    cleaned = (title or "").strip()
    if not cleaned or cleaned.lower() == "string":
        return PurePath(filename).stem or filename
    return cleaned[:MAX_NAME_LENGTH]


async def _find_by_hash(
    db: AsyncSession, workspace_id: uuid.UUID, content_hash: str
) -> uuid.UUID | None:
    return await db.scalar(
        select(Document.id).where(
            Document.workspace_id == workspace_id, Document.content_hash == content_hash
        )
    )


async def upload_document(
    principal: Principal,
    storage: Storage,
    *,
    filename: str | None,
    data: bytes,
    title: str | None,
) -> Document:
    """Validate, store and record an upload. Returns after the row is committed."""
    name = clean_filename(filename)
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "File is empty")
    try:
        mime_type = detect_mime_type(name, data)
    except UnsupportedFileType as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    content_hash = hashlib.sha256(data).hexdigest()
    workspace_id = principal.workspace_id

    async with tenant_session(workspace_id, principal.user_id) as db:
        if existing := await _find_by_hash(db, workspace_id, content_hash):
            raise DuplicateDocumentError(existing)

    key = new_storage_key(workspace_id)
    await storage.save(key, data)
    try:
        async with tenant_session(workspace_id, principal.user_id) as db:
            doc = Document(
                workspace_id=workspace_id,
                title=default_title(title, name),
                filename=name,
                mime_type=mime_type,
                size_bytes=len(data),
                storage_key=key,
                content_hash=content_hash,
                status=DocumentStatus.UPLOADED,
                uploaded_by=principal.user_id,
            )
            db.add(doc)
            await db.flush()
            await db.refresh(doc)
    except IntegrityError as exc:
        await storage.delete(key)
        # Lost a race with an identical upload.
        if "uq_documents_workspace_id" in str(exc.orig):
            async with tenant_session(workspace_id, principal.user_id) as db:
                if existing := await _find_by_hash(db, workspace_id, content_hash):
                    raise DuplicateDocumentError(existing) from exc
        raise
    except BaseException:
        await storage.delete(key)
        raise

    logger.info(
        "Document uploaded (document_id=%s, workspace_id=%s, size_bytes=%d)",
        doc.id,
        workspace_id,
        doc.size_bytes,
    )
    return doc


def encode_cursor(created_at: datetime, doc_id: uuid.UUID) -> str:
    raw = json.dumps({"c": created_at.isoformat(), "i": str(doc_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        return datetime.fromisoformat(data["c"]), uuid.UUID(data["i"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from exc


async def list_documents(
    db: AsyncSession, workspace_id: uuid.UUID, cursor: str | None, limit: int
) -> tuple[list[Document], str | None]:
    """Newest first. Keyset pagination on (created_at, id)."""
    query = select(Document).where(Document.workspace_id == workspace_id)
    if cursor:
        created_at, doc_id = decode_cursor(cursor)
        query = query.where(tuple_(Document.created_at, Document.id) < (created_at, doc_id))
    query = query.order_by(Document.created_at.desc(), Document.id.desc()).limit(limit + 1)
    rows = list((await db.scalars(query)).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)
    return rows, next_cursor


async def get_document(
    db: AsyncSession, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    doc = await db.scalar(
        select(Document).where(Document.workspace_id == workspace_id, Document.id == document_id)
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


async def delete_document(
    principal: Principal, storage: Storage, document_id: uuid.UUID
) -> None:
    """Delete the row (chunks cascade), then the stored file once the delete has committed."""
    async with tenant_session(principal.workspace_id, principal.user_id) as db:
        doc = await get_document(db, principal.workspace_id, document_id)
        key = doc.storage_key
        await db.delete(doc)
    await storage.delete(key)
    logger.info(
        "Document deleted (document_id=%s, workspace_id=%s)", document_id, principal.workspace_id
    )


async def mark_for_reindex(principal: Principal, document_id: uuid.UUID) -> Document:
    """Reset to `uploaded` so the next ingest job reprocesses it. Returns after commit."""
    async with tenant_session(principal.workspace_id, principal.user_id) as db:
        doc = await get_document(db, principal.workspace_id, document_id)
        doc.status = DocumentStatus.UPLOADED
        doc.error = None
        await db.flush()
        await db.refresh(doc)
    return doc
