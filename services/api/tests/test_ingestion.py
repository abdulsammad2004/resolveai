import subprocess
import sys
import uuid

import pytest
from arq import Retry
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.workers.ingestion import FINAL_FAILURE_MESSAGE, MAX_TRIES, ingest_document
from tests.conftest import API_DIR, RecordingQueue, SignedUp, signup, upload_file

SET_CONTEXT = text("SELECT set_config('app.workspace_id', :wid, true)")


async def _uploaded(client: AsyncClient, owner: SignedUp, **kwargs) -> uuid.UUID:
    resp = await upload_file(client, owner.headers, **kwargs)
    assert resp.status_code == 202, resp.text
    return uuid.UUID(resp.json()["id"])


async def _chunks(engine: AsyncEngine, workspace_id: uuid.UUID, document_id: uuid.UUID):
    async with engine.connect() as conn, conn.begin():
        await conn.execute(SET_CONTEXT, {"wid": str(workspace_id)})
        result = await conn.execute(
            text(
                "SELECT chunk_index, vector_dims(embedding) AS dims, metadata, content "
                "FROM document_chunks WHERE document_id = :id ORDER BY chunk_index"
            ),
            {"id": document_id},
        )
        return result.mappings().all()


async def test_ingest_markdown_to_ready(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    app_role_engine: AsyncEngine,
) -> None:
    owner = await signup(client, "owner@example.com")
    doc_id = await _uploaded(client, owner)
    assert job_queue.jobs == [(doc_id, owner.workspace_id)]

    result = await ingest_document(worker_ctx, str(doc_id), str(owner.workspace_id))
    assert result == "ready"

    body = (await client.get(f"/api/v1/documents/{doc_id}", headers=owner.headers)).json()
    assert body["status"] == "ready"
    assert body["error"] is None
    assert body["chunk_count"] > 0

    chunks = await _chunks(app_role_engine, owner.workspace_id, doc_id)
    assert len(chunks) == body["chunk_count"]
    assert all(c["dims"] == 1536 for c in chunks)
    assert [c["metadata"]["heading_path"] for c in chunks] == [
        ["Returns policy"],
        ["Returns policy", "Refunds"],
        ["Returns policy", "Exchanges"],
    ]


async def test_ingest_is_idempotent_and_reindex_reprocesses(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    app_role_engine: AsyncEngine,
) -> None:
    owner = await signup(client, "owner@example.com")
    doc_id = await _uploaded(client, owner)
    ws = str(owner.workspace_id)

    assert await ingest_document(worker_ctx, str(doc_id), ws) == "ready"
    first = await _chunks(app_role_engine, owner.workspace_id, doc_id)

    # Already ready: a second run is a no-op.
    assert await ingest_document(worker_ctx, str(doc_id), ws) == "skipped"
    assert await _chunks(app_role_engine, owner.workspace_id, doc_id) == first

    resp = await client.post(f"/api/v1/documents/{doc_id}/reindex", headers=owner.headers)
    assert resp.status_code == 202
    assert resp.json()["status"] == "uploaded"
    assert job_queue.jobs[-1] == (doc_id, owner.workspace_id)

    # Reprocessing replaces the chunks: same count, no duplicates.
    assert await ingest_document(worker_ctx, str(doc_id), ws) == "ready"
    second = await _chunks(app_role_engine, owner.workspace_id, doc_id)
    assert [c["chunk_index"] for c in second] == list(range(len(first)))
    assert [c["content"] for c in second] == [c["content"] for c in first]

    body = (await client.get(f"/api/v1/documents/{doc_id}", headers=owner.headers)).json()
    assert body["status"] == "ready"
    assert body["chunk_count"] == len(first)


async def test_unparseable_document_fails_with_safe_message(
    client: AsyncClient, worker_ctx: dict
) -> None:
    owner = await signup(client, "owner@example.com")
    doc_id = await _uploaded(client, owner, filename="blank.txt", content=b"   \n\n \t \n")

    result = await ingest_document(worker_ctx, str(doc_id), str(owner.workspace_id))
    assert result == "failed"

    body = (await client.get(f"/api/v1/documents/{doc_id}", headers=owner.headers)).json()
    assert body["status"] == "failed"
    assert body["error"] == "The document contains no extractable text."


class FailingEmbedder:
    dim = 1536

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise ConnectionError("provider down")


async def test_transient_errors_retry_then_fail(client: AsyncClient, worker_ctx: dict) -> None:
    owner = await signup(client, "owner@example.com")
    doc_id = await _uploaded(client, owner)
    ws = str(owner.workspace_id)
    ctx = {**worker_ctx, "embedder": FailingEmbedder()}

    with pytest.raises(Retry):
        await ingest_document({**ctx, "job_try": 1}, str(doc_id), ws)
    body = (await client.get(f"/api/v1/documents/{doc_id}", headers=owner.headers)).json()
    assert body["status"] == "processing"

    with pytest.raises(ConnectionError):
        await ingest_document({**ctx, "job_try": MAX_TRIES}, str(doc_id), ws)
    body = (await client.get(f"/api/v1/documents/{doc_id}", headers=owner.headers)).json()
    assert body["status"] == "failed"
    assert body["error"] == FINAL_FAILURE_MESSAGE
    assert "provider down" not in body["error"]


async def test_job_with_wrong_workspace_sees_nothing(client: AsyncClient, worker_ctx: dict) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    doc_id = await _uploaded(client, a)

    # A job carrying B's workspace cannot load or modify A's document.
    assert await ingest_document(worker_ctx, str(doc_id), str(b.workspace_id)) == "missing"
    body = (await client.get(f"/api/v1/documents/{doc_id}", headers=a.headers)).json()
    assert body["status"] == "uploaded"


def test_worker_process_resolves_all_foreign_keys() -> None:
    """The worker doesn't import the API routers; its models must still resolve FKs."""
    code = (
        "import app.workers.main\n"
        "from app.core.database import Base\n"
        "for table in Base.metadata.sorted_tables:\n"
        "    for fk in table.foreign_keys:\n"
        "        fk.column\n"
    )
    subprocess.run([sys.executable, "-c", code], cwd=API_DIR, check=True)
