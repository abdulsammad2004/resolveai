"""Workspace analytics. Every number is aggregated in Postgres, one query per section, inside
the caller's tenant transaction (RLS) and filtered by workspace_id as well. Days are UTC.

Nothing here returns message text except the knowledge gaps, which show one masked example
question per group and never contact details.
"""

import datetime as dt
import re
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.schemas import (
    ActionTypeStats,
    AnalyticsOverview,
    ConversationStats,
    CostDay,
    CountItem,
    DayPoint,
    DraftStats,
    DurationStats,
    KnowledgeGap,
    KnowledgeGapsOut,
    LLMStats,
    ModelCost,
    PurposeCost,
    SatisfactionStats,
    TicketStats,
)

# llm_calls.purpose -> the dashboard's cost groups.
PURPOSE_GROUPS = {
    "classify": "classify",
    "chat": "answer",
    "agent": "agent",
    "draft": "draft",
    "embed_document": "embedding",
    "embed_query": "embedding",
}
COST_GROUPS = ("classify", "answer", "agent", "draft", "embedding")
GAP_SAMPLE = 500
GAP_LIMIT = 10
GAP_SIMILARITY = 0.6


def range_start(days: int, today: dt.date | None = None) -> dt.datetime:
    """Midnight UTC `days - 1` days ago: the range is today plus the days before it."""
    today = today or dt.datetime.now(dt.UTC).date()
    start = today - dt.timedelta(days=days - 1)
    return dt.datetime.combine(start, dt.time.min, tzinfo=dt.UTC)


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _day(column: str) -> str:
    return f"CAST(({column} AT TIME ZONE 'UTC') AS date)"


_CONVERSATIONS_SQL = text(f"""
WITH ticketed AS (
    SELECT DISTINCT conversation_id FROM tickets
    WHERE workspace_id = :wid AND conversation_id IS NOT NULL
),
conv AS (
    SELECT
        {_day("c.created_at")} AS day,
        (c.ticket_id IS NOT NULL OR tc.conversation_id IS NOT NULL) AS has_ticket,
        last_reply.id IS NOT NULL AS answered,
        last_reply.route AS last_route,
        COALESCE(f.rating = 'down', false) AS thumbs_down
    FROM conversations c
    LEFT JOIN ticketed tc ON tc.conversation_id = c.id
    LEFT JOIN LATERAL (
        SELECT m.id, m.route FROM messages m
        WHERE m.workspace_id = c.workspace_id
          AND m.conversation_id = c.id
          AND m.role = 'assistant'
        ORDER BY m.created_at DESC, m.id DESC
        LIMIT 1
    ) last_reply ON true
    LEFT JOIN feedback f ON f.workspace_id = c.workspace_id AND f.message_id = last_reply.id
    WHERE c.workspace_id = :wid
      AND c.created_at >= :since
      AND c.last_message_at IS NOT NULL
)
SELECT
    day,
    count(*) AS total,
    count(*) FILTER (WHERE has_ticket) AS handed_off,
    count(*) FILTER (
        WHERE NOT has_ticket AND answered AND last_route <> 'fallback' AND NOT thumbs_down
    ) AS contained,
    count(*) FILTER (WHERE last_route = 'fallback') AS fallback_ended,
    count(*) FILTER (
        WHERE NOT has_ticket AND thumbs_down AND last_route IS DISTINCT FROM 'fallback'
    ) AS thumbs_down_ended
FROM conv
GROUP BY day
""")

# One pass over the range's tickets with grouping sets: by intent, by priority, by day, and
# overall (with response and resolution time percentiles).
_TICKETS_SQL = text(f"""
WITH t AS (
    SELECT
        t.intent,
        t.priority,
        {_day("t.created_at")} AS day,
        EXTRACT(EPOCH FROM first_reply.at - t.created_at) AS response_s,
        EXTRACT(EPOCH FROM resolved.at - t.created_at) AS resolution_s
    FROM tickets t
    LEFT JOIN LATERAL (
        SELECT min(d.sent_at) AS at FROM reply_drafts d
        WHERE d.workspace_id = t.workspace_id AND d.ticket_id = t.id AND d.sent_at IS NOT NULL
    ) first_reply ON true
    LEFT JOIN LATERAL (
        SELECT min(a.created_at) AS at FROM audit_events a
        WHERE a.workspace_id = t.workspace_id
          AND a.ticket_id = t.id
          AND a.action = 'ticket.status_changed'
          AND a.after ->> 'status' = 'resolved'
    ) resolved ON true
    WHERE t.workspace_id = :wid AND t.created_at >= :since
)
SELECT
    intent,
    priority,
    day,
    GROUPING(intent, priority, day) AS grp,
    count(*) AS n,
    count(response_s) AS response_n,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY response_s) AS response_p50,
    percentile_cont(0.9) WITHIN GROUP (ORDER BY response_s) AS response_p90,
    count(resolution_s) AS resolution_n,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_s) AS resolution_p50,
    percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_s) AS resolution_p90
FROM t
GROUP BY GROUPING SETS ((intent), (priority), (day), ())
""")
# GROUPING(intent, priority, day) bitmask: a set bit means "not grouped by this column".
_BY_INTENT, _BY_PRIORITY, _BY_DAY, _OVERALL = 0b011, 0b101, 0b110, 0b111

# Whitespace runs (spaces, newlines, tabs) become one space, then the ends are trimmed.
_NORMALISED = r"btrim(regexp_replace({col}, '\s+', ' ', 'g'))"
_DRAFTS_SQL = text(f"""
SELECT
    count(*) FILTER (
        WHERE status = 'sent'
          AND {_NORMALISED.format(col="content")} = {_NORMALISED.format(col="original_content")}
    ) AS sent_as_is,
    count(*) FILTER (
        WHERE status = 'sent'
          AND {_NORMALISED.format(col="content")} <> {_NORMALISED.format(col="original_content")}
    ) AS sent_edited,
    count(*) FILTER (WHERE status = 'rejected') AS rejected
FROM reply_drafts
WHERE workspace_id = :wid AND created_at >= :since AND author_type = 'ai'
""")

_ACTIONS_SQL = text("""
SELECT
    tool_name,
    count(*) FILTER (WHERE status = 'proposed') AS proposed,
    count(*) FILTER (
        WHERE status IN ('approved', 'executing', 'succeeded', 'failed')
    ) AS approved,
    count(*) FILTER (WHERE status = 'rejected') AS rejected,
    count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
    count(*) FILTER (WHERE status = 'failed') AS failed
FROM action_requests
WHERE workspace_id = :wid AND created_at >= :since
GROUP BY tool_name
ORDER BY count(*) DESC, tool_name
""")

_SATISFACTION_SQL = text("""
SELECT
    (SELECT count(*) FROM feedback
     WHERE workspace_id = :wid AND created_at >= :since AND rating = 'up') AS answer_up,
    (SELECT count(*) FROM feedback
     WHERE workspace_id = :wid AND created_at >= :since AND rating = 'down') AS answer_down,
    (SELECT count(*) FROM tickets
     WHERE workspace_id = :wid AND resolution_rated_at >= :since
       AND resolution_rating = 'up') AS resolution_up,
    (SELECT count(*) FROM tickets
     WHERE workspace_id = :wid AND resolution_rated_at >= :since
       AND resolution_rating = 'down') AS resolution_down
""")

_LLM_SQL = text(f"""
SELECT
    {_day("created_at")} AS day,
    purpose,
    model,
    count(*) AS calls,
    count(*) FILTER (WHERE status = 'error') AS errors,
    COALESCE(sum(input_tokens), 0) AS input_tokens,
    COALESCE(sum(output_tokens), 0) AS output_tokens,
    COALESCE(sum(cost_usd), 0) AS cost_usd,
    sum(latency_ms) AS latency_ms
FROM llm_calls
WHERE workspace_id = :wid AND created_at >= :since
GROUP BY 1, 2, 3
""")

# The customer message each fallback answered: the latest one at or before the reply.
_GAPS_SQL = text("""
SELECT question.content, m.created_at
FROM messages m
JOIN LATERAL (
    SELECT c.content FROM messages c
    WHERE c.workspace_id = m.workspace_id
      AND c.conversation_id = m.conversation_id
      AND c.role = 'customer'
      AND c.created_at <= m.created_at
    ORDER BY c.created_at DESC, c.id DESC
    LIMIT 1
) question ON true
WHERE m.workspace_id = :wid
  AND m.route = 'fallback'
  AND m.created_at >= :since
  AND m.role = 'assistant'
  AND (m.fallback_reason IS NULL OR m.fallback_reason <> 'budget')
ORDER BY m.created_at DESC
LIMIT :sample
""")


def _days(since: dt.datetime, days: int) -> list[dt.date]:
    return [since.date() + dt.timedelta(days=i) for i in range(days)]


async def overview(db: AsyncSession, workspace_id: uuid.UUID, days: int) -> AnalyticsOverview:
    since = range_start(days)
    params = {"wid": workspace_id, "since": since}

    conv_rows = (await db.execute(_CONVERSATIONS_SQL, params)).mappings().all()
    ticket_rows = (await db.execute(_TICKETS_SQL, params)).mappings().all()
    drafts = (await db.execute(_DRAFTS_SQL, params)).mappings().one()
    action_rows = (await db.execute(_ACTIONS_SQL, params)).mappings().all()
    satisfaction = (await db.execute(_SATISFACTION_SQL, params)).mappings().one()
    llm_rows = (await db.execute(_LLM_SQL, params)).mappings().all()

    conversations = _conversation_stats(conv_rows)
    tickets, tickets_by_day = _ticket_stats(ticket_rows)
    llm, cost_by_day = _llm_stats(llm_rows, since, days, conversations.total)

    by_day = {r["day"]: r for r in conv_rows}
    series = [
        DayPoint(
            day=day,
            conversations=int(by_day[day]["total"]) if day in by_day else 0,
            contained=int(by_day[day]["contained"]) if day in by_day else 0,
            handed_off=int(by_day[day]["handed_off"]) if day in by_day else 0,
            tickets=tickets_by_day.get(day, 0),
            cost_usd=round(cost_by_day.get(day, 0.0), 6),
        )
        for day in _days(since, days)
    ]

    sent = int(drafts["sent_as_is"]) + int(drafts["sent_edited"])
    return AnalyticsOverview(
        days=days,
        since=since,
        series=series,
        conversations=conversations,
        tickets=tickets,
        drafts=DraftStats(
            sent_as_is=int(drafts["sent_as_is"]),
            sent_edited=int(drafts["sent_edited"]),
            rejected=int(drafts["rejected"]),
            edit_rate=_rate(int(drafts["sent_edited"]), sent),
            acceptance_rate=_rate(sent, sent + int(drafts["rejected"])),
        ),
        actions=[ActionTypeStats.model_validate(dict(r)) for r in action_rows],
        satisfaction=SatisfactionStats(**{k: int(v) for k, v in satisfaction.items()}),
        llm=llm,
    )


def _conversation_stats(rows: Any) -> ConversationStats:
    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        for key in ("total", "handed_off", "contained", "fallback_ended", "thumbs_down_ended"):
            totals[key] += int(row[key])
    total = totals["total"]
    return ConversationStats(
        total=total,
        contained=totals["contained"],
        contained_rate=_rate(totals["contained"], total),
        handed_off=totals["handed_off"],
        handoff_rate=_rate(totals["handed_off"], total),
        fallback_ended=totals["fallback_ended"],
        thumbs_down_ended=totals["thumbs_down_ended"],
    )


def _duration(n: Any, p50: Any, p90: Any) -> DurationStats:
    return DurationStats(
        count=int(n or 0),
        median_s=round(float(p50), 1) if p50 is not None else None,
        p90_s=round(float(p90), 1) if p90 is not None else None,
    )


def _ticket_stats(rows: Any) -> tuple[TicketStats, dict[dt.date, int]]:
    by_intent: list[CountItem] = []
    by_priority: list[CountItem] = []
    by_day: dict[dt.date, int] = {}
    overall: Any = None
    for row in rows:
        grouping = row["grp"]
        if grouping == _BY_INTENT:
            by_intent.append(CountItem(key=row["intent"], count=row["n"]))
        elif grouping == _BY_PRIORITY:
            by_priority.append(CountItem(key=row["priority"], count=row["n"]))
        elif grouping == _BY_DAY:
            by_day[row["day"]] = int(row["n"])
        elif grouping == _OVERALL:
            overall = row
    by_intent.sort(key=lambda i: (-i.count, i.key))
    by_priority.sort(key=lambda i: (-i.count, i.key))
    if overall is None:
        stats = TicketStats(
            total=0,
            by_intent=[],
            by_priority=[],
            first_response=DurationStats(count=0, median_s=None, p90_s=None),
            resolution=DurationStats(count=0, median_s=None, p90_s=None),
        )
        return stats, by_day
    stats = TicketStats(
        total=int(overall["n"]),
        by_intent=by_intent,
        by_priority=by_priority,
        first_response=_duration(
            overall["response_n"], overall["response_p50"], overall["response_p90"]
        ),
        resolution=_duration(
            overall["resolution_n"], overall["resolution_p50"], overall["resolution_p90"]
        ),
    )
    return stats, by_day


def _llm_stats(
    rows: Any, since: dt.datetime, days: int, conversations: int
) -> tuple[LLMStats, dict[dt.date, float]]:
    purposes: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "cost": 0.0})
    models: dict[str, dict[str, float]] = defaultdict(
        lambda: {"calls": 0, "errors": 0, "in": 0, "out": 0, "cost": 0.0, "latency": 0.0}
    )
    daily: dict[dt.date, dict[str, float]] = defaultdict(lambda: dict.fromkeys(COST_GROUPS, 0.0))
    for row in rows:
        cost = float(row["cost_usd"])
        group = PURPOSE_GROUPS.get(row["purpose"], row["purpose"])
        purposes[group]["calls"] += int(row["calls"])
        purposes[group]["cost"] += cost
        m = models[row["model"]]
        m["calls"] += int(row["calls"])
        m["errors"] += int(row["errors"])
        m["in"] += int(row["input_tokens"])
        m["out"] += int(row["output_tokens"])
        m["cost"] += cost
        m["latency"] += float(row["latency_ms"] or 0)
        if group in COST_GROUPS:
            daily[row["day"]][group] += cost

    total_cost = sum(p["cost"] for p in purposes.values())
    cost_by_day = {day: sum(values.values()) for day, values in daily.items()}
    stats = LLMStats(
        calls=int(sum(p["calls"] for p in purposes.values())),
        errors=int(sum(m["errors"] for m in models.values())),
        total_cost_usd=round(total_cost, 6),
        cost_per_conversation=round(total_cost / conversations, 6) if conversations else None,
        by_purpose=sorted(
            (
                PurposeCost(purpose=name, calls=int(p["calls"]), cost_usd=round(p["cost"], 6))
                for name, p in purposes.items()
            ),
            key=lambda p: (-p.cost_usd, p.purpose),
        ),
        by_model=sorted(
            (
                ModelCost(
                    model=name,
                    calls=int(m["calls"]),
                    errors=int(m["errors"]),
                    input_tokens=int(m["in"]),
                    output_tokens=int(m["out"]),
                    cost_usd=round(m["cost"], 6),
                    avg_latency_ms=round(m["latency"] / m["calls"], 1) if m["calls"] else None,
                )
                for name, m in models.items()
            ),
            key=lambda m: (-m.cost_usd, m.model),
        ),
        daily=[
            CostDay(day=day, **{g: round(daily[day][g], 6) for g in COST_GROUPS})
            if day in daily
            else CostDay(day=day, **dict.fromkeys(COST_GROUPS, 0.0))
            for day in _days(since, days)
        ],
    )
    return stats, cost_by_day


# Knowledge gaps --------------------------------------------------------------------------

_MASKS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"(?i)\b(?:https?://|www\.)\S+"), "[link]"),
    (re.compile(r"\+?\d[\d\s().-]{7,}\d"), "[phone]"),
    (re.compile(r"#?\b[A-Za-z]*\d[\w-]{3,}\b"), "[number]"),
)
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do", "does", "for",
        "from", "have", "hi", "hello", "hey", "how", "i", "if", "in", "is", "it", "me", "my",
        "of", "on", "or", "our", "please", "so", "thank", "thanks", "that", "the", "there",
        "this", "to", "was", "we", "what", "when", "where", "which", "who", "why", "will",
        "with", "you", "your", "yours",
    }
)
_WORD = re.compile(r"[a-z0-9']+")


def mask_question(question: str, limit: int = 200) -> str:
    masked = question.strip()
    for pattern, replacement in _MASKS:
        masked = pattern.sub(replacement, masked)
    masked = re.sub(r"\s+", " ", masked)
    return masked if len(masked) <= limit else masked[: limit - 1].rstrip() + "…"


def _tokens(masked: str) -> frozenset[str]:
    words = _WORD.findall(masked.lower())
    meaningful = [w for w in words if w not in _STOPWORDS and len(w) > 1]
    return frozenset(meaningful or words)


def _similar(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return a == b
    return len(a & b) / len(a | b) >= GAP_SIMILARITY


def group_questions(rows: list[tuple[str, dt.datetime]]) -> list[KnowledgeGap]:
    """Greedy grouping by word-set similarity, newest first. Each group is shown by its most
    common (masked) wording."""
    groups: list[dict[str, Any]] = []
    for content, seen_at in rows:
        masked = mask_question(content)
        tokens = _tokens(masked)
        for group in groups:
            if _similar(tokens, group["tokens"]):
                break
        else:
            group = {"tokens": tokens, "count": 0, "last_seen": seen_at, "wordings": {}}
            groups.append(group)
        group["count"] += 1
        group["last_seen"] = max(group["last_seen"], seen_at)
        key = masked.lower()
        wording = group["wordings"].setdefault(key, [masked, 0])
        wording[1] += 1

    gaps = [
        KnowledgeGap(
            question=max(g["wordings"].values(), key=lambda w: w[1])[0],
            count=g["count"],
            last_seen=g["last_seen"],
        )
        for g in groups
    ]
    gaps.sort(key=lambda g: (-g.count, -g.last_seen.timestamp()))
    return gaps[:GAP_LIMIT]


async def knowledge_gaps(
    db: AsyncSession, workspace_id: uuid.UUID, days: int
) -> KnowledgeGapsOut:
    since = range_start(days)
    rows = (
        await db.execute(_GAPS_SQL, {"wid": workspace_id, "since": since, "sample": GAP_SAMPLE})
    ).all()
    return KnowledgeGapsOut(
        days=days,
        total_fallbacks=len(rows),
        gaps=group_questions([(r[0], r[1]) for r in rows]),
    )
