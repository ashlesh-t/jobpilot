"""Alembic environment — always runs online, against an engine handed in by core.db."""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# core/ must be importable when Alembic loads this file standalone (e.g. `alembic revision`).
REPO_DIR = Path(__file__).resolve().parents[2]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from core.models import Base  # noqa: E402

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
    with connectable.connect() as connection:
        sqlite = connection.dialect.name == "sqlite"
        if sqlite:
            # `PRAGMA foreign_keys` is a no-op once a transaction is open, so this has
            # to happen before begin_transaction() below — and be committed on its own
            # right away, so it doesn't leave this connection's implicit transaction
            # open (which would otherwise make Alembic's own begin_transaction() nest
            # inside it, and silently roll back everything on close since nothing then
            # calls the outer commit). Without disabling the pragma, a batch-mode table
            # recreate (add/drop-column or a constraint change on SQLite) CASCADE-
            # deletes rows in every other table with an `ON DELETE CASCADE` FK to the
            # table being rebuilt — SQLite fires cascade actions on DROP TABLE, not
            # just DELETE. Restored the same way once the migration is done.
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # batch mode makes ALTER TABLE work on SQLite, which has no real ALTER
            render_as_batch=sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()
        if sqlite:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
