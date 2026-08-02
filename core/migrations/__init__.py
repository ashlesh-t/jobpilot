"""Alembic migration tree, driven programmatically (no alembic.ini on disk).

`upgrade_to_head()` is called at every service start, so a user who upgrades JobPilot
never has to run a migration command by hand. A brand-new database is stamped and
built by the same revisions, so fresh installs and upgrades share one code path.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

MIGRATIONS_DIR = Path(__file__).resolve().parent


def alembic_config(url: str):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Escape % so ConfigParser interpolation doesn't choke on URL-encoded passwords.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade_to_head(engine: Engine, url: str) -> None:
    """Run every pending migration. Safe to call on an already-current database."""
    from alembic import command

    cfg = alembic_config(url)
    cfg.attributes["connection"] = engine
    command.upgrade(cfg, "head")


def current_revision(engine: Engine) -> str | None:
    from alembic.migration import MigrationContext

    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()
