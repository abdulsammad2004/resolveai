import logging
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.deps import CurrentPrincipal, Principal, TenantDB, require_role
from app.core.storage import Storage, get_storage
from app.modules.knowledge import service
from app.modules.knowledge.schemas import DocumentOut, DocumentPage
from app.modules.workspaces.models import Role
from app.workers.queue import JobQueue, get_job_queue

logger = logging.getLogger("app.api.documents")

router = APIRouter(prefix="/documents", tags=["knowledge"])

KnowledgeEditor = Annotated[Principal, Depends(require_role(Role.OWNER, Role.ADMIN))]
StorageDep = Annotated[Storage, Depends(get_storage)]
QueueDep = Annotated[JobQueue, Depends(get_job_queue)]


async def _enqueue(queue: JobQueue, document_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
    # The row is already committed; if Redis is down it stays `uploaded` and can be reindexed.
    try:
        await queue.enqueue_ingest(document_id, workspace_id)
    except Exception:
        logger.exception("Failed to enqueue ingestion (document_id=%s)", document_id)


@router.post("", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    principal: KnowledgeEditor,
    storage: StorageDep,
    queue: QueueDep,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=255)] = None,
) -> DocumentOut | JSONResponse:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"File exceeds the {get_settings().max_upload_mb} MB limit",
        )
    try:
        doc = await service.upload_document(
            principal, storage, filename=file.filename, data=data, title=title
        )
    except service.DuplicateDocumentError as exc:
        # Same error shape as app.core.errors, plus the id of the existing document.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "duplicate_document",
                    "message": "This document has already been uploaded",
                    "request_id": getattr(request.state, "request_id", ""),
                    "existing_document_id": str(exc.existing_id),
                }
            },
        )
    await _enqueue(queue, doc.id, doc.workspace_id)
    return DocumentOut.model_validate(doc)


@router.get("", response_model=DocumentPage)
async def list_documents(
    principal: CurrentPrincipal,
    db: TenantDB,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DocumentPage:
    rows, next_cursor = await service.list_documents(db, principal.workspace_id, cursor, limit)
    return DocumentPage(
        items=[DocumentOut.model_validate(d) for d in rows], next_cursor=next_cursor
    )


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID, principal: CurrentPrincipal, db: TenantDB
) -> DocumentOut:
    doc = await service.get_document(db, principal.workspace_id, document_id)
    return DocumentOut.model_validate(doc)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, principal: KnowledgeEditor, storage: StorageDep
) -> None:
    await service.delete_document(principal, storage, document_id)


@router.post(
    "/{document_id}/reindex", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED
)
async def reindex_document(
    document_id: uuid.UUID, principal: KnowledgeEditor, queue: QueueDep
) -> DocumentOut:
    doc = await service.mark_for_reindex(principal, document_id)
    await _enqueue(queue, doc.id, doc.workspace_id)
    return DocumentOut.model_validate(doc)
