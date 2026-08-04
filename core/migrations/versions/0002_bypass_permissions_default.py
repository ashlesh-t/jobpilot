"""Migrate the stale "acceptEdits" permission-mode default to "bypassPermissions".

Revision ID: 0002_bypass_permissions
Revises: 0001_initial
Create Date: 2026-08-03

Every phase runs headless (`claude -p`, no terminal, no human present), and every
skill's autonomy contract already forbids asking questions or blocking. "acceptEdits"
only auto-approves file edits — WebFetch/WebSearch/Bash still hit an unanswerable
permission prompt (most visibly, the discover phase's career-page fetches and web
searches, which just fail outright with no one able to click "allow").

The code default has moved to "bypassPermissions", but anyone who already ran
`jobpilot setup` before this change has the old value baked into their settings row,
and there has never been a Settings UI to change it by hand. Nobody deliberately chose
"acceptEdits" — it was always a silent default — so migrating everyone still on it is
safe and runs automatically on the next `jobpilot start`/`serve`, no manual step needed.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy.orm import Session

revision = "0002_bypass_permissions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from core.models import Setting

    session = Session(bind=op.get_bind())
    try:
        row = session.get(Setting, "engine")
        if row and isinstance(row.value, dict) and row.value.get("permission_mode") == "acceptEdits":
            row.value = {**row.value, "permission_mode": "bypassPermissions"}
            session.commit()
    finally:
        session.close()


def downgrade() -> None:
    """Not reversible — reverting would silently reintroduce a permission mode that
    hangs forever on an unanswerable prompt for every headless run."""
