"""Multi-user accounts: users/sessions/user_secrets, user_id on every per-account
table, and a Job/JobUserScore split so per-user scoring stops living on the shared
job listing.

Revision ID: 0004_users
Revises: 0003_referrals
Create Date: 2026-08-04

This is the schema half of turning JobPilot from a single-tenant tool into a shared
instance with real accounts. An existing single-user install has rows with no owner,
so this migration also **backfills** one locked "legacy" admin account and assigns
every pre-existing row to it — nothing is dropped, nothing orphaned. That account's
password is a random value nobody knows (`core.auth.locked_password_hash`);
`User.must_set_password` marks it, and the next run of `jobpilot setup` (or
`POST /api/auth/claim`) prompts to give it a real username and password.

Every step below is individually idempotent (checked against live inspector state,
not a single up-front branch) so this migration is safe to re-run after a transient
failure leaves some but not all of it applied — important since `upgrade_to_head()`
runs automatically at every service start (see core/db.py, CLAUDE.md) and a partial
DDL failure must not silently skip the rest forever on the next boot. It is also safe
to run against a database `create_all` already built from *current* core.models (a
brand-new install — see 0001's docstring on why that's always the current schema, not
a frozen snapshot): every add/create call below checks first and no-ops if the target
is already there.

SQLite has no ALTER TABLE support for constraint changes, and its reflection of
unnamed inline `UNIQUE`/`PRIMARY KEY` constraints (used by columns declared with
`unique=True` before this revision, e.g. `applications.job_id`) doesn't yield a name
`drop_constraint` can target. So constraint-shape changes use `batch_alter_table(...,
copy_from=<explicit target Table>)` on SQLite, which recreates the table from a
hand-described definition instead of trying to name and drop the old constraint.
PostgreSQL supports both ALTER TABLE and named constraint drops directly (its default
auto-naming for an unnamed single-column unique is `<table>_<column>_key`), so that
dialect uses direct ops instead of a table rebuild.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session

from core.models import JSONType, UTCDateTime

revision = "0004_users"
down_revision = "0003_referrals"
branch_labels = None
depends_on = None


# (table, unique-constraint-column, new FK column already added by the time this
# runs) — every table below gains a plain, non-unique `user_id` FK column.
SIMPLE_USER_TABLES = [
    "profiles", "runs", "scans", "tailored_resumes", "contacts",
    "referrals", "cost_ledger", "schedule_slots", "chat_messages",
]


def _is_sqlite(bind) -> bool:
    return bind.dialect.name == "sqlite"


def _legacy_user_id(bind) -> int | None:
    """Create the locked legacy account iff there is pre-existing data to own — a
    brand-new database has nothing to backfill and gets no legacy user at all.
    Idempotent: if a legacy account already exists (a prior partial run created it),
    reuse it instead of inserting a second one."""
    from core.auth import locked_password_hash

    session = Session(bind=bind)
    try:
        existing = session.execute(
            sa.text("SELECT id FROM users WHERE must_set_password = :t"),
            {"t": True},
        ).scalar()
        if existing is not None:
            return existing

        job_count = session.execute(sa.text("SELECT COUNT(*) FROM jobs")).scalar() or 0
        run_count = session.execute(sa.text("SELECT COUNT(*) FROM runs")).scalar() or 0
        setting_count = session.execute(sa.text("SELECT COUNT(*) FROM settings")).scalar() or 0
        if not (job_count or run_count or setting_count):
            return None

        session.execute(
            sa.text(
                "INSERT INTO users (username, email, password_hash, is_admin, "
                "must_set_password, created_at) "
                "VALUES (:username, NULL, :password_hash, TRUE, TRUE, :created_at)"
            ),
            {
                "username": "legacy-admin",
                "password_hash": locked_password_hash(),
                "created_at": datetime.now(timezone.utc),
            },
        )
        session.commit()
        return session.execute(
            sa.text("SELECT id FROM users WHERE username = :u"), {"u": "legacy-admin"}
        ).scalar()
    finally:
        session.close()


def _ensure_table(inspector, name: str, *columns) -> None:
    if not inspector.has_table(name):
        op.create_table(name, *columns)


def _ensure_index(inspector, table: str, name: str, columns: list[str], **kw) -> None:
    existing = {ix["name"] for ix in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, **kw)


def _ensure_user_id_column(bind, inspector, table: str, legacy_id: int | None) -> None:
    """Add a plain `user_id` FK + index to `table`, backfilling existing rows to
    `legacy_id`. Every sub-step checks live state first, so this is safe to re-run."""
    cols = {c["name"] for c in inspector.get_columns(table)}
    if "user_id" not in cols:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))

    if legacy_id is not None:
        op.execute(sa.text(f"UPDATE {table} SET user_id = :uid WHERE user_id IS NULL")
                  .bindparams(uid=legacy_id))

    inspector = sa.inspect(bind)
    col = next(c for c in inspector.get_columns(table) if c["name"] == "user_id")
    fks = {fk["name"] for fk in inspector.get_foreign_keys(table) if fk["name"]}
    indexes = {ix["name"] for ix in inspector.get_indexes(table)}
    fk_name, ix_name = f"fk_{table}_user", f"ix_{table}_user"
    needs_not_null = col["nullable"]
    needs_fk = fk_name not in fks
    needs_ix = ix_name not in indexes
    if needs_not_null or needs_fk or needs_ix:
        with op.batch_alter_table(table) as batch:
            if needs_not_null:
                batch.alter_column("user_id", nullable=False)
            if needs_fk:
                batch.create_foreign_key(fk_name, "users", ["user_id"], ["id"], ondelete="CASCADE")
            if needs_ix:
                batch.create_index(ix_name, ["user_id"])


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = _is_sqlite(bind)
    inspector = sa.inspect(bind)

    # -- new tables ------------------------------------------------------------ #
    _ensure_table(
        inspector, "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("must_set_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("last_login_at", UTCDateTime(), nullable=True),
    )
    inspector = sa.inspect(bind)
    _ensure_table(
        inspector, "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("user_agent", sa.String(255), nullable=False, server_default=""),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
    )
    inspector = sa.inspect(bind)
    _ensure_index(inspector, "sessions", "ix_sessions_user", ["user_id"])
    _ensure_table(
        inspector, "user_secrets",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value_encrypted", sa.Text(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )

    legacy_id = _legacy_user_id(bind)

    # -- simple tables: add user_id, backfill, enforce NOT NULL ---------------- #
    for table in SIMPLE_USER_TABLES:
        inspector = sa.inspect(bind)
        _ensure_user_id_column(bind, inspector, table, legacy_id)

    # -- settings, resumes, applications: add + backfill user_id first (plain,
    # nullable-then-NOT-NULL via _ensure_user_id_column, same as the simple tables)
    # BEFORE touching the PK/unique shape below. Folding the column add and the
    # constraint rebuild into a single SQLite recreate doesn't work: `copy_from`
    # would declare `user_id` NOT NULL from the start, and the data-copy step that
    # populates the recreated table runs before this migration has backfilled
    # anything — every pre-existing row would fail that NOT NULL check immediately.
    for table in ("settings", "resumes", "applications", "user_feedback"):
        inspector = sa.inspect(bind)
        if "user_id" not in {c["name"] for c in inspector.get_columns(table)}:
            _ensure_user_id_column(bind, inspector, table, legacy_id)

    # -- settings: PK (key) -> (user_id, key) ----------------------------------- #
    inspector = sa.inspect(bind)
    pk_cols = inspector.get_pk_constraint("settings").get("constrained_columns") or []
    if "user_id" not in pk_cols:
        if sqlite:
            target = sa.Table(
                "settings", sa.MetaData(),
                sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                         primary_key=True, nullable=False),
                sa.Column("key", sa.String(128), primary_key=True, nullable=False),
                sa.Column("value", JSONType, nullable=True),
                sa.Column("updated_at", UTCDateTime(), nullable=False),
            )
            with op.batch_alter_table("settings", copy_from=target, recreate="always"):
                pass
        else:
            op.drop_constraint("settings_pkey", "settings", type_="primary")
            op.create_primary_key("pk_settings", "settings", ["user_id", "key"])

    # -- resumes: unique(folder, filename) -> unique(user_id, folder, filename) - #
    inspector = sa.inspect(bind)
    existing_uniques = {u["name"] for u in inspector.get_unique_constraints("resumes")}
    if "uq_resume_user_folder_filename" not in existing_uniques:
        if sqlite:
            target = sa.Table(
                "resumes", sa.MetaData(),
                sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                sa.Column("folder", sa.String(128), nullable=False),
                sa.Column("filename", sa.String(255), nullable=False),
                sa.Column("path", sa.Text(), nullable=False),
                sa.Column("label", sa.String(255), nullable=False),
                sa.Column("file_hash", sa.String(64), nullable=False),
                sa.Column("parsed_text", sa.Text(), nullable=True),
                sa.Column("is_active", sa.Boolean(), nullable=False),
                sa.Column("uploaded_at", UTCDateTime(), nullable=False),
                sa.UniqueConstraint("user_id", "folder", "filename", name="uq_resume_user_folder_filename"),
            )
            with op.batch_alter_table("resumes", copy_from=target, recreate="always"):
                pass
        else:
            op.drop_constraint("uq_resume_folder_filename", "resumes", type_="unique")
            op.create_unique_constraint("uq_resume_user_folder_filename", "resumes",
                                        ["user_id", "folder", "filename"])

    # -- applications: unique(job_id) -> unique(user_id, job_id) --------------- #
    inspector = sa.inspect(bind)
    existing_uniques = {u["name"] for u in inspector.get_unique_constraints("applications")}
    if "uq_application_user_job" not in existing_uniques:
        if sqlite:
            target = sa.Table(
                "applications", sa.MetaData(),
                sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
                sa.Column("status", sa.String(32), nullable=False),
                sa.Column("applied_at", UTCDateTime(), nullable=False),
                sa.Column("updated_at", UTCDateTime(), nullable=False),
                sa.Column("status_history", JSONType, nullable=False),
                sa.Column("notes", sa.Text(), nullable=False),
                sa.Column("reminder_at", UTCDateTime(), nullable=True),
                sa.UniqueConstraint("user_id", "job_id", name="uq_application_user_job"),
            )
            with op.batch_alter_table("applications", copy_from=target, recreate="always"):
                pass
        else:
            op.drop_constraint("applications_job_id_key", "applications", type_="unique")
            op.create_unique_constraint("uq_application_user_job", "applications", ["user_id", "job_id"])

    # -- tailored_resumes: unique(folder_name) -> unique(user_id, folder_name) - #
    inspector = sa.inspect(bind)
    existing_uniques = {u["name"] for u in inspector.get_unique_constraints("tailored_resumes")}
    if "uq_tailored_user_folder" not in existing_uniques:
        if sqlite:
            target = sa.Table(
                "tailored_resumes", sa.MetaData(),
                sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
                sa.Column("folder_name", sa.String(255), nullable=False),
                sa.Column("pdf_path", sa.Text(), nullable=False),
                sa.Column("tex_path", sa.Text(), nullable=False),
                sa.Column("docx_path", sa.Text(), nullable=False),
                sa.Column("base_resume_id", sa.Integer(),
                         sa.ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True),
                sa.Column("ats_before", sa.Float(), nullable=True),
                sa.Column("ats_after", sa.Float(), nullable=True),
                sa.Column("engine", sa.String(32), nullable=False),
                sa.Column("cost_usd", sa.Float(), nullable=False),
                sa.Column("status", sa.String(16), nullable=False),
                sa.Column("error", sa.Text(), nullable=False),
                sa.Column("meta", JSONType, nullable=False),
                sa.Column("created_at", UTCDateTime(), nullable=False),
                sa.UniqueConstraint("user_id", "folder_name", name="uq_tailored_user_folder"),
            )
            with op.batch_alter_table("tailored_resumes", copy_from=target, recreate="always"):
                pass
        else:
            op.drop_constraint("uq_tailored_folder", "tailored_resumes", type_="unique")
            op.create_unique_constraint("uq_tailored_user_folder", "tailored_resumes",
                                        ["user_id", "folder_name"])

    # -- user_feedback: PK (job_id) -> (user_id, job_id) ------------------------ #
    # (user_id column + FK + backfill already handled by the loop above)
    inspector = sa.inspect(bind)
    pk_cols = inspector.get_pk_constraint("user_feedback").get("constrained_columns") or []
    if "user_id" not in pk_cols:
        if sqlite:
            target = sa.Table(
                "user_feedback", sa.MetaData(),
                sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
                         primary_key=True, nullable=False),
                sa.Column("job_id", sa.String(64), primary_key=True, nullable=False),
                sa.Column("status", sa.String(32), nullable=False),
                sa.Column("notes", sa.Text(), nullable=False),
                sa.Column("feedback_date", UTCDateTime(), nullable=False),
            )
            with op.batch_alter_table("user_feedback", copy_from=target, recreate="always"):
                pass
        else:
            op.drop_constraint("user_feedback_pkey", "user_feedback", type_="primary")
            op.create_primary_key("pk_user_feedback", "user_feedback", ["user_id", "job_id"])

    # -- schedule_slots: unique(name) -> unique(user_id, name) ------------------ #
    # (user_id column + FK + index already added by the SIMPLE_USER_TABLES loop above)
    inspector = sa.inspect(bind)
    existing_uniques = {u["name"] for u in inspector.get_unique_constraints("schedule_slots")}
    if "uq_schedule_user_name" not in existing_uniques:
        if sqlite:
            cols = inspector.get_columns("schedule_slots")
            target = sa.Table(
                "schedule_slots", sa.MetaData(),
                sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
                sa.Column("name", sa.String(64), nullable=False),
                sa.Column("time_hhmm", sa.String(5), nullable=False),
                sa.Column("timezone", sa.String(64), nullable=False),
                sa.Column("mode", sa.String(16), nullable=False),
                sa.Column("enabled", sa.Boolean(), nullable=False),
                sa.Column("days", sa.String(32), nullable=False),
                sa.Column("last_fired_at", UTCDateTime(), nullable=True),
                sa.Column("last_run_id", sa.String(64), nullable=False),
                sa.Column("last_outcome", sa.String(32), nullable=False),
                sa.Column("created_at", UTCDateTime(), nullable=False),
                sa.UniqueConstraint("user_id", "name", name="uq_schedule_user_name"),
            )
            with op.batch_alter_table("schedule_slots", copy_from=target, recreate="always"):
                pass
        else:
            op.drop_constraint("schedule_slots_name_key", "schedule_slots", type_="unique")
            op.create_unique_constraint("uq_schedule_user_name", "schedule_slots", ["user_id", "name"])

    # -- Job / JobUserScore split ------------------------------------------------ #
    inspector = sa.inspect(bind)
    _ensure_table(
        inspector, "job_user_scores",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("job_id", sa.String(64), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("keyword_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("semantic_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("effective_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("location_weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("bar_fit", sa.Float(), nullable=False, server_default="0"),
        sa.Column("learning_adj", sa.Float(), nullable=False, server_default="0"),
        sa.Column("score_confidence", sa.String(16), nullable=False, server_default=""),
        sa.Column("matched_skills", JSONType, nullable=False),
        sa.Column("missing_skills", JSONType, nullable=False),
        sa.Column("archetype", sa.String(48), nullable=False, server_default=""),
        sa.Column("prep_focus", sa.Text(), nullable=False, server_default=""),
        sa.Column("gap_signals", sa.Text(), nullable=False, server_default=""),
        sa.Column("market_salary", sa.String(128), nullable=False, server_default=""),
        sa.Column("your_demand", sa.String(128), nullable=False, server_default=""),
        sa.Column("salary_source", sa.String(128), nullable=False, server_default=""),
        sa.Column("salary_min_lpa", sa.Float(), nullable=True),
        sa.Column("salary_max_lpa", sa.Float(), nullable=True),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    inspector = sa.inspect(bind)
    _ensure_index(inspector, "job_user_scores", "ix_job_scores_user_effective",
                 ["user_id", "effective_score"])
    _ensure_index(inspector, "job_user_scores", "ix_job_scores_job", ["job_id"])

    jobs_cols = {c["name"] for c in inspector.get_columns("jobs")}
    score_cols = (
        "score", "keyword_score", "semantic_score", "effective_score",
        "location_weight", "bar_fit", "learning_adj", "score_confidence",
        "matched_skills", "missing_skills", "archetype", "prep_focus", "gap_signals",
        "market_salary", "your_demand", "salary_source", "salary_min_lpa", "salary_max_lpa",
    )
    if "score" in jobs_cols:
        if legacy_id is not None:
            already_copied = op.get_bind().execute(
                sa.text("SELECT COUNT(*) FROM job_user_scores WHERE user_id = :uid"),
                {"uid": legacy_id},
            ).scalar() or 0
            if not already_copied:
                op.execute(sa.text(f"""
                    INSERT INTO job_user_scores (
                        user_id, job_id, score, keyword_score, semantic_score, effective_score,
                        location_weight, bar_fit, learning_adj, score_confidence,
                        matched_skills, missing_skills, archetype, prep_focus, gap_signals,
                        market_salary, your_demand, salary_source, salary_min_lpa, salary_max_lpa,
                        updated_at
                    )
                    SELECT
                        {legacy_id}, job_id, score, keyword_score, semantic_score, effective_score,
                        location_weight, bar_fit, learning_adj, score_confidence,
                        matched_skills, missing_skills, archetype, prep_focus, gap_signals,
                        market_salary, your_demand, salary_source, salary_min_lpa, salary_max_lpa,
                        last_seen
                    FROM jobs
                """))

        if sqlite:
            target = sa.Table(
                "jobs", sa.MetaData(),
                sa.Column("job_id", sa.String(64), primary_key=True),
                sa.Column("company", sa.String(255), nullable=False),
                sa.Column("role", sa.String(255), nullable=False),
                sa.Column("location", sa.String(255), nullable=False),
                sa.Column("source_board", sa.String(64), nullable=False),
                sa.Column("application_url", sa.Text(), nullable=False),
                sa.Column("apply_type", sa.String(32), nullable=False),
                sa.Column("jd_full", sa.Text(), nullable=False),
                sa.Column("experience_req", sa.String(128), nullable=False),
                sa.Column("exp_req_years", sa.Float(), nullable=True),
                sa.Column("posted_date", sa.String(32), nullable=False),
                sa.Column("last_date", sa.String(32), nullable=False),
                sa.Column("scan_id", sa.Integer(), sa.ForeignKey("scans.id", ondelete="SET NULL"), nullable=True),
                sa.Column("first_seen", UTCDateTime(), nullable=False),
                sa.Column("last_seen", UTCDateTime(), nullable=False),
                sa.Column("is_stale", sa.Boolean(), nullable=False),
                sa.Column("extra", JSONType, nullable=False),
            )
            with op.batch_alter_table("jobs", copy_from=target, recreate="always"):
                pass
        else:
            with op.batch_alter_table("jobs") as batch:
                batch.drop_index("ix_jobs_effective_score")
                for col in score_cols:
                    batch.drop_column(col)

    inspector = sa.inspect(bind)
    _ensure_index(inspector, "jobs", "ix_jobs_scan", ["scan_id"])
    _ensure_index(inspector, "jobs", "ix_jobs_last_seen", ["last_seen"])
    _ensure_index(inspector, "jobs", "ix_jobs_company", ["company"])
    _ensure_index(inspector, "jobs", "ix_jobs_stale", ["is_stale"])


def downgrade() -> None:
    """Not reversible — the Job/JobUserScore split loses which user a score belonged
    to on the way back, and the legacy-account backfill can't be un-guessed."""
