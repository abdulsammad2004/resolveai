"""Dev/demo reset of one workspace's conversation data, shared by the Settings button
(POST /workspace/demo/reset) and scripts/reset_conversations.py.

The work happens in the reset_workspace_demo_data() Postgres function (see its migration):
it owns the list of tables and their delete order, refuses any workspace other than the
transaction's tenant context, and can delete append-only audit events because it runs as
the table owner. Callers must have set app.workspace_id for this transaction first.
"""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.modules.orders.service import seeded_statuses

ORDERS_KEY = "mock_orders"

_RESET = text(
    "SELECT table_name, row_count FROM reset_workspace_demo_data(:wid, CAST(:seed AS jsonb))"
)


async def reset_demo_data(
    db: AsyncSession | AsyncConnection, workspace_id: uuid.UUID
) -> dict[str, int]:
    """Rows deleted per table, in delete order, then `mock_orders`: orders reset."""
    rows = await db.execute(_RESET, {"wid": workspace_id, "seed": json.dumps(seeded_statuses())})
    return {name: int(count) for name, count in rows.all()}
