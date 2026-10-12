"""tool calls, reply drafts and action requests

Revision ID: 9a1d3c7e5b20
Revises: c4071fd14902
Create Date: 2026-10-09 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Unset settings become NULL instead of raising, so a missing context matches no rows.
CURRENT_WORKSPACE = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
TENANT_TABLES = ("tool_calls", "reply_drafts", "action_requests")

# revision identifiers, used by Alembic.
revision: str = '9a1d3c7e5b20'
down_revision: str | None = 'c4071fd14902'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    ]


def upgrade() -> None:
    op.create_table('tool_calls',
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('conversation_id', sa.UUID(), nullable=True),
    sa.Column('ticket_id', sa.UUID(), nullable=True),
    sa.Column('tool_name', sa.String(length=64), nullable=False),
    sa.Column('arguments', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('result_summary', sa.String(length=300), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    *_timestamps(),
    sa.CheckConstraint("status IN ('ok', 'not_found', 'invalid', 'proposed', 'denied', 'error')", name=op.f('ck_tool_calls_status')),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_tool_calls_conversation_id_conversations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], name=op.f('fk_tool_calls_ticket_id_tickets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_tool_calls_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_calls'))
    )
    op.create_index('ix_tool_calls_workspace_id_ticket_id', 'tool_calls', ['workspace_id', 'ticket_id', 'created_at'], unique=False)
    op.create_index('ix_tool_calls_workspace_id_conversation_id', 'tool_calls', ['workspace_id', 'conversation_id', 'created_at'], unique=False)

    op.create_table('reply_drafts',
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('ticket_id', sa.UUID(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('citations', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('prompt_version', sa.String(length=64), nullable=True),
    sa.Column('llm_call_id', sa.UUID(), nullable=True),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.Column('input_hash', sa.String(length=64), nullable=True),
    *_timestamps(),
    sa.CheckConstraint("status IN ('pending', 'approved', 'edited', 'rejected', 'sent', 'superseded', 'failed')", name=op.f('ck_reply_drafts_status')),
    sa.ForeignKeyConstraint(['llm_call_id'], ['llm_calls.id'], name=op.f('fk_reply_drafts_llm_call_id_llm_calls'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], name=op.f('fk_reply_drafts_ticket_id_tickets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_reply_drafts_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reply_drafts'))
    )
    op.create_index('ix_reply_drafts_workspace_id_ticket_id', 'reply_drafts', ['workspace_id', 'ticket_id', 'created_at'], unique=False)

    op.create_table('action_requests',
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('ticket_id', sa.UUID(), nullable=False),
    sa.Column('conversation_id', sa.UUID(), nullable=True),
    sa.Column('tool_name', sa.String(length=64), nullable=False),
    sa.Column('arguments', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('risk', sa.String(length=16), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('approved_by', sa.UUID(), nullable=True),
    *_timestamps(),
    sa.CheckConstraint("risk IN ('write', 'sensitive')", name=op.f('ck_action_requests_risk')),
    sa.CheckConstraint("status IN ('proposed', 'approved', 'rejected', 'executing', 'succeeded', 'failed')", name=op.f('ck_action_requests_status')),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_action_requests_approved_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], name=op.f('fk_action_requests_conversation_id_conversations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], name=op.f('fk_action_requests_ticket_id_tickets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_action_requests_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_action_requests')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_action_requests_idempotency_key'))
    )
    op.create_index('ix_action_requests_workspace_id_status', 'action_requests', ['workspace_id', 'status', 'created_at'], unique=False)
    op.create_index('ix_action_requests_workspace_id_ticket_id', 'action_requests', ['workspace_id', 'ticket_id'], unique=False)

    op.add_column('messages', sa.Column('tools_used', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.drop_constraint(op.f('ck_messages_route'), 'messages', type_='check')
    op.create_check_constraint(
        op.f('ck_messages_route'),
        'messages',
        "route IN ('answer', 'fallback', 'small_talk', 'handoff', 'agent')",
    )

    # Row-level security: rows are visible and writable only in the current workspace.
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_isolation ON {table}
                FOR ALL
                USING (workspace_id = {CURRENT_WORKSPACE})
                WITH CHECK (workspace_id = {CURRENT_WORKSPACE})
            """
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_isolation ON {table}")

    op.execute("DELETE FROM messages WHERE route = 'agent'")
    op.drop_constraint(op.f('ck_messages_route'), 'messages', type_='check')
    op.create_check_constraint(
        op.f('ck_messages_route'),
        'messages',
        "route IN ('answer', 'fallback', 'small_talk', 'handoff')",
    )
    op.drop_column('messages', 'tools_used')

    op.drop_index('ix_action_requests_workspace_id_ticket_id', table_name='action_requests')
    op.drop_index('ix_action_requests_workspace_id_status', table_name='action_requests')
    op.drop_table('action_requests')
    op.drop_index('ix_reply_drafts_workspace_id_ticket_id', table_name='reply_drafts')
    op.drop_table('reply_drafts')
    op.drop_index('ix_tool_calls_workspace_id_conversation_id', table_name='tool_calls')
    op.drop_index('ix_tool_calls_workspace_id_ticket_id', table_name='tool_calls')
    op.drop_table('tool_calls')
