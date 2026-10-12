import datetime as dt
from typing import Annotated

from pydantic import AfterValidator, BaseModel

RANGES = (7, 30, 90)


def _check_range(days: int) -> int:
    if days not in RANGES:
        raise ValueError("days must be 7, 30 or 90")
    return days


RangeDays = Annotated[int, AfterValidator(_check_range)]


class DayPoint(BaseModel):
    day: dt.date
    conversations: int
    contained: int
    handed_off: int
    tickets: int
    cost_usd: float


class ConversationStats(BaseModel):
    total: int
    # No ticket, and the last assistant reply was neither a fallback nor rated thumbs down.
    contained: int
    contained_rate: float | None
    handed_off: int
    handoff_rate: float | None
    # The last assistant reply was the "couldn't find that in our help docs" fallback.
    fallback_ended: int
    # No ticket, but the last assistant reply was rated thumbs down.
    thumbs_down_ended: int


class CountItem(BaseModel):
    key: str
    count: int


class DurationStats(BaseModel):
    count: int
    median_s: float | None
    p90_s: float | None


class TicketStats(BaseModel):
    total: int
    by_intent: list[CountItem]
    by_priority: list[CountItem]
    first_response: DurationStats
    resolution: DurationStats


class DraftStats(BaseModel):
    """AI drafts created in the range. Sent text is compared with what the AI wrote, with
    whitespace normalised."""

    sent_as_is: int
    sent_edited: int
    rejected: int
    # sent_edited / (sent_as_is + sent_edited)
    edit_rate: float | None
    # (sent_as_is + sent_edited) / (sent + rejected)
    acceptance_rate: float | None


class ActionTypeStats(BaseModel):
    tool_name: str
    proposed: int
    # Approved by a person (includes those that then ran, succeeded or failed).
    approved: int
    rejected: int
    succeeded: int
    failed: int


class SatisfactionStats(BaseModel):
    answer_up: int
    answer_down: int
    resolution_up: int
    resolution_down: int


class PurposeCost(BaseModel):
    # classify, answer, agent, draft, embedding
    purpose: str
    calls: int
    cost_usd: float


class ModelCost(BaseModel):
    model: str
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    avg_latency_ms: float | None


class CostDay(BaseModel):
    day: dt.date
    classify: float
    answer: float
    agent: float
    draft: float
    embedding: float


class LLMStats(BaseModel):
    calls: int
    errors: int
    total_cost_usd: float
    cost_per_conversation: float | None
    by_purpose: list[PurposeCost]
    by_model: list[ModelCost]
    daily: list[CostDay]


class AnalyticsOverview(BaseModel):
    days: int
    since: dt.datetime
    series: list[DayPoint]
    conversations: ConversationStats
    tickets: TicketStats
    drafts: DraftStats
    actions: list[ActionTypeStats]
    satisfaction: SatisfactionStats
    llm: LLMStats


class KnowledgeGap(BaseModel):
    # A representative question, with emails, phone numbers, links and long numbers masked.
    question: str
    count: int
    last_seen: dt.datetime


class KnowledgeGapsOut(BaseModel):
    days: int
    total_fallbacks: int
    gaps: list[KnowledgeGap]
