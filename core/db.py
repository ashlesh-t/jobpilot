"""Database engine factory — PostgreSQL (Docker) with a SQLite fallback.

Resolution order for the DSN:
  1. $JOBPILOT_DATABASE_URL              — explicit override, always wins
  2. cache/database.json                 — what `jobpilot setup` resolved last time
  3. sqlite:///<jobpilot_dir>/cache/jobpilot.db

`jobpilot setup` calls `core.infra.docker.ensure_postgres()` and, if it succeeds, writes
the Postgres DSN into cache/database.json. Everything else just calls `get_engine()` and
neither knows nor cares which backend it got.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from .models import Base
from .paths import db_config_path, ensure_dirs, sqlite_path

_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None
_resolved_url: str | None = None


# --------------------------------------------------------------------------- #
# URL resolution
# --------------------------------------------------------------------------- #
def sqlite_url() -> str:
    ensure_dirs()
    return f"sqlite+pysqlite:///{sqlite_path()}"


def read_saved_url() -> str | None:
    try:
        cfg = json.loads(db_config_path().read_text())
    except Exception:
        return None
    url = cfg.get("url")
    return url if isinstance(url, str) and url else None


def save_url(url: str, **extra) -> None:
    """Persist the resolved DSN so every process (CLI, server, daemon) agrees."""
    ensure_dirs()
    path = db_config_path()
    cfg: dict = {}
    if path.exists():                       # read-before-write (repo rule)
        try:
            cfg = json.loads(path.read_text())
        except Exception:
            cfg = {}
    cfg.update({"url": url, **extra})
    path.write_text(json.dumps(cfg, indent=2))


def resolve_url() -> str:
    env = os.environ.get("JOBPILOT_DATABASE_URL")
    if env:
        return env
    return read_saved_url() or sqlite_url()


def is_sqlite(url: str | None = None) -> bool:
    return (url or resolve_url()).startswith("sqlite")


# --------------------------------------------------------------------------- #
# Engine / session
# --------------------------------------------------------------------------- #
def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        eng = create_engine(
            url,
            future=True,
            # The scheduler thread, the SSE tasks and the orchestrator all touch the DB.
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _rec):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")      # concurrent reads during a run
            cur.execute("PRAGMA foreign_keys=ON")       # off by default in SQLite
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

        return eng
    return create_engine(url, future=True, pool_pre_ping=True, pool_size=5, max_overflow=10)


def get_engine(url: str | None = None) -> Engine:
    """Process-wide engine singleton. Pass `url` only in tests."""
    global _engine, _Session, _resolved_url
    target = url or resolve_url()
    if _engine is None or target != _resolved_url:
        dispose()
        _engine = _make_engine(target)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
        _resolved_url = target
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _Session is not None
    return _Session


def dispose() -> None:
    """Drop the cached engine — used by tests and after a DSN change."""
    global _engine, _Session, _resolved_url
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
    _engine, _Session, _resolved_url = None, None, None


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session. Commits on success, rolls back on any exception."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# Schema management
# --------------------------------------------------------------------------- #
def init_db(url: str | None = None) -> str:
    """Bring the schema up to date and return the URL that was used.

    Uses Alembic when it is importable and the migration tree is present (the normal
    install); falls back to `create_all` so a source checkout without Alembic still
    boots. Both paths converge on the same schema for a fresh database.
    """
    target = url or resolve_url()
    engine = get_engine(target)
    try:
        from .migrations import upgrade_to_head
        upgrade_to_head(engine, target)
    except Exception:
        Base.metadata.create_all(engine)
    return target


def ping(url: str | None = None) -> tuple[bool, str]:
    """Cheap health check for the doctor page."""
    try:
        eng = get_engine(url) if url else get_engine()
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        backend = "sqlite" if is_sqlite(url) else "postgresql"
        return True, f"{backend} reachable"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
