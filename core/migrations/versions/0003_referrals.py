"""Add contacts + referrals tables — draft-only referral-request messages.

Revision ID: 0003_referrals
Revises: 0002_bypass_permissions
Create Date: 2026-08-03

Additive schema, so (unlike 0002's data-only fixup) this is fully reversible. Since
0001 built the baseline straight from the ORM metadata, every revision after it is
hand-written explicit ops (see that file's own docstring) — column types here mirror
core/models.py's Contact/Referral classes exactly.

Guarded with `has_table()`/`has_index()` checks: because 0001's `create_all` always
reflects *current* core.models (not a frozen snapshot), a fresh install running this
whole chain today finds contacts/referrals already created by 0001 — only an install
upgrading from a real pre-0003 database needs this revision to do anything.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from core.models import JSONType, UTCDateTime

revision = "0003_referrals"
down_revision = "0002_bypass_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("contacts"):
        return
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("company", sa.String(255), nullable=False, server_default=""),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("email", sa.String(255), nullable=False, server_default=""),
        sa.Column("role", sa.String(255), nullable=False, server_default=""),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_contacts_company", "contacts", ["company"])

    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="drafted"),
        sa.Column("status_history", JSONType, nullable=False),
        sa.Column("engine", sa.String(32), nullable=False, server_default=""),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_referrals_job", "referrals", ["job_id"])
    op.create_index("ix_referrals_contact", "referrals", ["contact_id"])


def downgrade() -> None:
    op.drop_index("ix_referrals_contact", table_name="referrals")
    op.drop_index("ix_referrals_job", table_name="referrals")
    op.drop_table("referrals")
    op.drop_index("ix_contacts_company", table_name="contacts")
    op.drop_table("contacts")
