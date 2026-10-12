"""resolved conversations: closed_at, customer audit actor, resolution rating

Revision ID: d4e6f8a0b2c4
Revises: c3d5e7f9a1b2
Create Date: 2026-10-12 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e6f8a0b2c4'
down_revision: str | None = 'c3d5e7f9a1b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))

    # The customer's own steps in the widget ("Still need help?", the resolution rating).
    op.drop_constraint(op.f('ck_audit_events_actor_type'), 'audit_events', type_='check')
    op.create_check_constraint(
        op.f('ck_audit_events_actor_type'),
        'audit_events',
        "actor_type IN ('user', 'ai', 'system', 'customer')",
    )

    op.add_column('tickets', sa.Column('resolution_rating', sa.String(length=8), nullable=True))
    op.add_column('tickets', sa.Column('resolution_rated_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f('ck_tickets_resolution_rating'), 'tickets', "resolution_rating IN ('up', 'down')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f('ck_tickets_resolution_rating'), 'tickets', type_='check')
    op.drop_column('tickets', 'resolution_rated_at')
    op.drop_column('tickets', 'resolution_rating')

    op.drop_constraint(op.f('ck_audit_events_actor_type'), 'audit_events', type_='check')
    # Customer events can't be deleted by the app role; the migrations role owns the table.
    op.execute("DELETE FROM audit_events WHERE actor_type = 'customer'")
    op.create_check_constraint(
        op.f('ck_audit_events_actor_type'),
        'audit_events',
        "actor_type IN ('user', 'ai', 'system')",
    )

    op.drop_column('conversations', 'closed_at')
