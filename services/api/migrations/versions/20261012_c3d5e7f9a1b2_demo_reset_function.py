"""reset_workspace_demo_data(): dev/demo reset of one workspace's conversation data

Revision ID: c3d5e7f9a1b2
Revises: b7e2f4a91c03
Create Date: 2026-10-12 12:00:00.000000

The app role can't delete audit_events (append-only), so the reset runs as this function's
owner (the migrations role) via SECURITY DEFINER. The function itself refuses any workspace
other than the caller's tenant context (app.workspace_id), so the app role can only ever
reset the workspace its request is scoped to. Only reachable from the API when
DEMO_TOOLS_ENABLED is on, and only by owners.
"""
from collections.abc import Sequence

from alembic import op

APP_ROLE = "resolveai_app"

# revision identifiers, used by Alembic.
revision: str = 'c3d5e7f9a1b2'
down_revision: str | None = 'b7e2f4a91c03'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIGNATURE = "reset_workspace_demo_data(uuid, jsonb)"


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reset_workspace_demo_data(
            p_workspace_id uuid,
            p_seed_statuses jsonb DEFAULT '{}'::jsonb
        )
        RETURNS TABLE (table_name text, row_count bigint)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            -- Children before parents. The remaining links (messages <-> reply_drafts,
            -- tickets <-> conversations) are ON DELETE SET NULL.
            v_tables text[] := ARRAY[
                'audit_events', 'feedback', 'tool_calls', 'action_requests', 'reply_drafts',
                'messages', 'tickets', 'conversations', 'contacts'
            ];
            v_table text;
            v_count bigint;
        BEGIN
            IF p_workspace_id IS NULL OR p_workspace_id IS DISTINCT FROM
                NULLIF(current_setting('app.workspace_id', true), '')::uuid
            THEN
                RAISE EXCEPTION 'reset_workspace_demo_data: workspace is not the current tenant'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;

            FOREACH v_table IN ARRAY v_tables LOOP
                EXECUTE format('DELETE FROM public.%I WHERE workspace_id = $1', v_table)
                    USING p_workspace_id;
                GET DIAGNOSTICS v_count = ROW_COUNT;
                table_name := v_table;
                row_count := v_count;
                RETURN NEXT;
            END LOOP;

            -- Orders keep their rows; refunds, cancellations and applied keys are undone.
            UPDATE public.mock_orders AS o
            SET refunded_amount = 0,
                refunded_at = NULL,
                applied_action_keys = '[]'::jsonb,
                status = COALESCE(p_seed_statuses ->> o.order_number, o.status),
                updated_at = now()
            WHERE o.workspace_id = p_workspace_id
              AND (o.refunded_amount <> 0
                   OR o.refunded_at IS NOT NULL
                   OR o.applied_action_keys <> '[]'::jsonb
                   OR o.status IS DISTINCT FROM COALESCE(p_seed_statuses ->> o.order_number, o.status));
            GET DIAGNOSTICS v_count = ROW_COUNT;
            table_name := 'mock_orders';
            row_count := v_count;
            RETURN NEXT;
        END;
        $$
        """
    )
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {APP_ROLE}")
    # audit_events has no DELETE policy (append-only). The function runs as its owner, so
    # let only that role delete, scoped to the tenant context like every other policy.
    # The app role still has no DELETE privilege on the table at all.
    op.execute(
        """
        CREATE POLICY audit_events_owner_delete ON audit_events
            FOR DELETE TO CURRENT_USER
            USING (workspace_id = NULLIF(current_setting('app.workspace_id', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS audit_events_owner_delete ON audit_events")
    op.execute(f"DROP FUNCTION IF EXISTS {SIGNATURE}")
