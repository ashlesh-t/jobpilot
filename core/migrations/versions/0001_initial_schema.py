"""Initial JobPilot v2 schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-01

The baseline revision builds the whole schema straight from the ORM metadata rather
than a hand-transcribed copy of it — there is nothing to migrate *from*, so the two
can never disagree. Every subsequent revision uses explicit ops.
"""
from __future__ import annotations

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from core.models import Base

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from core.models import Base

    Base.metadata.drop_all(bind=op.get_bind())
