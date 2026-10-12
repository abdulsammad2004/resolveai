import io
import uuid
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.storage import LocalStorage
from app.workers.ingestion import ingest_document
from tests.conftest import MD_DOC, RecordingQueue, as_agent_in, signup, upload_file


async def _storage_key(owner_engine: AsyncEngine, document_id: str) -> str:
    async with owner_engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT storage_key FROM documents WHERE id = :id"), {"id": document_id}
            )
        ).scalar_one()


async def test_upload_returns_202_without_storage_key(
    client: AsyncClient, job_queue: RecordingQueue, owner_engine: AsyncEngine, storage: LocalStorage
) -> None:
    owner = await signup(client, "owner@example.com")
    resp = await upload_file(client, owner.headers, filename="../../etc/Returns Policy.md")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "uploaded"
    assert body["filename"] == "Returns Policy.md"
    assert body["title"] == "Returns Policy"
    assert body["mime_type"] == "text/markdown"
    assert body["size_bytes"] == len(MD_DOC)
    assert body["uploaded_by"] == str(owner.user_id)
    assert "storage_key" not in resp.text
    assert job_queue.jobs == [(uuid.UUID(body["id"]), owner.workspace_id)]

    # Stored under a random key, not the user's filename.
    key = await _storage_key(owner_engine, body["id"])
    assert "Returns" not in key
    assert (storage.root / key).read_bytes() == MD_DOC


async def test_duplicate_upload_returns_409_with_existing_id(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    first = await upload_file(client, owner.headers)
    resp = await upload_file(client, owner.headers, filename="copy.md")
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "duplicate_document"
    assert error["existing_document_id"] == first.json()["id"]

    # The same content in another workspace is not a duplicate.
    other = await signup(client, "other@example.com", workspace_name="Other")
    assert (await upload_file(client, other.headers)).status_code == 202


async def test_oversized_upload_returns_413(
    client: AsyncClient, job_queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await signup(client, "owner@example.com")
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    resp = await upload_file(client, owner.headers, content=b"a" * (1024 * 1024 + 1))
    assert resp.status_code == 413
    assert job_queue.jobs == []


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("invoice.pdf", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff"),  # .exe renamed
        ("setup.exe", b"MZ\x90\x00"),
        ("notes.txt", b"\xff\xfe\x00b\x00a\x00d"),  # not UTF-8
        ("fake.docx", b"PK\x03\x04 not really a zip"),
    ],
)
async def test_unsupported_content_returns_415(
    client: AsyncClient, job_queue: RecordingQueue, filename: str, content: bytes
) -> None:
    owner = await signup(client, "owner@example.com")
    resp = await upload_file(client, owner.headers, filename=filename, content=content)
    assert resp.status_code == 415, resp.text
    assert job_queue.jobs == []


async def test_zip_without_word_document_is_not_docx(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "hi")
    resp = await upload_file(client, owner.headers, filename="a.docx", content=buf.getvalue())
    assert resp.status_code == 415


async def test_agent_cannot_upload_delete_or_reindex(
    client: AsyncClient, owner_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com", workspace_name="Tenant A")
    agent = await signup(client, "agent@example.com", workspace_name="Agent Home")
    agent_headers = await as_agent_in(client, owner_engine, agent, owner.workspace_id)
    doc_id = (await upload_file(client, owner.headers)).json()["id"]

    resp = await upload_file(client, agent_headers, content=b"# Other\n\ntext")
    assert resp.status_code == 403
    assert (
        await client.delete(f"/api/v1/documents/{doc_id}", headers=agent_headers)
    ).status_code == 403
    resp = await client.post(f"/api/v1/documents/{doc_id}/reindex", headers=agent_headers)
    assert resp.status_code == 403

    # Agents can still read.
    resp = await client.get("/api/v1/documents", headers=agent_headers)
    assert [d["id"] for d in resp.json()["items"]] == [doc_id]
    assert (
        await client.get(f"/api/v1/documents/{doc_id}", headers=agent_headers)
    ).status_code == 200


async def test_list_is_newest_first_with_cursor(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    ids = []
    for i in range(3):
        resp = await upload_file(
            client, owner.headers, filename=f"d{i}.md", content=f"doc {i}".encode()
        )
        ids.append(resp.json()["id"])

    page1 = (await client.get("/api/v1/documents?limit=2", headers=owner.headers)).json()
    assert [d["id"] for d in page1["items"]] == [ids[2], ids[1]]
    assert page1["next_cursor"]

    page2 = (
        await client.get(
            "/api/v1/documents",
            params={"limit": 2, "cursor": page1["next_cursor"]},
            headers=owner.headers,
        )
    ).json()
    assert [d["id"] for d in page2["items"]] == [ids[0]]
    assert page2["next_cursor"] is None

    resp = await client.get("/api/v1/documents?cursor=garbage", headers=owner.headers)
    assert resp.status_code == 422


async def test_delete_removes_row_chunks_and_file(
    client: AsyncClient, worker_ctx: dict, owner_engine: AsyncEngine, storage: LocalStorage
) -> None:
    owner = await signup(client, "owner@example.com")
    doc_id = (await upload_file(client, owner.headers)).json()["id"]
    await ingest_document(worker_ctx, doc_id, str(owner.workspace_id))
    key = await _storage_key(owner_engine, doc_id)
    assert (storage.root / key).exists()

    resp = await client.delete(f"/api/v1/documents/{doc_id}", headers=owner.headers)
    assert resp.status_code == 204

    assert not (storage.root / key).exists()
    assert (
        await client.get(f"/api/v1/documents/{doc_id}", headers=owner.headers)
    ).status_code == 404
    async with owner_engine.connect() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM document_chunks WHERE document_id = :id"), {"id": doc_id}
        )
    assert count == 0

    # The same content can be uploaded again after deletion.
    assert (await upload_file(client, owner.headers)).status_code == 202


async def test_workspace_b_cannot_reach_workspace_a_documents(
    client: AsyncClient,
    worker_ctx: dict,
    job_queue: RecordingQueue,
    app_role_engine: AsyncEngine,
    storage: LocalStorage,
    owner_engine: AsyncEngine,
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    doc_id = (await upload_file(client, a.headers)).json()["id"]
    assert await ingest_document(worker_ctx, doc_id, str(a.workspace_id)) == "ready"
    jobs_before = list(job_queue.jobs)

    resp = await client.get("/api/v1/documents", headers=b.headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert (await client.get(f"/api/v1/documents/{doc_id}", headers=b.headers)).status_code == 404
    assert (
        await client.delete(f"/api/v1/documents/{doc_id}", headers=b.headers)
    ).status_code == 404
    resp = await client.post(f"/api/v1/documents/{doc_id}/reindex", headers=b.headers)
    assert resp.status_code == 404
    assert job_queue.jobs == jobs_before

    # A's document, chunks and file are untouched.
    body = (await client.get(f"/api/v1/documents/{doc_id}", headers=a.headers)).json()
    assert body["status"] == "ready"
    assert (storage.root / await _storage_key(owner_engine, doc_id)).exists()

    # Database level: with B's context, none of A's rows are visible.
    set_context = text("SELECT set_config('app.workspace_id', :wid, true)")
    async with app_role_engine.connect() as conn, conn.begin():
        await conn.execute(set_context, {"wid": str(b.workspace_id)})
        assert await conn.scalar(text("SELECT count(*) FROM document_chunks")) == 0
        assert await conn.scalar(text("SELECT count(*) FROM documents")) == 0
        deleted = await conn.execute(text("DELETE FROM document_chunks"))
        assert deleted.rowcount == 0

    async with app_role_engine.connect() as conn, conn.begin():
        await conn.execute(set_context, {"wid": str(a.workspace_id)})
        assert (
            await conn.scalar(text("SELECT count(*) FROM document_chunks")) == body["chunk_count"]
        )

    # No context at all: nothing visible.
    async with app_role_engine.connect() as conn, conn.begin():
        assert await conn.scalar(text("SELECT count(*) FROM document_chunks")) == 0


@pytest.mark.parametrize("title", ["", "   ", "string", " String "])
async def test_empty_or_placeholder_title_defaults_to_filename_stem(
    client: AsyncClient, title: str
) -> None:
    owner = await signup(client, "owner@example.com")
    resp = await client.post(
        "/api/v1/documents",
        files={"file": ("Refund Policy.v2.md", MD_DOC, "application/octet-stream")},
        data={"title": title},
        headers=owner.headers,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["title"] == "Refund Policy.v2"


async def test_explicit_title_is_kept(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    resp = await client.post(
        "/api/v1/documents",
        files={"file": ("returns.md", MD_DOC, "application/octet-stream")},
        data={"title": "  Returns & refunds  "},
        headers=owner.headers,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["title"] == "Returns & refunds"
