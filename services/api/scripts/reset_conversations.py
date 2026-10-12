r"""Dev only: wipe one workspace's conversation data and reset its sample orders.

Deletes conversations, messages, tickets, reply drafts, action requests, tool calls, audit
events, message feedback and widget contacts. Keeps users, workspaces, memberships, widget
keys and settings, documents and chunks, llm_calls (cost history) and mock_orders rows;
the orders' refund/cancel state goes back to the seeded values.

Calls the same reset_workspace_demo_data() database function as the Settings button, so
the two can't drift; a dry run calls it and rolls back. Runs as the migrations role and only
against a database on localhost. Run from services/api:

    .\.venv\Scripts\python scripts\reset_conversations.py              # dry run: counts only
    .\.venv\Scripts\python scripts\reset_conversations.py --yes
    .\.venv\Scripts\python scripts\reset_conversations.py --workspace <id> --yes
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.modules.workspaces.demo import ORDERS_KEY, reset_demo_data

LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", type=uuid.UUID, help="workspace id (default: the only one)")
    parser.add_argument("--yes", action="store_true", help="delete (without it: dry run)")
    return parser.parse_args()


async def _pick_workspace(conn: AsyncConnection, wanted: uuid.UUID | None) -> tuple[uuid.UUID, str]:
    rows = (await conn.execute(text("SELECT id, name FROM workspaces ORDER BY created_at"))).all()
    if wanted is not None:
        match = [r for r in rows if r.id == wanted]
        if not match:
            raise SystemExit(f"No workspace with id {wanted}.")
        return match[0].id, match[0].name
    if len(rows) == 1:
        return rows[0].id, rows[0].name
    listing = "\n".join(f"  {r.id}  {r.name}" for r in rows) or "  (none)"
    raise SystemExit(f"Pass --workspace <id>. Workspaces:\n{listing}")


def _print_counts(title: str, counts: dict[str, int], orders: int) -> None:
    print(title)
    for table, n in counts.items():
        print(f"  {table:<16} {n:>7}")
    print(f"  {'mock_orders':<16} {orders:>7}  (state reset to the seeded values)")


async def main() -> int:
    args = _parse_args()
    url = make_url(get_settings().migrations_database_url)
    if url.host not in LOCAL_HOSTS:
        print(f"Refusing to run: database host is {url.host!r}, not localhost.")
        return 1

    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            wid, name = await _pick_workspace(conn, args.workspace)
            # The function only resets the transaction's tenant context.
            await conn.execute(
                text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": str(wid)}
            )
            print(f"Workspace: {name} ({wid}) on {url.host}/{url.database}\n")
            counts = await reset_demo_data(conn, wid)
            orders = counts.pop(ORDERS_KEY, 0)

            if not args.yes:
                await trans.rollback()
                _print_counts("Would delete (dry run, nothing changed):", counts, orders)
                print("\nRun again with --yes to delete.")
                return 0
            await trans.commit()
    finally:
        await engine.dispose()

    _print_counts("Deleted:", counts, orders)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
