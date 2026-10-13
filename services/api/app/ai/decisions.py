"""Message classification: intent, priority and whether a human is needed.

The primary provider is Cloudflare's Clef-flash decision model (Workers AI), which returns a
probability for every allowed option instead of generated text. When Cloudflare isn't
configured or a call fails, the chat LLM answers the same questions. Both are versioned
(CLASSIFY_VERSION): Clef asks the questions in prompt classify_criteria_<version>, the LLM uses
prompt classify_<version>. Older versions stay in the repo so evals can compare them.

Only the minimum context leaves the system: the message plus the previous two messages of the
conversation. Message text is never logged; llm_calls rows carry tokens, cost and latency only.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any, Literal, Protocol, get_args

import httpx
from pydantic import BaseModel, Field, create_model

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
    "cancel_order",
    "complaint",
    "account_change",
    "account_security",
    "off_topic",
    "other",
]
Priority = Literal["low", "normal", "high", "urgent"]
ClassifyVersion = Literal["v2", "v3"]
# Every intent any classifier version can return. A version's own options are in its spec.
INTENTS: tuple[str, ...] = get_args(Intent)
PRIORITIES: tuple[str, ...] = get_args(Priority)

CLEF_MODEL = "clef-flash"
CLEF_MODEL_ID = "@cf/cloudflare/clef-flash"
CLEF_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/" + CLEF_MODEL_ID
CLEF_TIMEOUT_S = 5.0
CLEF_ATTEMPTS = 2  # one retry
# The previous few messages give short replies ("yes please") their meaning. Each is cut
# short to keep the cost low; the latest message keeps MAX_TEXT_CHARS.
CONTEXT_MESSAGES = 3
CONTEXT_CHARS = 400
MAX_TEXT_CHARS = 2000
PROMPT_NAME = "classify"
CRITERIA_NAME = "classify_criteria"
# Account security always goes to a person, at high priority or above (deterministic, after
# the model: the prompt asks for it, this guarantees it).
SECURITY_INTENT = "account_security"
SECURITY_MIN_NEEDS_HUMAN = 0.95
SECURITY_PRIORITY_FLOOR = "high"


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
        ContextMessage(role=m.role, content=m.content[:CONTEXT_CHARS])
        for m in context[-CONTEXT_MESSAGES:]
    ]


def _normalize(probs: dict[str, Any], options: tuple[str, ...]) -> dict[str, float]:
    values = {o: max(0.0, float(probs.get(o, 0.0) or 0.0)) for o in options}
    total = sum(values.values())
    if total <= 0:
        raise DecisionError("Classification returned no probabilities")
    return {o: round(v / total, 4) for o, v in values.items()}


# Versioned criteria ------------------------------------------------------------------------


@dataclass(frozen=True)
class Question:
    instructions: str
    criteria: dict[str, str]


@dataclass(frozen=True)
class ClassifierSpec:
    """One classifier version: the questions (prompt classify_criteria_<version>, used as-is by
    Clef) and the LLM prompt classify_<version>."""

    version: str
    intent: Question
    priority: Question
    needs_human: Question

    @property
    def intents(self) -> tuple[str, ...]:
        return tuple(self.intent.criteria)

    @property
    def priorities(self) -> tuple[str, ...]:
        return tuple(self.priority.criteria)


def parse_criteria(text: str) -> dict[str, Question]:
    """`# name` headings, each followed by one instruction line and `- option: criterion`
    bullets."""
    questions: dict[str, Question] = {}
    name: str | None = None
    instructions: list[str] = []
    criteria: dict[str, str] = {}

    def close() -> None:
        if name is not None:
            questions[name] = Question(" ".join(instructions), dict(criteria))

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            close()
            name, instructions, criteria = line[2:].strip(), [], {}
        elif line.startswith("- ") and ":" in line:
            option, criterion = line[2:].split(":", 1)
            criteria[option.strip()] = criterion.strip()
        else:
            instructions.append(line)
    close()
    return questions


@lru_cache
def classifier_spec(version: str) -> ClassifierSpec:
    questions = parse_criteria(load_prompt(CRITERIA_NAME, version).text)
    try:
        spec = ClassifierSpec(
            version=version,
            intent=questions["intent"],
            priority=questions["priority"],
            needs_human=questions["needs_human"],
        )
    except KeyError as exc:
        raise ValueError(f"{CRITERIA_NAME}_{version} is missing a question: {exc}") from exc
    unknown = set(spec.intents) - set(INTENTS) or set(spec.priorities) - set(PRIORITIES)
    if unknown:
        raise ValueError(f"{CRITERIA_NAME}_{version} has unknown options: {sorted(unknown)}")
    return spec


def _version(version: str | None) -> str:
    return version or get_settings().classify_version


def apply_policy(c: Classification) -> Classification:
    """Deterministic rules on top of the model's answer."""
    if c.intent == SECURITY_INTENT:
        c.needs_human_prob = max(c.needs_human_prob, SECURITY_MIN_NEEDS_HUMAN)
        if PRIORITIES.index(c.priority) < PRIORITIES.index(SECURITY_PRIORITY_FLOOR):
            c.priority = SECURITY_PRIORITY_FLOOR
    return c


# Cloudflare Clef ----------------------------------------------------------------------------


def clef_questions(version: str | None = None) -> dict[str, Any]:
    spec = classifier_spec(_version(version))
    return {
        "intent": {
            "type": "choice",
            "instructions": spec.intent.instructions,
            "criteria": spec.intent.criteria,
        },
        "priority": {
            "type": "choice",
            "instructions": spec.priority.instructions,
            "criteria": spec.priority.criteria,
        },
        "needs_human": {
            "type": "noul",
            "instructions": spec.needs_human.instructions,
            "criteria": spec.needs_human.criteria,
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
        version: str | None = None,
    ) -> None:
        self.spec = classifier_spec(_version(version))
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
            "questions": clef_questions(self.spec.version),
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
            intents, priorities = self.spec.intents, self.spec.priorities
            intent_probs = _normalize(intent["probabilities"], intents)
            priority_probs = _normalize(priority["probabilities"], priorities)
            chosen_intent = intent["choice"] if intent["choice"] in intents else max(
                intent_probs, key=intent_probs.__getitem__
            )
            chosen_priority = priority["choice"] if priority["choice"] in priorities else max(
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
        return apply_policy(result)

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
            prompt_version=f"{CRITERIA_NAME}_{self.spec.version}",
            latency_ms=(time.perf_counter() - started) * 1000,
            status=LLMCallStatus.ERROR if error else LLMCallStatus.OK,
            error_type=type(error.__cause__ or error).__name__[:100] if error else None,
            request_id=get_request_id() or None,
        )


# LLM fallback -------------------------------------------------------------------------------


class LLMVerdict(BaseModel):
    intent: str
    intent_confidence: float = Field(ge=0.0, le=1.0)
    priority: Priority
    priority_confidence: float = Field(ge=0.0, le=1.0)
    needs_human_probability: float = Field(ge=0.0, le=1.0)


@lru_cache
def verdict_model(version: str) -> type[LLMVerdict]:
    """LLMVerdict with `intent` limited to the version's options (in the JSON schema too)."""
    intents = classifier_spec(version).intents
    return create_model(
        f"LLMVerdict{version.upper()}",
        __base__=LLMVerdict,
        intent=(Literal[intents], ...),  # type: ignore[valid-type]
    )


def _spread(chosen: str, confidence: float, options: tuple[str, ...]) -> dict[str, float]:
    """A distribution from one choice and its confidence: the rest is shared evenly."""
    rest = (1.0 - confidence) / (len(options) - 1)
    return {o: round(confidence if o == chosen else rest, 4) for o in options}


def _escape(value: str) -> str:
    return value.replace("<", "&lt;")


class LLMDecisionClient:
    """Asks the chat LLM the same questions, with structured output."""

    def __init__(
        self, llm: UsageReportingLLMClient | None = None, *, version: str | None = None
    ) -> None:
        self._llm = llm
        self.spec = classifier_spec(_version(version))

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
        prompt = load_prompt(PROMPT_NAME, self.spec.version)
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
            verdict = await metered.complete_structured(
                messages, verdict_model(self.spec.version)
            )
        except LLMError as exc:
            raise DecisionError("LLM classification failed") from exc
        intents, priorities = self.spec.intents, self.spec.priorities
        result = Classification(
            intent=verdict.intent,
            intent_probs=_spread(verdict.intent, verdict.intent_confidence, intents),
            priority=verdict.priority,
            priority_probs=_spread(verdict.priority, verdict.priority_confidence, priorities),
            needs_human_prob=round(verdict.needs_human_probability, 4),
            confidence=round(verdict.intent_confidence, 4),
            provider=inner.provider,
            model=inner.model or "unset",
            tokens=metered.last_input_tokens + metered.last_output_tokens,
        )
        return apply_policy(result)


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
