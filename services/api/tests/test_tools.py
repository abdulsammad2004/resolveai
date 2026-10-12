"""Tool registry and runtime: schema and business validation, the neutral order lookup,
write tools becoming proposals (never executed), and tool_calls logging."""

import json
import re
import uuid

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.decisions import FakeDecisionClient, get_decision_client
from app.ai.decisions import fake_classification as clf
from app.ai.embeddings import FakeEmbeddingClient
from app.ai.llm import fake_tool_call
from app.ai.tools.builtin import ORDER_NOT_FOUND, REGISTRY, WIDGET_TOOLS
from app.ai.tools.models import ToolCallStatus
from app.ai.tools.registry import PROPOSED_MESSAGE, ToolContext, run_tool
from app.core.config import get_settings
from tests.conftest import SignedUp, signup
from tests.test_widget import ready_chunk, rows

ORDER = "RA-10421"
ORDER_EMAIL = "maya.robinson@example.com"


@pytest.fixture(autouse=True)
def decider(app: FastAPI) -> FakeDecisionClient:
    fake = FakeDecisionClient({}, default=clf("refund_request"))
    app.dependency_overrides[get_decision_client] = lambda: fake
    return fake


async def seed_orders(client: AsyncClient, user: SignedUp) -> None:
    resp = await client.post("/api/v1/mock-orders/seed", headers=user.headers)
    assert resp.status_code == 200, resp.text


async def manual_ticket(client: AsyncClient, user: SignedUp, email: str = ORDER_EMAIL) -> str:
    resp = await client.post(
        "/api/v1/tickets",
        json={"subject": "Refund please", "description": "I want my money back", "contact_email": email},
        headers=user.headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def context(user: SignedUp, **extra) -> ToolContext:
    return ToolContext(
        workspace_id=user.workspace_id,
        embedder=FakeEmbeddingClient(get_settings().embedding_dim),
        **extra,
    )


async def call(ctx: ToolContext, name: str, args: dict | str, tools=None):
    allowed = {t.name: t for t in tools} if tools is not None else REGISTRY
    return await run_tool(fake_tool_call(name, args).tool_calls[0], allowed, ctx)


# get_order_status ---------------------------------------------------------------------------


async def test_order_lookup_with_matching_email_returns_details(
    client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    await seed_orders(client, owner)

    result = await call(
        context(owner), "get_order_status", {"order_number": "ra-10421", "email": "Maya.Robinson@Example.com"}
    )

    assert result.status is ToolCallStatus.OK
    details = json.loads(result.content)
    assert details["order_number"] == ORDER
    assert details["status"] == "shipped"
    assert details["carrier"] == "UPS"
    assert details["tracking_number"] == "1Z999AA10123456784"
    assert details["eta"]
    assert {i["name"] for i in details["items"]} == {"Canvas tote", "Wool beanie"}
    # Only what the customer needs: no email, no totals, no prices.
    assert set(details) == {"order_number", "status", "carrier", "tracking_number", "eta", "items"}
    assert "unit_price" not in result.content
    assert result.summary == f"Looked up order {ORDER} — shipped"

    [logged] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM tool_calls")
    assert logged["tool_name"] == "get_order_status"
    assert logged["status"] == "ok"
    assert logged["arguments"] == {"order_number": "ra-10421", "email": "M***@Example.com"}
    assert logged["result_summary"] == f"Looked up order {ORDER} — shipped"


@pytest.mark.parametrize(
    "args",
    [
        {"order_number": ORDER, "email": "someone.else@example.com"},
        {"order_number": "RA-99999", "email": ORDER_EMAIL},
        {"order_number": "RA-99999", "email": "someone.else@example.com"},
    ],
    ids=["wrong-email", "unknown-order", "both-wrong"],
)
async def test_order_lookup_misses_are_indistinguishable(client: AsyncClient, args) -> None:
    owner = await signup(client, "owner@example.com")
    await seed_orders(client, owner)

    result = await call(context(owner), "get_order_status", args)

    assert result.status is ToolCallStatus.NOT_FOUND
    assert result.content == ORDER_NOT_FOUND


async def test_another_workspaces_order_is_never_found(client: AsyncClient) -> None:
    a = await signup(client, "a@example.com", workspace_name="Tenant A")
    b = await signup(client, "b@example.com", workspace_name="Tenant B")
    await seed_orders(client, b)  # only B has orders

    result = await call(context(a), "get_order_status", {"order_number": ORDER, "email": ORDER_EMAIL})

    assert result.status is ToolCallStatus.NOT_FOUND
    assert result.content == ORDER_NOT_FOUND


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"order_number": ORDER}, "email"),
        ({"order_number": ORDER, "email": ORDER_EMAIL, "workspace_id": str(uuid.uuid4())}, "workspace_id"),
        ({"order_number": "https://evil.example/x", "email": ORDER_EMAIL}, "order_number"),
        ("not json", "JSON object"),
        ("[1, 2]", "JSON object"),
    ],
    ids=["missing-email", "extra-field", "url-as-order", "not-json", "not-object"],
)
async def test_invalid_arguments_return_a_message_not_an_exception(
    client: AsyncClient, app_role_engine: AsyncEngine, args, expected
) -> None:
    owner = await signup(client, "owner@example.com")

    result = await call(context(owner), "get_order_status", args)

    assert result.status is ToolCallStatus.INVALID
    assert expected in result.content
    [logged] = await rows(app_role_engine, owner.workspace_id, "SELECT status FROM tool_calls")
    assert logged["status"] == "invalid"


async def test_unknown_or_disallowed_tools_are_denied(
    client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    ticket_id = uuid.UUID(await manual_ticket(client, owner))
    ctx = context(owner, ticket_id=ticket_id, customer_asked_refund=True)

    unknown = await call(ctx, "run_sql", {"query": "DROP TABLE tickets"})
    # The widget only has read tools: request_refund doesn't exist there.
    disallowed = await call(
        ctx, "request_refund", {"order_number": ORDER, "reason": "please"}, tools=WIDGET_TOOLS
    )

    assert unknown.status is ToolCallStatus.DENIED
    assert disallowed.status is ToolCallStatus.DENIED
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM action_requests") == []


async def test_search_knowledge_returns_numbered_sources(
    client: AsyncClient,
    worker_ctx: dict,
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "retrieval_min_score", -1.0)
    owner = await signup(client, "owner@example.com")
    await ready_chunk(client, worker_ctx, owner, owner_engine)
    ctx = context(owner)

    result = await call(ctx, "search_knowledge", {"query": "How do returns work?"})

    assert result.status is ToolCallStatus.OK
    assert result.content.startswith("<sources>")
    assert '<source id="S1"' in result.content
    assert ctx.sources and ctx.sources[0].document_title


# Write and sensitive tools ------------------------------------------------------------------


async def test_refund_request_is_proposed_never_executed(
    client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    await seed_orders(client, owner)
    ticket_id = uuid.UUID(await manual_ticket(client, owner))
    ctx = context(owner, ticket_id=ticket_id, contact_email=ORDER_EMAIL, customer_asked_refund=True)
    args = {"order_number": ORDER, "reason": "Item arrived damaged", "amount": "24.00"}

    first = await call(ctx, "request_refund", args)
    again = await call(ctx, "request_refund", args)  # the same proposal is stored once

    assert first.status is ToolCallStatus.PROPOSED
    assert first.content == PROPOSED_MESSAGE
    assert again.status is ToolCallStatus.PROPOSED
    [action] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM action_requests")
    assert action["tool_name"] == "request_refund"
    assert action["risk"] == "sensitive"
    assert action["status"] == "proposed"
    assert action["reason"] == "Item arrived damaged"
    assert action["arguments"] == args
    assert action["ticket_id"] == ticket_id
    assert len(action["idempotency_key"]) == 64
    # Nothing ran: no result, nobody approved it.
    assert action["result"] is None
    assert action["decided_by"] is None
    statuses = await rows(app_role_engine, owner.workspace_id, "SELECT status FROM tool_calls")
    assert [r["status"] for r in statuses] == ["proposed", "proposed"]


async def test_escalation_is_a_write_proposal(
    client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    ticket_id = uuid.UUID(await manual_ticket(client, owner))

    result = await call(
        context(owner, ticket_id=ticket_id), "escalate_to_human", {"reason": "Customer is upset"}
    )

    assert result.status is ToolCallStatus.PROPOSED
    [action] = await rows(app_role_engine, owner.workspace_id, "SELECT * FROM action_requests")
    assert (action["tool_name"], action["risk"], action["status"]) == (
        "escalate_to_human",
        "write",
        "proposed",
    )


@pytest.mark.parametrize(
    ("args", "ctx_extra", "expected"),
    [
        ({"order_number": ORDER, "reason": "x" * 5, "amount": "500.00"}, {}, "more than the order total"),
        ({"order_number": "RA-99999", "reason": "damaged"}, {}, "No order"),
        ({"order_number": "RA-10425", "reason": "damaged"}, {"contact_email": "emma.wilson@example.com"}, "cancelled"),
        ({"order_number": "RA-10422", "reason": "damaged"}, {}, "doesn't belong"),
        ({"order_number": ORDER, "reason": "damaged"}, {"customer_asked_refund": False}, "customer asked"),
        ({"order_number": ORDER, "reason": "damaged", "amount": "-5"}, {}, "amount"),
    ],
    ids=["over-total", "unknown-order", "cancelled", "other-customer", "not-requested", "negative"],
)
async def test_refund_business_rules(
    client: AsyncClient, app_role_engine: AsyncEngine, args, ctx_extra, expected
) -> None:
    owner = await signup(client, "owner@example.com")
    await seed_orders(client, owner)
    ticket_id = uuid.UUID(await manual_ticket(client, owner))
    extra = {"contact_email": ORDER_EMAIL, "customer_asked_refund": True, **ctx_extra}

    result = await call(context(owner, ticket_id=ticket_id, **extra), "request_refund", args)

    assert result.status is ToolCallStatus.INVALID
    assert expected in result.content
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM action_requests") == []


async def test_write_tools_need_a_ticket(client: AsyncClient, app_role_engine: AsyncEngine) -> None:
    owner = await signup(client, "owner@example.com")

    result = await call(context(owner), "escalate_to_human", {"reason": "Customer is upset"})

    assert result.status is ToolCallStatus.DENIED
    assert await rows(app_role_engine, owner.workspace_id, "SELECT * FROM action_requests") == []


def test_model_sees_only_json_schemas_without_context_ids() -> None:
    for tool in REGISTRY.values():
        spec = tool.spec().to_openai()
        properties = spec["function"]["parameters"]["properties"]
        assert not {"workspace_id", "conversation_id", "ticket_id", "url"} & set(properties)
        assert spec["function"]["parameters"].get("additionalProperties") is False


# Tool schemas -------------------------------------------------------------------------------

# A valid call for every registered tool: it must pass both the JSON schema the model sees
# and the Pydantic model the runtime validates with, so the two can't drift apart.
SAMPLE_ARGS = {
    "search_knowledge": {"query": "How long do returns take?"},
    "get_order_status": {"order_number": "RA-10421", "email": "maya.robinson@example.com"},
    "request_refund": {"order_number": "RA-10421", "reason": "Arrived torn", "amount": 24.5},
    "request_cancellation": {"order_number": "RA-10422", "reason": "Ordered twice"},
    "escalate_to_human": {"reason": "Customer is upset"},
    "hand_off_to_team": {"reason": "Customer wants to cancel order RA-10421"},
}
TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _walk(schema: dict):
    """Every sub-schema (properties, anyOf branches, items, $defs)."""
    yield schema
    for key in ("properties", "$defs"):
        for sub in schema.get(key, {}).values():
            yield from _walk(sub)
    for sub in schema.get("anyOf", []):
        yield from _walk(sub)
    if isinstance(schema.get("items"), dict):
        yield from _walk(schema["items"])


def test_every_registered_tool_has_a_sample() -> None:
    assert set(SAMPLE_ARGS) == set(REGISTRY)


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_tool_schema_is_valid_for_openai(name: str) -> None:
    tool = REGISTRY[name]
    spec = tool.spec().to_openai()

    # The documented Chat Completions `tools` entry shape.
    assert set(spec) == {"type", "function"} and spec["type"] == "function"
    function = spec["function"]
    assert set(function) == {"name", "description", "parameters"}
    assert TOOL_NAME.match(function["name"]) and function["name"] == name
    assert function["description"].strip()
    json.dumps(spec)  # serialisable as sent

    params = function["parameters"]
    Draft202012Validator.check_schema(params)
    assert params["type"] == "object"
    assert params["properties"]
    assert params["additionalProperties"] is False
    assert set(params.get("required", [])) <= set(params["properties"])
    # The runtime injects these; the model must never be able to send them.
    assert not {"workspace_id", "conversation_id", "ticket_id", "url"} & set(params["properties"])
    for sub in _walk(params):
        if "pattern" in sub:
            re.compile(sub["pattern"])
    for prop in params["properties"].values():
        assert "type" in prop or "anyOf" in prop

    # The schema and the Pydantic model accept the same valid call...
    sample = SAMPLE_ARGS[name]
    Draft202012Validator(params).validate(sample)
    tool.input_model.model_validate(sample)
    # ...and both reject an extra field.
    extra = {**sample, "workspace_id": str(uuid.uuid4())}
    assert not Draft202012Validator(params).is_valid(extra)
    with pytest.raises(ValidationError):
        tool.input_model.model_validate(extra)
