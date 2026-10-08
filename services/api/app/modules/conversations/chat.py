"""Grounded widget answers: retrieve, stream the model, validate citations, persist.

The pipeline runs as its own task and hands SSE events to the response through a queue,
so a customer closing the tab mid-answer does not lose the stored answer or its metering.
Message text is never logged; only ids, counts and outcomes.
"""

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.ai.embeddings import EmbeddingClient
from app.ai.llm import ChatMessage, UsageReportingLLMClient
from app.ai.prompts import load_prompt
from app.ai.usage import LLMPurpose, MeteredLLMClient
from app.core.config import get_settings
from app.core.deps import tenant_session
from app.modules.conversations import service
from app.modules.conversations.limits import BudgetUnavailableError, WidgetLimiter
from app.modules.conversations.models import Message, MessageRole
from app.modules.conversations.schemas import Citation, FinalEvent
from app.modules.knowledge.retrieval import RetrievedChunk, retrieve

logger = logging.getLogger("app.conversations.chat")

FALLBACK_MESSAGE = (
    "I couldn't find that in our help docs. Someone from the team can follow up here."
)
ERROR_MESSAGE = "Something went wrong while answering. Please try again."
PROMPT_NAME, PROMPT_VERSION = "answer", "v1"
HISTORY_MESSAGES = 6
HISTORY_CHARS = 2000
SNIPPET_CHARS = 600

# [S1], [S1, S3] and [S1][S2] all count; anything else in brackets is left alone.
CITATION_GROUP = re.compile(r"\[\s*(S\d+(?:\s*,\s*S\d+)*)\s*\]")
_SOURCE_ID = re.compile(r"S\d+")
# Text that could close or open our delimiters inside untrusted content.
_DELIMITERS = re.compile(r"<(/?)(sources?|customer_message)\b", re.IGNORECASE)

_tasks: set[asyncio.Task[None]] = set()


@dataclass
class HistoryItem:
    role: str
    content: str


@dataclass
class Answer:
    content: str
    citations: list[Citation] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return bool(self.citations)


def _neutralize(value: str) -> str:
    return _DELIMITERS.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", value)


def _attr(value: str) -> str:
    escaped = value.replace("&", "&amp;").replace('"', "&quot;").replace("\n", " ")
    return _neutralize(escaped)


def source_id(index: int) -> str:
    return f"S{index + 1}"


def build_messages(
    system_prompt: str, history: list[HistoryItem], chunks: list[RetrievedChunk], question: str
) -> list[ChatMessage]:
    messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
    for item in history[-HISTORY_MESSAGES:]:
        # Old answers cite old sources; drop their markers so ids can't be confused.
        content = CITATION_GROUP.sub("", item.content)[:HISTORY_CHARS].strip()
        if not content:
            continue
        role = "user" if item.role == MessageRole.CUSTOMER else "assistant"
        messages.append({"role": role, "content": _neutralize(content)})

    blocks = []
    for i, chunk in enumerate(chunks):
        section = " > ".join(chunk.heading_path)
        blocks.append(
            f'<source id="{source_id(i)}" title="{_attr(chunk.document_title)}"'
            f' section="{_attr(section)}">\n{_neutralize(chunk.content)}\n</source>'
        )
    sources = "\n".join(blocks)
    messages.append(
        {
            "role": "user",
            "content": (
                f"<sources>\n{sources}\n</sources>\n\n"
                f"<customer_message>\n{_neutralize(question)}\n</customer_message>"
            ),
        }
    )
    return messages


def validate_citations(text: str, chunks: list[RetrievedChunk]) -> Answer:
    """Keep only [S#] ids that were retrieved. No valid citation left means the fallback."""
    by_id = {source_id(i): chunk for i, chunk in enumerate(chunks)}
    cited: list[str] = []

    def keep_valid(match: re.Match[str]) -> str:
        ids = [sid for sid in _SOURCE_ID.findall(match.group(1)) if sid in by_id]
        for sid in ids:
            if sid not in cited:
                cited.append(sid)
        return "".join(f"[{sid}]" for sid in dict.fromkeys(ids))

    content = CITATION_GROUP.sub(keep_valid, text)
    content = re.sub(r"[ \t]+([.,;:!?])", r"\1", content)
    content = re.sub(r"[ \t]{2,}", " ", content).strip()
    if not cited or not content:
        return Answer(content=FALLBACK_MESSAGE)
    return Answer(
        content=content,
        citations=[
            Citation(
                source_id=sid,
                chunk_id=by_id[sid].chunk_id,
                document_id=by_id[sid].document_id,
                title=by_id[sid].document_title,
                heading_path=by_id[sid].heading_path,
                snippet=by_id[sid].content[:SNIPPET_CHARS],
            )
            for sid in cited
        ],
    )


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


@dataclass
class AnswerRequest:
    workspace_id: uuid.UUID
    conversation_id: uuid.UUID
    question: str
    history: list[HistoryItem]
    llm: UsageReportingLLMClient
    embedder: EmbeddingClient
    limiter: WidgetLimiter
    request_id: str | None = None


class _Pipeline:
    def __init__(self, req: AnswerRequest, queue: asyncio.Queue[str | None]) -> None:
        self.req = req
        self.queue = queue

    def emit(self, event: str, data: dict[str, Any]) -> None:
        self.queue.put_nowait(sse(event, data))

    async def _budget_left(self) -> bool:
        budget = get_settings().widget_daily_token_budget
        try:
            used = await self.req.limiter.tokens_used_today(self.req.workspace_id)
        except BudgetUnavailableError:
            logger.warning("Token budget unavailable (workspace_id=%s)", self.req.workspace_id)
            return False
        return used < budget

    async def _save(
        self,
        answer: Answer,
        *,
        llm_call_id: uuid.UUID | None = None,
        prompt_version: str | None = None,
    ) -> None:
        async with tenant_session(self.req.workspace_id) as db:
            message: Message = await service.add_assistant_message(
                db,
                workspace_id=self.req.workspace_id,
                conversation_id=self.req.conversation_id,
                content=answer.content,
                citations=[c.model_dump(mode="json") for c in answer.citations],
                grounded=answer.grounded,
                llm_call_id=llm_call_id,
                prompt_version=prompt_version,
            )
        final = FinalEvent(
            id=message.id,
            content=answer.content,
            citations=answer.citations,
            grounded=answer.grounded,
        )
        self.emit("final", final.model_dump(mode="json"))

    async def run(self) -> None:
        req = self.req
        if not await self._budget_left():
            logger.info("Widget answer: budget exhausted (workspace_id=%s)", req.workspace_id)
            await self._save(Answer(content=FALLBACK_MESSAGE))
            return

        async with tenant_session(req.workspace_id) as db:
            result = await retrieve(
                db, req.question, workspace_id=req.workspace_id, embedder=req.embedder
            )
        chunks = result.chunks
        if not chunks:
            logger.info(
                "Widget answer: no sources (conversation_id=%s)", req.conversation_id
            )
            await self._save(Answer(content=FALLBACK_MESSAGE))
            return

        prompt = load_prompt(PROMPT_NAME, PROMPT_VERSION)
        metered = MeteredLLMClient(
            req.llm,
            workspace_id=req.workspace_id,
            purpose=LLMPurpose.CHAT,
            prompt_version=prompt.id,
            request_id=req.request_id,
        )
        pieces: list[str] = []
        try:
            async for piece in metered.stream(
                build_messages(prompt.text, req.history, chunks, req.question)
            ):
                pieces.append(piece)
                self.emit("token", {"text": piece})
        finally:
            await req.limiter.add_tokens(
                req.workspace_id, metered.last_input_tokens + metered.last_output_tokens
            )

        answer = validate_citations("".join(pieces), chunks)
        logger.info(
            "Widget answer (conversation_id=%s, sources=%d, cited=%d, grounded=%s)",
            req.conversation_id,
            len(chunks),
            len(answer.citations),
            answer.grounded,
        )
        await self._save(answer, llm_call_id=metered.last_call_id, prompt_version=prompt.id)

    async def run_safely(self) -> None:
        try:
            await self.run()
        except Exception as exc:  # noqa: BLE001 - the stream must always end with an event
            logger.warning(
                "Widget answer failed (conversation_id=%s, error=%s)",
                self.req.conversation_id,
                type(exc.__cause__ or exc).__name__,
            )
            self.emit("error", {"message": ERROR_MESSAGE})
        finally:
            self.queue.put_nowait(None)


async def stream_answer(req: AnswerRequest) -> AsyncIterator[str]:
    """SSE body: `token` events while the model writes, then `final` (or `error`)."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    task = asyncio.create_task(_Pipeline(req, queue).run_safely())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)

    # A comment line first, so proxies see bytes immediately and flush the headers.
    yield ": stream open\n\n"
    while (item := await queue.get()) is not None:
        yield item
