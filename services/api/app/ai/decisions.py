"""Message classification: intent, priority and whether a human is needed.

The primary provider is Cloudflare's Clef-flash decision model (Workers AI), which returns a
probability for every allowed option instead of generated text. When Cloudflare isn't
configured or a call fails, the chat LLM answers the same questions (prompt classify_v1).

Only the minimum context leaves the system: the message plus the previous two messages of the
conversation. Message text is never logged; llm_calls rows carry tokens, cost and latency only.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field

from app.ai.llm import ChatMessage, LLMError, UsageReportingLLMClient, get_llm_client
from app.ai.prompts import load_prompt
from app.ai.usage import (
    LLMCallStatus,
    LLMPurpose,
    MeteredLLMClient,
    clef_cost,
    record_llm_call,
)
from app.core.config import get_settings
from app.core.middleware import get_request_id

logger = logging.getLogger("app.ai.decisions")

Intent = Literal[
    "greeting",
    "thanks",
    "knowledge_question",
    "order_status",
    "refund_request",
    "complaint",
    "account_change",
    "other",
]
Priority = Literal["low", "normal", "high", "urgent"]

INTENT_CRITERIA: dict[str, str] = {
    "greeting": "Only says hello or opens the conversation, with no request yet.",
    "thanks": "Only thanks the team or says goodbye, with no new request.",
    "knowledge_question": (
        "Asks a general question that help articles or policies could answer "
        "(shipping times, return policy, how something works)."
    ),
    "order_status": "Asks where a specific order is, when it arrives, or for tracking.",
    "refund_request": "Asks for money back, a refund, or a return of a specific purchase.",
    "complaint": "Expresses dissatisfaction with a product, delivery or the service.",
    "account_change": (
        "Asks to change account details, email, password, address or subscription, "
        "or reports an account access problem."
    ),
    "other": "Anything that fits none of the other options.",
}
PRIORITY_CRITERIA: dict[str, str] = {
    "low": "General curiosity or feedback; nothing is blocked.",
    "normal": "A routine question or request that can wait for a normal reply.",
    "high": "The customer is blocked, upset, or money or an order is at risk.",
    "urgent": (
        "Safety issue, legal threat, payment taken twice, account hacked, or the customer is "
        "locked out of their account."
    ),
}
NEEDS_HUMAN_QUESTION = "Does this need a human agent rather than an automated answer?"
INTENTS: tuple[str, ...] = tuple(INTENT_CRITERIA)
PRIORITIES: tuple[str, ...] = tuple(PRIORITY_CRITERIA)

CLEF_MODEL = "clef-flash"
CLEF_MODEL_ID = "@cf/cloudflare/clef-flash"
CLEF_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/" + CLEF_MODEL_ID
CLEF_TIMEOUT_S = 5.0
CLEF_ATTEMPTS = 2  # one retry
CONTEXT_MESSAGES = 2
MAX_TEXT_CHARS = 2000
PROMPT_NAME, PROMPT_VERSION = "classify", "v1"


class DecisionError(Exception):
    """Classification failed (provider error, timeout or unusable output)."""


@dataclass(frozen=True)
class ContextMessage:
    role: str  # customer | assistant | agent
    content: str


@dataclass
class Classification:
    intent: str
    intent_probs: dict[str, float]
    priority: str
    priority_probs: dict[str, float]
    needs_human_prob: float
    confidence: float
    provider: str
    model: str
    # Billable tokens of this classification, for the widget's daily token budget.
    tokens: int = field(default=0)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("tokens")
        return data


class DecisionClient(Protocol):
    async def classify(
        self, text: str, context: list[ContextMessage], *, workspace_id: uuid.UUID
    ) -> Classification: ...


def _context(context: list[ContextMessage]) -> list[ContextMessage]:
    return [
        ContextMessage(role=m.role, content=m.content[:MAX_TEXT_CHARS])
        for m in context[-CONTEXT_MESSAGES:]
    ]


def _normalize(probs: dict[str, Any], options: tuple[str, ...]) -> dict[str, float]:
    values = {o: max(0.0, float(probs.get(o, 0.0) or 0.0)) for o in options}
    total = sum(values.values())
    if total <= 0:
        raise DecisionError("Classification returned no probabilities")
    return {o: round(v / total, 4) for o, v in values.items()}


# Cloudflare Clef ----------------------------------------------------------------------------


def clef_questions() -> dict[str, Any]:
    return {
        "intent": {
            "type": "choice",
            "instructions": "What is the customer's latest message mainly about?",
            "criteria": INTENT_CRITERIA,
        },
        "priority": {
            "type": "choice",
            "instructions": "How urgently does the customer's latest message need attention?",
            "criteria": PRIORITY_CRITERIA,
        },
        "needs_human": {
            "type": "noul",
            "instructions": NEEDS_HUMAN_QUESTION,
            "criteria": {
                "true": "A person must act, decide, investigate or reassure.",
                "false": "An automated reply or a help article answers it fully.",
            },
        },
    }


class CloudflareClefClient:
    provider = "cloudflare"
    model = CLEF_MODEL_ID

    def __init__(
        self,
        account_id: str,
        api_token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        meter: bool = True,
    ) -> None:
        self._url = CLEF_URL.format(account_id=account_id)
        self._token = api_token
        self._transport = transport
        # Off only for the smoke-test script, which has no workspace to meter against.
        self._meter = meter

    def _body(self, text: str, context: list[ContextMessage]) -> dict[str, Any]:
        return {
            "model": CLEF_MODEL,
            # The state is data to evaluate, not instructions to the model.
            "state": {
                "previous_messages": [
                    {"role": m.role, "text": m.content} for m in _context(context)
                ],
                "latest_customer_message": text[:MAX_TEXT_CHARS],
            },
            "questions": clef_questions(),
        }

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=CLEF_TIMEOUT_S, transport=self._transport) as client:
            for attempt in range(CLEF_ATTEMPTS):
                try:
                    resp = await client.post(
                        self._url,
                        json=body,
                        headers={"Authorization": f"Bearer {self._token}"},
                    )
                except httpx.HTTPError as exc:
                    last_error = exc
                else:
                    if resp.status_code < 400:
                        return resp.json()
                    last_error = DecisionError(f"Clef returned HTTP {resp.status_code}")
                    if resp.status_code < 500 and resp.status_code != 429:
                        break  # auth or request errors won't succeed on retry
                logger.info(
                    "Clef attempt %d/%d failed (error=%s)",
                    attempt + 1,
                    CLEF_ATTEMPTS,
                    type(last_error).__name__,
                )
                if attempt + 1 < CLEF_ATTEMPTS:
                    await asyncio.sleep(0.2)
        raise DecisionError("Clef request failed") from last_error

    @staticmethod
    def parse(payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Return (answers, input_tokens) from a Workers AI response.

        The REST API wraps model output as {"result": {...}, "success": true}; the model's
        own output is {"model", "answers", "usage": {"input_tokens", "output_tokens"}}.
        """
        data = payload.get("result", payload) if isinstance(payload, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
            raise DecisionError("Clef response has no answers")
        usage = data.get("usage") or {}
        return data["answers"], int(usage.get("input_tokens") or 0)

    async def classify(
        self, text: str, context: list[ContextMessage], *, workspace_id: uuid.UUID
    ) -> Classification:
        started = time.perf_counter()
        input_tokens = 0
        try:
            answers, input_tokens = self.parse(await self._post(self._body(text, context)))
            intent = answers["intent"]
            priority = answers["priority"]
            needs_human = answers["needs_human"]
            intent_probs = _normalize(intent["probabilities"], INTENTS)
            priority_probs = _normalize(priority["probabilities"], PRIORITIES)
            chosen_intent = intent["choice"] if intent["choice"] in INTENTS else max(
                intent_probs, key=intent_probs.__getitem__
            )
            chosen_priority = priority["choice"] if priority["choice"] in PRIORITIES else max(
                priority_probs, key=priority_probs.__getitem__
            )
            result = Classification(
                intent=chosen_intent,
                intent_probs=intent_probs,
                priority=chosen_priority,
                priority_probs=priority_probs,
                needs_human_prob=round(min(1.0, max(0.0, float(needs_human["noul"]))), 4),
                confidence=round(float(intent.get("confidence", intent_probs[chosen_intent])), 4),
                provider=self.provider,
                model=self.model,
                tokens=input_tokens,
            )
        except (DecisionError, KeyError, TypeError, ValueError) as exc:
            await self._record(workspace_id, started, input_tokens, exc)
            if isinstance(exc, DecisionError):
                raise
            raise DecisionError("Clef response could not be read") from exc
        await self._record(workspace_id, started, input_tokens, None)
        return result

    async def _record(
        self,
        workspace_id: uuid.UUID,
        started: float,
        input_tokens: int,
        error: Exception | None,
    ) -> None:
        if not self._meter:
            return
        await record_llm_call(
            workspace_id=workspace_id,
            purpose=LLMPurpose.CLASSIFY.value,
            provider=self.provider,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=0,
            cost_usd=clef_cost(input_tokens),
            latency_ms=(time.perf_counter() - started) * 1000,
            status=LLMCallStatus.ERROR if error else LLMCallStatus.OK,
            error_type=type(error.__cause__ or error).__name__[:100] if error else None,
            request_id=get_request_id() or None,
        )


# LLM fallback -------------------------------------------------------------------------------


class LLMVerdict(BaseModel):
    intent: Intent
    intent_confidence: float = Field(ge=0.0, le=1.0)
    priority: Priority
    priority_confidence: float = Field(ge=0.0, le=1.0)
    needs_human_probability: float = Field(ge=0.0, le=1.0)


def _spread(chosen: str, confidence: float, options: tuple[str, ...]) -> dict[str, float]:
    """A distribution from one choice and its confidence: the rest is shared evenly."""
    rest = (1.0 - confidence) / (len(options) - 1)
    return {o: round(confidence if o == chosen else rest, 4) for o in options}


def _escape(value: str) -> str:
    return value.replace("<", "&lt;")


class LLMDecisionClient:
    """Asks the chat LLM the same questions, with structured output."""

    def __init__(self, llm: UsageReportingLLMClient | None = None) -> None:
        self._llm = llm

    def _client(self) -> UsageReportingLLMClient:
        if self._llm is not None:
            return self._llm
        try:
            return get_llm_client()
        except LLMError as exc:
            raise DecisionError("Chat model is not configured") from exc

    async def classify(
        self, text: str, context: list[ContextMessage], *, workspace_id: uuid.UUID
    ) -> Classification:
        prompt = load_prompt(PROMPT_NAME, PROMPT_VERSION)
        inner = self._client()
        metered = MeteredLLMClient(
            inner,
            workspace_id=workspace_id,
            purpose=LLMPurpose.CLASSIFY,
            prompt_version=prompt.id,
            request_id=get_request_id() or None,
        )
        previous = "\n".join(
            f'<message role="{m.role}">{_escape(m.content)}</message>' for m in _context(context)
        )
        messages: list[ChatMessage] = [
            {"role": "system", "content": prompt.text},
            {
                "role": "user",
                "content": (
                    f"<previous_messages>\n{previous}\n</previous_messages>\n\n"
                    f"<customer_message>\n{_escape(text[:MAX_TEXT_CHARS])}\n</customer_message>"
                ),
            },
        ]
        try:
            verdict = await metered.complete_structured(messages, LLMVerdict)
        except LLMError as exc:
            raise DecisionError("LLM classification failed") from exc
        return Classification(
            intent=verdict.intent,
            intent_probs=_spread(verdict.intent, verdict.intent_confidence, INTENTS),
            priority=verdict.priority,
            priority_probs=_spread(verdict.priority, verdict.priority_confidence, PRIORITIES),
            needs_human_prob=round(verdict.needs_human_probability, 4),
            confidence=round(verdict.intent_confidence, 4),
            provider=inner.provider,
            model=inner.model or "unset",
            tokens=metered.last_input_tokens + metered.last_output_tokens,
        )


class FallbackDecisionClient:
    """Clef first; the LLM when Clef fails. Both calls are metered in llm_calls."""

    def __init__(self, primary: DecisionClient, fallback: DecisionClient) -> None:
        self.primary = primary
        self.fallback = fallback

    async def classify(
        self, text: str, context: list[ContextMessage], *, workspace_id: uuid.UUID
    ) -> Classification:
        try:
            return await self.primary.classify(text, context, workspace_id=workspace_id)
        except DecisionError as exc:
            logger.warning(
                "Clef classification failed, using LLM fallback (workspace_id=%s, error=%s)",
                workspace_id,
                type(exc.__cause__ or exc).__name__,
            )
        return await self.fallback.classify(text, context, workspace_id=workspace_id)


# Tests --------------------------------------------------------------------------------------


def fake_classification(
    intent: str = "knowledge_question",
    *,
    priority: str = "normal",
    needs_human: float = 0.05,
    confidence: float = 0.9,
) -> Classification:
    return Classification(
        intent=intent,
        intent_probs=_spread(intent, confidence, INTENTS),
        priority=priority,
        priority_probs=_spread(priority, 0.8, PRIORITIES),
        needs_human_prob=needs_human,
        confidence=confidence,
        provider="fake",
        model="fake-decisions",
    )


class FakeDecisionClient:
    """Deterministic: `rules` maps a substring of the message to a classification."""

    def __init__(
        self,
        rules: dict[str, Classification] | None = None,
        default: Classification | None = None,
    ) -> None:
        self.rules = rules or {}
        self.default = default or fake_classification()
        self.calls: list[tuple[str, list[ContextMessage]]] = []

    async def classify(
        self, text: str, context: list[ContextMessage], *, workspace_id: uuid.UUID
    ) -> Classification:
        self.calls.append((text, _context(context)))
        for needle, result in self.rules.items():
            if needle.lower() in text.lower():
                return result
        return self.default


@lru_cache
def get_decision_client() -> DecisionClient:
    settings = get_settings()
    if settings.decision_provider == "fake":
        return FakeDecisionClient()
    token = settings.cloudflare_api_token.get_secret_value() if settings.cloudflare_api_token else ""
    if settings.decision_provider == "clef" and settings.cloudflare_account_id and token:
        return FallbackDecisionClient(
            CloudflareClefClient(settings.cloudflare_account_id, token), LLMDecisionClient()
        )
    if settings.decision_provider == "clef":
        logger.warning("Cloudflare is not configured; classifying with the chat LLM")
    return LLMDecisionClient()
