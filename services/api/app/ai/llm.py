"""Chat model clients. Prompts and replies are never logged; only model, tokens and latency.

Callers depend on the LLMClient protocol. The concrete clients also report token usage
(`*_with_usage`) so app.ai.usage can meter every call into llm_calls.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, NotRequired, Protocol, TypedDict, TypeVar

from openai import APIStatusError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.ai.embeddings import backoff_delay, is_retryable
from app.core.config import get_settings
from app.modules.knowledge.chunking import count_tokens

logger = logging.getLogger("app.ai.llm")

REQUEST_TIMEOUT_S = 60.0
MAX_RETRIES = 3

ModelT = TypeVar("ModelT", bound=BaseModel)
T = TypeVar("T")


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    # Assistant turns that called tools, in the OpenAI wire format.
    tool_calls: NotRequired[list[dict[str, Any]]]
    # Tool results: the id of the call they answer.
    tool_call_id: NotRequired[str]


class LLMError(Exception):
    """The provider call failed after retries."""


class LLMConfigError(LLMError):
    """The chat model is not configured (e.g. LLM_CHAT_MODEL is empty)."""


class LLMOutputError(LLMError):
    """The model returned output that does not match the requested schema."""


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ToolSpec:
    """A tool as the model sees it: name, description and a JSON schema for its arguments."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolCallRequest:
    """A tool call the model asked for. `arguments` is the raw JSON text, still unvalidated."""

    id: str
    name: str
    arguments: str


@dataclass
class ToolCompletion:
    """Either a text answer (no tool calls) or tool calls (text may still be present)."""

    text: str
    tool_calls: list[ToolCallRequest]
    input_tokens: int
    output_tokens: int


def assistant_tool_message(completion: ToolCompletion) -> ChatMessage:
    """The assistant turn to append to the conversation before its tool results."""
    return {
        "role": "assistant",
        "content": completion.text,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in completion.tool_calls
        ],
    }


@dataclass
class StreamUsage:
    """Filled in by stream_with_usage once the stream has finished."""

    input_tokens: int = 0
    output_tokens: int = 0
    done: bool = field(default=False)


class LLMClient(Protocol):
    async def complete(self, messages: list[ChatMessage]) -> str: ...

    async def complete_structured(
        self, messages: list[ChatMessage], schema: type[ModelT]
    ) -> ModelT: ...

    def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]: ...


class UsageReportingLLMClient(LLMClient, Protocol):
    provider: str
    model: str

    async def complete_with_usage(
        self, messages: list[ChatMessage], schema: type[BaseModel] | None = None
    ) -> Completion: ...

    def stream_with_usage(
        self, messages: list[ChatMessage], usage: StreamUsage
    ) -> AsyncIterator[str]: ...

    async def complete_with_tools(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> ToolCompletion: ...


PROVIDER_MESSAGE_CHARS = 300


def provider_error_details(exc: BaseException) -> str:
    """Status, message, param and code of an OpenAI API error, for logs.

    Only fields of the parsed error body: never request headers, the API key or the prompt.
    The message is cut short because providers sometimes echo a piece of the request.
    """
    if not isinstance(exc, APIStatusError):
        return ""
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error", body) if isinstance(body.get("error", body), dict) else {}
    message = str(error.get("message") or exc.message or "")[:PROVIDER_MESSAGE_CHARS]
    return (
        f", status={exc.status_code}, message={message!r}, param={error.get('param')!r}, "
        f"code={error.get('code')!r}, type={error.get('type')!r}"
    )


def parse_structured(text: str, schema: type[ModelT]) -> ModelT:
    try:
        return schema.model_validate_json(text)
    except ValidationError as exc:
        raise LLMOutputError(f"Model output does not match {schema.__name__}") from exc


class _UsageClientBase:
    """Derives the LLMClient methods from the two *_with_usage primitives."""

    async def complete_with_usage(
        self, messages: list[ChatMessage], schema: type[BaseModel] | None = None
    ) -> Completion:
        raise NotImplementedError

    def stream_with_usage(
        self, messages: list[ChatMessage], usage: StreamUsage
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    async def complete_with_tools(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> ToolCompletion:
        raise NotImplementedError

    async def complete(self, messages: list[ChatMessage]) -> str:
        return (await self.complete_with_usage(messages)).text

    async def complete_structured(
        self, messages: list[ChatMessage], schema: type[ModelT]
    ) -> ModelT:
        return parse_structured((await self.complete_with_usage(messages, schema)).text, schema)

    def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        return self.stream_with_usage(messages, StreamUsage())


class OpenAILLMClient(_UsageClientBase):
    provider = "openai"

    def __init__(self, api_key: str, model: str, tools_reasoning_effort: str = "none") -> None:
        # Retries are handled here so backoff and logging are under our control.
        self._client = AsyncOpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
        self.model = model
        self.tools_reasoning_effort = tools_reasoning_effort

    def _require_model(self) -> str:
        if not self.model:
            raise LLMConfigError("LLM_CHAT_MODEL is not set; configure a chat model to use the LLM")
        return self.model

    async def _with_retries(self, call: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        while True:
            try:
                return await call()
            except Exception as exc:
                if not is_retryable(exc) or attempt >= MAX_RETRIES:
                    logger.warning(
                        "Chat request failed (error=%s, attempts=%d%s)",
                        type(exc).__name__,
                        attempt + 1,
                        provider_error_details(exc),
                    )
                    raise LLMError("Chat provider request failed") from exc
                delay = backoff_delay(attempt)
                attempt += 1
                logger.info(
                    "Chat request retry %d/%d in %.1fs (error=%s)",
                    attempt,
                    MAX_RETRIES,
                    delay,
                    type(exc).__name__,
                )
                await asyncio.sleep(delay)

    async def complete_with_usage(
        self, messages: list[ChatMessage], schema: type[BaseModel] | None = None
    ) -> Completion:
        model = self._require_model()
        kwargs: dict[str, Any] = {}
        if schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            }
        started = time.perf_counter()
        resp = await self._with_retries(
            lambda: self._client.chat.completions.create(
                model=model, messages=messages, **kwargs  # type: ignore[arg-type]
            )
        )
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        usage = resp.usage
        completion = Completion(
            text=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
        logger.info(
            "Chat completion (model=%s, input_tokens=%d, output_tokens=%d, latency_ms=%.0f)",
            model,
            completion.input_tokens,
            completion.output_tokens,
            (time.perf_counter() - started) * 1000,
        )
        return completion

    async def complete_with_tools(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> ToolCompletion:
        model = self._require_model()
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = [t.to_openai() for t in tools]
            kwargs["tool_choice"] = "auto"
            # GPT-6 Sol/Luna reject function tools in Chat Completions unless reasoning is off.
            if self.tools_reasoning_effort:
                kwargs["reasoning_effort"] = self.tools_reasoning_effort
        started = time.perf_counter()
        resp = await self._with_retries(
            lambda: self._client.chat.completions.create(
                model=model, messages=messages, **kwargs  # type: ignore[arg-type]
            )
        )
        message = resp.choices[0].message if resp.choices else None
        calls = [
            ToolCallRequest(id=c.id, name=c.function.name, arguments=c.function.arguments or "")
            for c in ((message.tool_calls or []) if message else [])
            if c.type == "function"
        ]
        usage = resp.usage
        completion = ToolCompletion(
            text=(message.content or "") if message else "",
            tool_calls=calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
        logger.info(
            "Chat tool completion (model=%s, tool_calls=%d, input_tokens=%d, "
            "output_tokens=%d, latency_ms=%.0f)",
            model,
            len(calls),
            completion.input_tokens,
            completion.output_tokens,
            (time.perf_counter() - started) * 1000,
        )
        return completion

    async def stream_with_usage(
        self, messages: list[ChatMessage], usage: StreamUsage
    ) -> AsyncIterator[str]:
        model = self._require_model()
        # Only opening the stream is retried; a failure mid-stream is surfaced to the caller.
        stream = await self._with_retries(
            lambda: self._client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
                stream_options={"include_usage": True},
            )
        )
        try:
            async for chunk in stream:
                if chunk.usage is not None:
                    usage.input_tokens = chunk.usage.prompt_tokens
                    usage.output_tokens = chunk.usage.completion_tokens
                for choice in chunk.choices:
                    if choice.delta.content:
                        yield choice.delta.content
        except Exception as exc:
            raise LLMError("Chat stream failed") from exc
        usage.done = True


def fake_tool_call(name: str, arguments: dict[str, Any] | str) -> ToolCompletion:
    """A scripted model turn that calls one tool (for FakeLLMClient's `script`)."""
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    call_id = "call_" + hashlib.sha256(f"{name}:{raw}".encode()).hexdigest()[:12]
    return ToolCompletion(
        text="",
        tool_calls=[ToolCallRequest(id=call_id, name=name, arguments=raw)],
        input_tokens=0,
        output_tokens=0,
    )


def fake_text(text: str) -> ToolCompletion:
    """A scripted model turn that answers with text and calls no tool."""
    return ToolCompletion(text=text, tool_calls=[], input_tokens=0, output_tokens=0)


class FakeLLMClient(_UsageClientBase):
    """Deterministic replies for tests. No network.

    `responses` maps a substring of the last user message to a canned reply; otherwise the
    reply is a stable digest of the conversation. Structured calls must use a canned reply.

    `script` drives complete_with_tools: each call takes the next scripted turn (see
    fake_tool_call and fake_text), across runs. Once it is used up, calls answer with text
    chosen as above.
    """

    provider = "fake"
    model = "fake-chat"

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        script: list[ToolCompletion] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.script = list(script or [])
        # The messages and tool names of every complete_with_tools call, for assertions.
        self.tool_requests: list[tuple[list[ChatMessage], list[str]]] = []

    def _reply(self, messages: list[ChatMessage]) -> str:
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        for needle, reply in self.responses.items():
            if needle in last_user:
                return reply
        digest = hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()
        return f"fake reply {digest[:12]}"

    async def complete_with_usage(
        self, messages: list[ChatMessage], schema: type[BaseModel] | None = None
    ) -> Completion:
        text = self._reply(messages)
        return Completion(
            text=text,
            input_tokens=sum(count_tokens(m["content"]) for m in messages),
            output_tokens=count_tokens(text),
        )

    async def complete_with_tools(
        self, messages: list[ChatMessage], tools: list[ToolSpec]
    ) -> ToolCompletion:
        self.tool_requests.append((list(messages), [t.name for t in tools]))
        turn = self.script.pop(0) if self.script else fake_text(self._reply(messages))
        return ToolCompletion(
            text=turn.text,
            tool_calls=list(turn.tool_calls),
            input_tokens=sum(count_tokens(m["content"]) for m in messages),
            output_tokens=count_tokens(turn.text)
            + sum(count_tokens(c.arguments) for c in turn.tool_calls),
        )

    async def stream_with_usage(
        self, messages: list[ChatMessage], usage: StreamUsage
    ) -> AsyncIterator[str]:
        completion = await self.complete_with_usage(messages)
        for i, word in enumerate(completion.text.split(" ")):
            yield word if i == 0 else f" {word}"
        usage.input_tokens = completion.input_tokens
        usage.output_tokens = completion.output_tokens
        usage.done = True


@lru_cache
def get_llm_client() -> UsageReportingLLMClient:
    settings = get_settings()
    if settings.llm_provider == "fake":
        return FakeLLMClient()
    if settings.openai_api_key is None or not settings.openai_api_key.get_secret_value():
        raise LLMConfigError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
    return OpenAILLMClient(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.llm_chat_model,
        tools_reasoning_effort=settings.llm_tools_reasoning_effort,
    )
