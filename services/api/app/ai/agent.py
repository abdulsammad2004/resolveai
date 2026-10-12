"""The agent loop: the model answers or calls allowlisted tools, in plain Python.

A run is bounded by MAX_TOOL_CALLS tool calls and RUN_TIMEOUT_S seconds. Asking for more
tool calls than allowed, timing out or a provider error ends the run without an answer, and
the caller hands over to a person. Write and sensitive tools only ever become proposals (see
app.ai.tools.registry).

Prompts put customer text, ticket fields and tool results in delimited data blocks. Message
text is never logged; only ids, counts and outcomes.
"""

import asyncio
import enum
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.ai.grounding import attr, extract_citations, neutralize, strip_citations
from app.ai.llm import ChatMessage, LLMError, assistant_tool_message
from app.ai.tools.models import ToolCallStatus
from app.ai.tools.registry import Tool, ToolContext, ToolResult, run_tool
from app.ai.usage import MeteredLLMClient
from app.modules.conversations.schemas import Citation

logger = logging.getLogger("app.ai.agent")

MAX_TOOL_CALLS = 4
RUN_TIMEOUT_S = 30.0
HISTORY_MESSAGES = 8
MESSAGE_CHARS = 2000


class AgentOutcome(enum.StrEnum):
    ANSWERED = "answered"
    TOOL_LIMIT = "tool_limit"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True)
class ToolUse:
    name: str
    status: ToolCallStatus


@dataclass
class AgentResult:
    outcome: AgentOutcome = AgentOutcome.ERROR
    text: str = ""
    citations: list[Citation] = field(default_factory=list)
    tool_uses: list[ToolUse] = field(default_factory=list)
    llm_call_id: uuid.UUID | None = None  # the last llm_calls row of the run
    tokens: int = 0

    @property
    def answered(self) -> bool:
        return self.outcome is AgentOutcome.ANSWERED and bool(self.text.strip())

    @property
    def tools_used(self) -> list[str]:
        return list(dict.fromkeys(u.name for u in self.tool_uses))


def tool_message(call_id: str, name: str, result: ToolResult) -> ChatMessage:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": (
            f'<tool_result name="{attr(name)}" status="{result.status.value}">\n'
            f"{result.content}\n</tool_result>"
        ),
    }


async def run_agent(
    *,
    llm: MeteredLLMClient,
    messages: list[ChatMessage],
    tools: Sequence[Tool],
    ctx: ToolContext,
    on_tool: Callable[[Tool], None] | None = None,
    max_tool_calls: int | None = None,
    timeout_s: float | None = None,
) -> AgentResult:
    """Run until the model answers in text, or a limit ends the run."""
    max_tool_calls = max_tool_calls or MAX_TOOL_CALLS
    timeout_s = timeout_s or RUN_TIMEOUT_S
    allowed = {t.name: t for t in tools}
    specs = [t.spec() for t in tools]
    conversation = list(messages)
    result = AgentResult()
    try:
        async with asyncio.timeout(timeout_s):
            while True:
                completion = await llm.complete_with_tools(conversation, specs)
                result.tokens += llm.last_input_tokens + llm.last_output_tokens
                result.llm_call_id = llm.last_call_id
                if not completion.tool_calls:
                    result.outcome = AgentOutcome.ANSWERED
                    result.text, result.citations = extract_citations(
                        completion.text, ctx.sources
                    )
                    break
                if len(result.tool_uses) + len(completion.tool_calls) > max_tool_calls:
                    result.outcome = AgentOutcome.TOOL_LIMIT
                    break
                conversation.append(assistant_tool_message(completion))
                for call in completion.tool_calls:
                    tool = allowed.get(call.name)
                    if tool is not None and on_tool is not None:
                        on_tool(tool)
                    tool_result = await run_tool(call, allowed, ctx)
                    result.tool_uses.append(ToolUse(call.name[:64], tool_result.status))
                    conversation.append(tool_message(call.id, call.name, tool_result))
    except TimeoutError:
        result.outcome = AgentOutcome.TIMEOUT
    except LLMError as exc:
        logger.warning(
            "Agent model call failed (workspace_id=%s, error=%s)",
            ctx.workspace_id,
            type(exc.__cause__ or exc).__name__,
        )
        result.outcome = AgentOutcome.ERROR

    logger.info(
        "Agent run (workspace_id=%s, conversation_id=%s, ticket_id=%s, outcome=%s, "
        "tool_calls=%d, cited=%d)",
        ctx.workspace_id,
        ctx.conversation_id,
        ctx.ticket_id,
        result.outcome.value,
        len(result.tool_uses),
        len(result.citations),
    )
    return result


# Prompt building ----------------------------------------------------------------------------


def _history_turns(history: Sequence[tuple[str, str]]) -> list[ChatMessage]:
    """Earlier widget turns as chat messages: customer -> user, everything else -> assistant."""
    turns: list[ChatMessage] = []
    for role, content in history[-HISTORY_MESSAGES:]:
        # Old answers cite old sources; drop their markers so ids can't be confused.
        text = strip_citations(content)[:MESSAGE_CHARS].strip()
        if text:
            turns.append(
                {
                    "role": "user" if role == "customer" else "assistant",
                    "content": neutralize(text),
                }
            )
    return turns


def build_widget_messages(
    system_prompt: str, history: Sequence[tuple[str, str]], question: str
) -> list[ChatMessage]:
    return [
        {"role": "system", "content": system_prompt},
        *_history_turns(history),
        {
            "role": "user",
            "content": f"<customer_message>\n{neutralize(question)}\n</customer_message>",
        },
    ]


@dataclass(frozen=True)
class DraftInput:
    subject: str
    description: str | None
    contact_email: str | None
    # The ticket's classified intent, e.g. "cancel_order" (from the classifier, not the model).
    intent: str
    # (role, content) of the conversation, oldest first: customer | assistant | agent
    messages: Sequence[tuple[str, str]]


def build_draft_messages(system_prompt: str, data: DraftInput) -> list[ChatMessage]:
    lines = [
        f'<message role="{attr(role)}">\n{neutralize(strip_citations(content)[:MESSAGE_CHARS])}'
        "\n</message>"
        for role, content in data.messages[-HISTORY_MESSAGES * 2 :]
    ]
    ticket = (
        f'<ticket subject="{attr(data.subject)}" intent="{attr(data.intent)}"'
        f' contact_email="{attr(data.contact_email or "unknown")}">\n'
        f"{neutralize((data.description or '')[:MESSAGE_CHARS])}\n</ticket>"
    )
    conversation = "<conversation>\n" + "\n".join(lines) + "\n</conversation>"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{ticket}\n\n{conversation}"},
    ]
