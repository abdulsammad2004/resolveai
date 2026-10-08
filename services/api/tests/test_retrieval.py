"""Knowledge search: ranking, threshold, ready-only, tenancy, and llm_calls metering."""

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.embeddings import FakeEmbeddingClient
from app.core.config import get_settings
from app.core.deps import tenant_session
from app.modules.knowledge.chunking import count_tokens
from app.modules.knowledge.retrieval import retrieve
from app.workers.ingestion import MAX_TRIES, ingest_document
from tests.conftest import SignedUp, as_agent_in, signup, upload_file

SET_CONTEXT = text("SELECT set_config('app.workspace_id', :wid, true)")
SEARCH_URL = "/api/v1/knowledge/search"

SHIPPING_DOC = (
    b"# Shipping\n\nStandard shipping takes 3 to 5 business days within the country.\n\n"
    b"## International\n\nInternational orders arrive in 7 to 14 days and may incur customs fees.\n"
)


async def _ready_document(
    client: AsyncClient,
    worker_ctx: dict,
    owner: SignedUp,
    filename: str = "returns.md",
    content: bytes | None = None,
) -> uuid.UUID:
    kwargs = {"filename": filename} | ({"content": content} if content else {})
    resp = await upload_file(client, owner.headers, **kwargs)
    assert resp.status_code == 202, resp.text
    doc_id = uuid.UUID(resp.json()["id"])
    assert await ingest_document(worker_ctx, str(doc_id), str(owner.workspace_id)) == "ready"
    return doc_id


async def _chunk_contents(
    engine: AsyncEngine, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> dict[uuid.UUID, str]:
    async with engine.connect() as conn, conn.begin():
        await conn.execute(SET_CONTEXT, {"wid": str(workspace_id)})
        rows = await conn.execute(
            text("SELECT id, content FROM document_chunks WHERE document_id = :id"),
            {"id": document_id},
        )
        return {row.id: row.content for row in rows}


async def _llm_calls(engine: AsyncEngine, workspace_id: uuid.UUID) -> list[dict]:
    async with engine.connect() as conn, conn.begin():
        await conn.execute(SET_CONTEXT, {"wid": str(workspace_id)})
        rows = await conn.execute(text("SELECT * FROM llm_calls ORDER BY created_at"))
        return [dict(r) for r in rows.mappings()]


async def test_most_relevant_chunk_comes_first(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    returns_id = await _ready_document(client, worker_ctx, owner)
    await _ready_document(client, worker_ctx, owner, "shipping.md", SHIPPING_DOC)

    chunks = await _chunk_contents(app_role_engine, owner.workspace_id, returns_id)
    target_id, target_text = next(iter(chunks.items()))

    # The fake embedder maps identical text to identical vectors (similarity 1.0) and
    # unrelated text to near-orthogonal ones, so the exact chunk text must rank first.
    resp = await client.post(SEARCH_URL, json={"query": target_text}, headers=owner.headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    first = body["results"][0]
    assert first["chunk_id"] == str(target_id)
    assert first["document_id"] == str(returns_id)
    assert first["document_title"] == "returns"
    assert first["content"] == target_text
    assert first["score"] > 0.99
    assert isinstance(first["heading_path"], list)
    assert "page_number" in first
    assert body["query_tokens"] == count_tokens(target_text)
    scores = [r["score"] for r in body["results"]]
    assert scores == sorted(scores, reverse=True)


async def test_results_below_threshold_are_dropped(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    doc_id = await _ready_document(client, worker_ctx, owner)

    # Unrelated text scores near 0 against every chunk: an empty 200, not an error.
    resp = await client.post(
        SEARCH_URL, json={"query": "zebra migration patterns"}, headers=owner.headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"] == []

    # With the threshold disabled the same chunks come back, so the filter did the dropping.
    async with tenant_session(owner.workspace_id, owner.user_id) as db:
        result = await retrieve(
            db,
            "zebra migration patterns",
            workspace_id=owner.workspace_id,
            embedder=FakeEmbeddingClient(get_settings().embedding_dim),
            min_score=-1.0,
        )
    chunk_count = len(await _chunk_contents(app_role_engine, owner.workspace_id, doc_id))
    assert len(result.chunks) == min(chunk_count, get_settings().retrieval_keep)
    assert all(c.score < get_settings().retrieval_min_score for c in result.chunks)


async def test_keep_limits_the_number_of_results(
    client: AsyncClient, worker_ctx: dict
) -> None:
    owner = await signup(client, "owner@example.com")
    await _ready_document(client, worker_ctx, owner)
    await _ready_document(client, worker_ctx, owner, "shipping.md", SHIPPING_DOC)

    async with tenant_session(owner.workspace_id, owner.user_id) as db:
        result = await retrieve(
            db,
            "anything",
            top_k=8,
            workspace_id=owner.workspace_id,
            embedder=FakeEmbeddingClient(get_settings().embedding_dim),
            min_score=-1.0,
            keep=2,
        )
    assert len(result.chunks) == 2


async def test_only_ready_documents_are_searched(
    client: AsyncClient, worker_ctx: dict, owner_engine: AsyncEngine, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    doc_id = await _ready_document(client, worker_ctx, owner)
    target_text = next(iter((await _chunk_contents(
        app_role_engine, owner.workspace_id, doc_id
    )).values()))

    # Chunks still exist, but the document is no longer ready (e.g. being reindexed).
    async with owner_engine.connect() as conn, conn.begin():
        await conn.execute(SET_CONTEXT, {"wid": str(owner.workspace_id)})
        await conn.execute(
            text("UPDATE documents SET status = 'processing' WHERE id = :id"), {"id": doc_id}
        )

    resp = await client.post(SEARCH_URL, json={"query": target_text}, headers=owner.headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"] == []


async def test_workspace_b_search_never_returns_workspace_a_chunks(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    a_doc = await _ready_document(client, worker_ctx, a)
    b_doc = await _ready_document(client, worker_ctx, b, "shipping.md", SHIPPING_DOC)
    a_chunks = await _chunk_contents(app_role_engine, a.workspace_id, a_doc)

    for a_text in a_chunks.values():
        resp = await client.post(SEARCH_URL, json={"query": a_text}, headers=b.headers)
        assert resp.status_code == 200, resp.text
        returned = {r["chunk_id"] for r in resp.json()["results"]}
        assert not returned & {str(cid) for cid in a_chunks}

    # B's own content is still found, so the empty results above are not a broken search.
    b_text = next(iter((await _chunk_contents(app_role_engine, b.workspace_id, b_doc)).values()))
    resp = await client.post(SEARCH_URL, json={"query": b_text}, headers=b.headers)
    assert resp.json()["results"][0]["document_id"] == str(b_doc)


async def test_agents_can_search(
    client: AsyncClient, worker_ctx: dict, owner_engine: AsyncEngine, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    doc_id = await _ready_document(client, worker_ctx, owner)
    agent = await signup(client, "agent@example.com", workspace_name="Agent Home")
    headers = await as_agent_in(client, owner_engine, agent, owner.workspace_id)
    target_text = next(iter((await _chunk_contents(
        app_role_engine, owner.workspace_id, doc_id
    )).values()))

    resp = await client.post(SEARCH_URL, json={"query": target_text}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["document_id"] == str(doc_id)


async def test_search_validates_query_and_requires_auth(client: AsyncClient) -> None:
    owner = await signup(client, "owner@example.com")
    for query in ["", "   ", "x" * 501]:
        resp = await client.post(SEARCH_URL, json={"query": query}, headers=owner.headers)
        assert resp.status_code == 422, query
    assert (await client.post(SEARCH_URL, json={"query": "refunds"})).status_code == 401


async def test_every_embedding_call_writes_an_llm_calls_row_without_text(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    doc_id = await _ready_document(client, worker_ctx, owner)
    chunks = await _chunk_contents(app_role_engine, owner.workspace_id, doc_id)
    price = get_settings().embedding_price_per_mtok

    [ingest_row] = await _llm_calls(app_role_engine, owner.workspace_id)
    assert ingest_row["purpose"] == "embed_document"
    assert ingest_row["provider"] == "fake"
    assert ingest_row["status"] == "ok"
    assert ingest_row["error_type"] is None
    assert ingest_row["prompt_version"] is None
    expected_tokens = sum(count_tokens(c) for c in chunks.values())
    assert ingest_row["input_tokens"] == expected_tokens > 0
    assert ingest_row["output_tokens"] == 0
    assert ingest_row["cost_usd"] == (Decimal(expected_tokens) * price / 1_000_000).quantize(
        Decimal("0.00000001")
    )
    assert ingest_row["latency_ms"] >= 0

    query = "How long do refunds take?"
    resp = await client.post(
        SEARCH_URL, json={"query": query}, headers=owner.headers | {"X-Request-ID": "req-123"}
    )
    assert resp.status_code == 200, resp.text
    rows = await _llm_calls(app_role_engine, owner.workspace_id)
    assert [r["purpose"] for r in rows] == ["embed_document", "embed_query"]
    query_row = rows[1]
    assert query_row["input_tokens"] == count_tokens(query) == resp.json()["query_tokens"]
    assert query_row["request_id"] == "req-123"

    # No column of any row holds document or query text.
    for row in rows:
        stored = " ".join(str(v) for v in row.values())
        assert query not in stored
        for content in chunks.values():
            assert content not in stored
        assert "Refunds" not in stored and "returned" not in stored


async def test_failed_embedding_call_is_recorded_as_error(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    class DownEmbedder:
        dim = get_settings().embedding_dim
        provider = "fake"
        model = "fake-embedding"

        async def embed(self, texts: list[str]) -> list[list[float]]:
            raise ConnectionError("provider down")

    owner = await signup(client, "owner@example.com")
    resp = await upload_file(client, owner.headers)
    doc_id = resp.json()["id"]
    # Last attempt, so the job re-raises instead of scheduling a retry.
    with pytest.raises(ConnectionError):
        await ingest_document(
            {**worker_ctx, "embedder": DownEmbedder(), "job_try": MAX_TRIES},
            doc_id,
            str(owner.workspace_id),
        )

    [row] = await _llm_calls(app_role_engine, owner.workspace_id)
    assert row["status"] == "error"
    assert row["error_type"] == "ConnectionError"
    assert row["input_tokens"] == 0
    assert row["cost_usd"] == 0


async def test_llm_calls_are_isolated_by_workspace(
    client: AsyncClient, worker_ctx: dict, app_role_engine: AsyncEngine
) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    await _ready_document(client, worker_ctx, a)

    assert len(await _llm_calls(app_role_engine, a.workspace_id)) == 1
    assert await _llm_calls(app_role_engine, b.workspace_id) == []
