"""LLM layer: prompt registry, fake client, metering, tool calling and configuration errors."""

import json
import uuid

import httpx
import pytest
from httpx import AsyncClient
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.agent import build_widget_messages, run_agent
from app.ai.embeddings import FakeEmbeddingClient
from app.ai.llm import (
    ChatMessage,
    FakeLLMClient,
    LLMConfigError,
    LLMError,
    LLMOutputError,
    OpenAILLMClient,
    ToolSpec,
    get_llm_client,
)
from app.ai.prompts import PromptNotFoundError, load_prompt
from app.ai.tools.builtin import WIDGET_TOOLS
from app.ai.tools.registry import ToolContext
from app.ai.usage import LLMPurpose, MeteredLLMClient
from app.core.config import get_settings
from tests.conftest import signup

SET_CONTEXT = text("SELECT set_config('app.workspace_id', :wid, true)")
MESSAGES: list[ChatMessage] = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Where is my order 1234?"},
]


class Verdict(BaseModel):
    intent: str
    confidence: float


def test_prompt_registry_loads_answer_v1_with_version() -> None:
    prompt = load_prompt("answer", "v1")
    assert prompt.name == "answer"
    assert prompt.version == "v1"
    assert prompt.id == "answer_v1"
    lowered = prompt.text.lower()
    assert "cite" in lowered
    assert "don't know" in lowered
    assert "not instructions" in lowered


@pytest.mark.parametrize(
    ("name", "version"), [("answer", "v999"), ("../config", "v1"), ("answer", "v1/../x")]
)
def test_prompt_registry_rejects_unknown_or_unsafe_names(name: str, version: str) -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt(name, version)


def test_factory_uses_fake_client_in_tests() -> None:
    assert isinstance(get_llm_client(), FakeLLMClient)


async def test_fake_client_is_deterministic() -> None:
    client = FakeLLMClient()
    first = await client.complete(MESSAGES)
    assert first == await client.complete(MESSAGES)
    assert "".join([piece async for piece in client.stream(MESSAGES)]) == first


async def test_fake_client_structured_output_is_validated() -> None:
    client = FakeLLMClient({"order": '{"intent": "order_status", "confidence": 0.9}'})
    verdict = await client.complete_structured(MESSAGES, Verdict)
    assert verdict == Verdict(intent="order_status", confidence=0.9)

    with pytest.raises(LLMOutputError):
        await FakeLLMClient({"order": "not json"}).complete_structured(MESSAGES, Verdict)


async def test_openai_client_without_model_raises_config_error() -> None:
    client = OpenAILLMClient(api_key="sk-test-not-used", model="")
    with pytest.raises(LLMConfigError, match="LLM_CHAT_MODEL"):
        await client.complete(MESSAGES)
    with pytest.raises(LLMConfigError, match="LLM_CHAT_MODEL"):
        [piece async for piece in client.stream(MESSAGES)]


async def test_metered_chat_calls_write_rows_without_text(
    client: AsyncClient, app_role_engine: AsyncEngine
) -> None:
    owner = await signup(client, "owner@example.com")
    metered = MeteredLLMClient(
        FakeLLMClient(),
        workspace_id=owner.workspace_id,
        purpose=LLMPurpose.CHAT,
        prompt_version=load_prompt("answer", "v1").id,
    )
    reply = await metered.complete(MESSAGES)
    streamed = "".join([piece async for piece in metered.stream(MESSAGES)])
    assert streamed == reply

    rows = await _rows(app_role_engine, owner.workspace_id)
    assert len(rows) == 2
    for row in rows:
        assert row["purpose"] == "chat"
        assert row["prompt_version"] == "answer_v1"
        assert row["status"] == "ok"
        assert row["input_tokens"] > 0 and row["output_tokens"] > 0
        stored = " ".join(str(v) for v in row.values())
        assert "order 1234" not in stored and reply not in stored


async def _rows(engine: AsyncEngine, workspace_id: uuid.UUID) -> list[dict]:
    async with engine.connect() as conn, conn.begin():
        await conn.execute(SET_CONTEXT, {"wid": str(workspace_id)})
        result = await conn.execute(text("SELECT * FROM llm_calls ORDER BY created_at"))
        return [dict(r) for r in result.mappings()]


async def test_openai_tool_calling_sends_schemas_and_parses_calls() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_order_status",
                                        "arguments": '{"order_number": "RA-1", "email": "a@b.c"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
            },
        )

    client = OpenAILLMClient(api_key="sk-test-not-used", model="test-model")
    client._client = AsyncOpenAI(
        api_key="sk-test-not-used",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    spec = ToolSpec(name="get_order_status", description="Look up", parameters={"type": "object"})

    completion = await client.complete_with_tools(MESSAGES, [spec])

    assert seen["tools"] == [spec.to_openai()]
    assert seen["tool_choice"] == "auto"
    # GPT-6 Sol/Luna only allow function tools in Chat Completions with reasoning off.
    assert seen["reasoning_effort"] == "none"
    assert completion.text == ""
    [call] = completion.tool_calls
    assert (call.id, call.name) == ("call_1", "get_order_status")
    assert json.loads(call.arguments) == {"order_number": "RA-1", "email": "a@b.c"}
    assert (completion.input_tokens, completion.output_tokens) == (12, 5)


# Real OpenAI client over a mocked transport -------------------------------------------------

API_KEY = "sk-test-secret-do-not-log"


def _completion(message: dict) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def mocked_openai(handler, **kwargs) -> OpenAILLMClient:
    client = OpenAILLMClient(api_key=API_KEY, model="test-model", **kwargs)
    client._client = AsyncOpenAI(
        api_key=API_KEY,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return client


async def test_bad_request_is_logged_with_provider_details_but_no_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Function tools with reasoning_effort are not supported.",
                    "type": "invalid_request_error",
                    "param": "reasoning_effort",
                    "code": None,
                }
            },
        )

    client = mocked_openai(handler)
    spec = ToolSpec(name="get_order_status", description="Look up", parameters={"type": "object"})
    with caplog.at_level("WARNING", logger="app.ai.llm"), pytest.raises(LLMError):
        await client.complete_with_tools(MESSAGES, [spec])

    [record] = [r for r in caplog.records if r.name == "app.ai.llm"]
    line = record.getMessage()
    assert "BadRequestError" in line
    assert "status=400" in line
    assert "Function tools with reasoning_effort are not supported." in line
    assert "param='reasoning_effort'" in line
    assert "type='invalid_request_error'" in line
    assert API_KEY not in line and "Bearer" not in line
    assert "Where is my order 1234?" not in line and "You are helpful." not in line


async def test_reasoning_effort_is_only_sent_with_tools() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_completion({"role": "assistant", "content": "hi"}))

    spec = ToolSpec(name="get_order_status", description="Look up", parameters={"type": "object"})
    await mocked_openai(handler).complete(MESSAGES)
    await mocked_openai(handler).complete_with_tools(MESSAGES, [])
    await mocked_openai(handler, tools_reasoning_effort="").complete_with_tools(MESSAGES, [spec])

    assert all("reasoning_effort" not in body for body in bodies)


async def test_two_turn_agent_run_over_the_openai_wire_format(client: AsyncClient) -> None:
    """Tool call, then the final answer: the second request carries the assistant tool call
    and the tool result linked by its id, in the format Chat Completions expects."""
    owner = await signup(client, "owner@example.com")
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(
                200,
                json=_completion(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "get_order_status",
                                    "arguments": json.dumps(
                                        {"order_number": "RA-104", "email": "maya.robinson@example.com"}
                                    ),
                                },
                            }
                        ],
                    }
                ),
            )
        return httpx.Response(
            200,
            json=_completion({"role": "assistant", "content": "Please double-check the details."}),
        )

    result = await run_agent(
        llm=MeteredLLMClient(
            mocked_openai(handler), workspace_id=owner.workspace_id, purpose=LLMPurpose.AGENT
        ),
        messages=build_widget_messages("system", [], "Where is my order RA-104?"),
        tools=WIDGET_TOOLS,
        ctx=ToolContext(
            workspace_id=owner.workspace_id,
            embedder=FakeEmbeddingClient(get_settings().embedding_dim),
        ),
    )

    assert result.answered and result.text == "Please double-check the details."
    assert [(u.name, u.status.value) for u in result.tool_uses] == [("get_order_status", "not_found")]
    assert len(bodies) == 2
    assert all(b["reasoning_effort"] == "none" for b in bodies)
    assert [t["function"]["name"] for t in bodies[0]["tools"]] == [
        "get_order_status",
        "search_knowledge",
        "hand_off_to_team",
    ]
    assistant, tool = bodies[1]["messages"][-2:]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "get_order_status",
                "arguments": json.dumps(
                    {"order_number": "RA-104", "email": "maya.robinson@example.com"}
                ),
            },
        }
    ]
    assert tool["role"] == "tool" and tool["tool_call_id"] == "call_1"
    assert tool["content"].startswith('<tool_result name="get_order_status" status="not_found">')
