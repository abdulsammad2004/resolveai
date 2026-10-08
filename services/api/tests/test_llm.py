"""LLM layer: prompt registry, fake client, metering, and configuration errors."""

import uuid

import pytest
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.ai.llm import (
    ChatMessage,
    FakeLLMClient,
    LLMConfigError,
    LLMOutputError,
    OpenAILLMClient,
    get_llm_client,
)
from app.ai.prompts import PromptNotFoundError, load_prompt
from app.ai.usage import LLMPurpose, MeteredLLMClient
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
