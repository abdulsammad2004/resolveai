"""human review loop: draft review fields, action decisions, audit_events

Revision ID: b7e2f4a91c03
Revises: 9a1d3c7e5b20
Create Date: 2026-10-12 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Unset settings become NULL instead of raising, so a missing context matches no rows.
CURRENT_WORKSPACE = "NULLIF(current_setting('app.workspace_id', true), '')::uuid"
APP_ROLE = "resolveai_app"

# revision identifiers, used by Alembic.
revision: str = 'b7e2f4a91c03'
down_revision: str | None = '9a1d3c7e5b20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # reply_drafts: the original AI text, who reviewed it, and the message it became.
    op.add_column('reply_drafts', sa.Column('original_content', sa.Text(), server_default='', nullable=False))
    op.execute("UPDATE reply_drafts SET original_content = content")
    op.add_column('reply_drafts', sa.Column('author_type', sa.String(length=8), server_default='ai', nullable=False))
    op.create_check_constraint(op.f('ck_reply_drafts_author_type'), 'reply_drafts', "author_type IN ('ai', 'human')")
    op.add_column('reply_drafts', sa.Column('reviewed_by', sa.UUID(), nullable=True))
    op.add_column('reply_drafts', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('reply_drafts', sa.Column('rejection_reason', sa.String(length=500), nullable=True))
    op.add_column('reply_drafts', sa.Column('sent_message_id', sa.UUID(), nullable=True))
    op.add_column('reply_drafts', sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(op.f('fk_reply_drafts_reviewed_by_users'), 'reply_drafts', 'users', ['reviewed_by'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_reply_drafts_sent_message_id_messages'), 'reply_drafts', 'messages', ['sent_message_id'], ['id'], ondelete='SET NULL')

    # messages: which draft (if any) a team reply came from, and who sent it.
    op.add_column('messages', sa.Column('draft_id', sa.UUID(), nullable=True))
    op.add_column('messages', sa.Column('author_id', sa.UUID(), nullable=True))
    op.create_foreign_key(op.f('fk_messages_draft_id_reply_drafts'), 'messages', 'reply_drafts', ['draft_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_messages_author_id_users'), 'messages', 'users', ['author_id'], ['id'], ondelete='SET NULL')

    # action_requests: one decision (approve or reject) and the execution timestamps.
    op.alter_column('action_requests', 'approved_by', new_column_name='decided_by')
    op.execute(
        "ALTER TABLE action_requests RENAME CONSTRAINT fk_action_requests_approved_by_users "
        "TO fk_action_requests_decided_by_users"
    )
    op.add_column('action_requests', sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('action_requests', sa.Column('decision_reason', sa.String(length=500), nullable=True))
    op.add_column('action_requests', sa.Column('execution_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('action_requests', sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True))

    # mock_orders: refunds, and the idempotency keys already applied (stands in for the
    # provider-side idempotency a real connector gets from Stripe or Shopify).
    op.add_column('mock_orders', sa.Column('refunded_amount', sa.Numeric(precision=10, scale=2), server_default='0', nullable=False))
    op.add_column('mock_orders', sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('mock_orders', sa.Column('applied_action_keys', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))

    op.create_table('audit_events',
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('ticket_id', sa.UUID(), nullable=True),
    sa.Column('actor_type', sa.String(length=8), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=False),
    sa.Column('target_id', sa.UUID(), nullable=True),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("actor_type IN ('user', 'ai', 'system')", name=op.f('ck_audit_events_actor_type')),
    # No foreign keys to tickets or users: the record outlives what it describes.
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_audit_events_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index('ix_audit_events_workspace_id_ticket_id', 'audit_events', ['workspace_id', 'ticket_id', 'created_at'], unique=False)
    op.create_index('ix_audit_events_workspace_id_created_at', 'audit_events', ['workspace_id', 'created_at'], unique=False)

    # Append-only: the app role may read and insert, never change or delete.
    op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM {APP_ROLE}")
    op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY audit_events_select ON audit_events
            FOR SELECT USING (workspace_id = {CURRENT_WORKSPACE})
        """
    )
    op.execute(
        f"""
        CREATE POLICY audit_events_insert ON audit_events
            FOR INSERT WITH CHECK (workspace_id = {CURRENT_WORKSPACE})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS audit_events_insert ON audit_events")
    op.execute("DROP POLICY IF EXISTS audit_events_select ON audit_events")
    op.drop_index('ix_audit_events_workspace_id_created_at', table_name='audit_events')
    op.drop_index('ix_audit_events_workspace_id_ticket_id', table_name='audit_events')
    op.drop_table('audit_events')

    op.drop_column('mock_orders', 'applied_action_keys')
    op.drop_column('mock_orders', 'refunded_at')
    op.drop_column('mock_orders', 'refunded_amount')

    op.drop_column('action_requests', 'executed_at')
    op.drop_column('action_requests', 'execution_started_at')
    op.drop_column('action_requests', 'decision_reason')
    op.drop_column('action_requests', 'decided_at')
    op.execute(
        "ALTER TABLE action_requests RENAME CONSTRAINT fk_action_requests_decided_by_users "
        "TO fk_action_requests_approved_by_users"
    )
    op.alter_column('action_requests', 'decided_by', new_column_name='approved_by')

    op.drop_constraint(op.f('fk_messages_author_id_users'), 'messages', type_='foreignkey')
    op.drop_constraint(op.f('fk_messages_draft_id_reply_drafts'), 'messages', type_='foreignkey')
    op.drop_column('messages', 'author_id')
    op.drop_column('messages', 'draft_id')

    op.drop_constraint(op.f('fk_reply_drafts_sent_message_id_messages'), 'reply_drafts', type_='foreignkey')
    op.drop_constraint(op.f('fk_reply_drafts_reviewed_by_users'), 'reply_drafts', type_='foreignkey')
    op.drop_column('reply_drafts', 'sent_at')
    op.drop_column('reply_drafts', 'sent_message_id')
    op.drop_column('reply_drafts', 'rejection_reason')
    op.drop_column('reply_drafts', 'reviewed_at')
    op.drop_column('reply_drafts', 'reviewed_by')
    op.drop_constraint(op.f('ck_reply_drafts_author_type'), 'reply_drafts', type_='check')
    op.drop_column('reply_drafts', 'author_type')
    op.drop_column('reply_drafts', 'original_content')
