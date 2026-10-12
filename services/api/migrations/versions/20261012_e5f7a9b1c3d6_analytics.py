"""analytics: fallback reason on messages, indexes for date-range aggregations

Revision ID: e5f7a9b1c3d6
Revises: d4e6f8a0b2c4
Create Date: 2026-10-12 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f7a9b1c3d6'
down_revision: str | None = 'd4e6f8a0b2c4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Why a reply fell back, so budget fallbacks don't count as knowledge gaps. Older rows
    # stay NULL (treated as gaps).
    op.add_column('messages', sa.Column('fallback_reason', sa.String(length=16), nullable=True))
    op.create_check_constraint(
        op.f('ck_messages_fallback_reason'),
        'messages',
        "fallback_reason IN ('no_sources', 'not_grounded', 'budget')",
    )

    # Every analytics query filters by workspace and a created_at range.
    op.create_index(
        'ix_conversations_workspace_id_created_at',
        'conversations',
        ['workspace_id', 'created_at'],
    )
    op.create_index(
        'ix_messages_workspace_id_fallback_created_at',
        'messages',
        ['workspace_id', 'created_at'],
        postgresql_where=sa.text("route = 'fallback'"),
    )
    op.create_index(
        'ix_reply_drafts_workspace_id_created_at',
        'reply_drafts',
        ['workspace_id', 'created_at'],
    )
    op.create_index(
        'ix_action_requests_workspace_id_created_at',
        'action_requests',
        ['workspace_id', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_action_requests_workspace_id_created_at', table_name='action_requests')
    op.drop_index('ix_reply_drafts_workspace_id_created_at', table_name='reply_drafts')
    op.drop_index('ix_messages_workspace_id_fallback_created_at', table_name='messages')
    op.drop_index('ix_conversations_workspace_id_created_at', table_name='conversations')
    op.drop_constraint(op.f('ck_messages_fallback_reason'), 'messages', type_='check')
    op.drop_column('messages', 'fallback_reason')
