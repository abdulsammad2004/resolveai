r"""Run the agent once against the real chat model (LLM_CHAT_MODEL) with the real tool registry.

Reproduces tool-calling problems without the widget or the worker. Run from services/api:

    .\.venv\Scripts\python scripts\smoke_agent.py
    .\.venv\Scripts\python scripts\smoke_agent.py --question "Where is my order RA-10421? My email is maya.robinson@example.com"
    .\.venv\Scripts\python scripts\smoke_agent.py --tools draft

First it makes one raw tool-calling request (no retries) and prints the provider's error body
if it fails, then it runs the full agent loop exactly as the widget does (agent_v1, widget
tools) or as the drafting job does (draft_v1, all tools; write tools only become proposals).

Prints only the model name, error bodies and results: never the API key, headers or env values.
Side effects: one short synthetic conversation is sent to OpenAI, and llm_calls / tool_calls
rows are written to the chosen workspace (the same metering as a real chat). In widget mode an
empty widget conversation is created for the run; the script never opens tickets itself (the
widget does that after a handoff), it only reports the handoff. With --tools
draft, a proposal can only be stored with --ticket; without one, write tools are refused.
"""

import argparse
import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openai import APIStatusError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.ai.agent import build_widget_messages, run_agent
from app.ai.embeddings import get_embedding_client
from app.ai.llm import LLMError, OpenAILLMClient
from app.ai.prompts import load_prompt
from app.ai.tools.builtin import DRAFT_TOOLS, WIDGET_TOOLS
from app.ai.tools.registry import ToolContext
from app.ai.usage import LLMPurpose, MeteredLLMClient
from app.core.config import get_settings
from app.core.deps import tenant_session

# Register every model on the shared metadata so foreign keys resolve when metering writes
# llm_calls and tool_calls rows (as in app.workers.main).
from app.modules.approvals import models as approvals_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.modules.conversations import models as conversations_models  # noqa: F401
from app.modules.conversations.chat import AGENT_PROMPT_NAME, AGENT_PROMPT_VERSION
from app.modules.conversations.service import start_session
from app.modules.tickets import models as tickets_models  # noqa: F401
from app.modules.workspaces import models as workspaces_models  # noqa: F401
from app.workers import drafting

DEFAULT_QUESTION = "Where is my order RA-104? My email is maya.robinson@example.com"


async def find_workspace() -> uuid.UUID | None:
    """The first workspace with sample orders (owner role: a read across tenants, dev only)."""
    engine = create_async_engine(get_settings().migrations_database_url)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT workspace_id FROM mock_orders ORDER BY created_at LIMIT 1")
                )
            ).scalar_one_or_none()
    finally:
        await engine.dispose()


def show_error(exc: BaseException) -> None:
    cause = exc.__cause__ or exc
    print(f"  {type(cause).__name__}")
    if isinstance(cause, APIStatusError):
        print(f"  status: {cause.status_code}")
        print(f"  body:   {json.dumps(cause.body, indent=2)}")
    else:
        print(f"  {cause}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--tools", choices=("widget", "draft"), default="widget")
    parser.add_argument("--workspace", type=uuid.UUID)
    parser.add_argument("--ticket", type=uuid.UUID, help="ticket id for --tools draft proposals")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # answers contain curly quotes and …

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings()
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not key or not settings.llm_chat_model:
        print("Set OPENAI_API_KEY and LLM_CHAT_MODEL in services/api/.env first.")
        return 1
    workspace_id = args.workspace or await find_workspace()
    if workspace_id is None:
        print("No workspace has sample orders. Load them in Settings -> Demo data first.")
        return 1

    llm = OpenAILLMClient(
        api_key=key,
        model=settings.llm_chat_model,
        tools_reasoning_effort=settings.llm_tools_reasoning_effort,
    )
    tools = WIDGET_TOOLS if args.tools == "widget" else DRAFT_TOOLS
    # The same prompt versions the widget and the drafting job use.
    prompt = (
        load_prompt(AGENT_PROMPT_NAME, AGENT_PROMPT_VERSION)
        if args.tools == "widget"
        else load_prompt(drafting.PROMPT_NAME, drafting.PROMPT_VERSION)
    )
    messages = build_widget_messages(prompt.text, [], args.question)
    specs = [t.spec() for t in tools]
    print(f"Model: {settings.llm_chat_model}")
    print(f"Tools: {', '.join(t.name for t in tools)}")
    print(f"Prompt: {prompt.id}")
    print(f"Workspace: {workspace_id}\n")

    # 1. One raw request, no retries, so the provider's error body is visible as-is.
    print("Raw tool-calling request:")
    try:
        first = await llm.complete_with_tools(messages, specs)
    except LLMError as exc:
        print("  FAILED")
        show_error(exc)
        return 1
    print(f"  OK: {len(first.tool_calls)} tool call(s), {len(first.text)} chars of text\n")

    # 2. The full agent loop, as the widget (or the drafting job) runs it.
    print("Agent run:")
    conversation_id = None
    if args.tools == "widget":
        # The widget always runs inside a conversation (hand_off_to_team needs one). An empty
        # one, as a widget session creates: it stays out of the inbox (no messages).
        async with tenant_session(workspace_id) as db:
            conversation, _ = await start_session(db, workspace_id, None, None)
            conversation_id = conversation.id
        print(f"  conversation: {conversation_id}")
    ctx = ToolContext(
        workspace_id=workspace_id,
        embedder=get_embedding_client(),
        conversation_id=conversation_id,
        ticket_id=args.ticket,
    )
    metered = MeteredLLMClient(
        llm, workspace_id=workspace_id, purpose=LLMPurpose.AGENT, prompt_version=prompt.id
    )
    result = await run_agent(
        llm=metered,
        messages=messages,
        tools=tools,
        ctx=ctx,
        on_tool=lambda tool: print(f"  status: {tool.status_text}"),
    )
    print(f"  outcome: {result.outcome.value}")
    for use in result.tool_uses:
        print(f"  tool: {use.name} -> {use.status.value}")
    print(f"  tokens: {result.tokens}")
    print(f"  answer: {result.text!r}")
    if ctx.handoff_reason is not None:
        print(f"  handed off to the team (reason: {ctx.handoff_reason!r})")
    return 0 if result.answered or ctx.handoff_reason is not None else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
