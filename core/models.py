"""SQLAlchemy 2.0 ORM models — one schema, two dialects (PostgreSQL and SQLite).

Design rules:
  * Secrets are encrypted at rest in `user_secrets` via core/crypto.py before they ever
    reach a column — see that module, not the OS keyring, which is now only used to
    hold the one instance-wide encryption key. The `settings` table only records
    *which* (non-secret) settings exist.
  * JSON columns use JSONB on PostgreSQL and plain JSON on SQLite via `with_variant`,
    so the same model works on both without dialect branches in query code.
  * Timestamps are timezone-aware UTC everywhere. Display-time conversion (IST) is the
    UI's job, never the database's.
  * Multi-tenant: every row that represents a person's data carries `user_id`. `Job` is
    the one deliberate exception — the listing itself (company/role/JD) is shared and
    globally deduped; per-user scoring/intel/salary judgments live on `JobUserScore`.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

# JSONB on Postgres (indexable, binary), JSON on SQLite (stored as text).
JSONType = JSON().with_variant(JSONB, "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Always-aware UTC timestamps, on both dialects.

    SQLite has no native timestamp type and hands back naive datetimes, which then blow
    up when compared against `utcnow()`. This normalizes on the way in and re-attaches
    UTC on the way out, so application code only ever sees aware datetimes.
    """
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


def _ts(**kw) -> Mapped[datetime]:
    return mapped_column(UTCDateTime(), **kw)


# --------------------------------------------------------------------------- #
# Enums — stored as plain strings so a new value never needs a DB migration.
# --------------------------------------------------------------------------- #
class RunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    error = "error"
    cancelled = "cancelled"
    waiting_network = "waiting_network"


class PhaseStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    error = "error"
    cancelled = "cancelled"
    skipped = "skipped"


class ApplicationStatus(str, enum.Enum):
    applied = "applied"
    selected = "selected"
    interview = "interview"
    final_round = "final_round"
    placed = "placed"
    rejected = "rejected"
    ghosted = "ghosted"


APPLICATION_PIPELINE = [
    ApplicationStatus.applied,
    ApplicationStatus.selected,
    ApplicationStatus.interview,
    ApplicationStatus.final_round,
    ApplicationStatus.placed,
]
APPLICATION_TERMINAL = [ApplicationStatus.rejected, ApplicationStatus.ghosted]


class ReferralStatus(str, enum.Enum):
    """Draft-only, always — see server/routes_referrals.py. Nothing here ever sends
    anything; this only tracks what the user did with a message they drafted."""
    drafted = "drafted"
    sent = "sent"
    responded = "responded"
    declined = "declined"


REFERRAL_PIPELINE = [ReferralStatus.drafted, ReferralStatus.sent, ReferralStatus.responded]
REFERRAL_TERMINAL = [ReferralStatus.declined]


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
class User(Base):
    """An account on this JobPilot instance. Everything else hangs off `user_id`."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # True only for the auto-created legacy account from an existing single-user install
    # (see migration 0004) — its password_hash is a locked random value nobody knows.
    # `jobpilot setup`, run again after upgrading, detects this and prompts to claim the
    # account with a real username/password instead of leaving it unreachable.
    must_set_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = _ts(nullable=True)


class Session(Base):
    """A logged-in session. `id` is the opaque token stored in the HttpOnly cookie."""
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = _ts(nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    ip: Mapped[str] = mapped_column(String(64), default="", nullable=False)

    __table_args__ = (Index("ix_sessions_user", "user_id"),)


class UserSecret(Base):
    """A per-user credential (Apify token, Telegram bot token, ...), encrypted at rest
    by core/crypto.py before it reaches `value_encrypted`. See core/secrets.py."""
    __tablename__ = "user_secrets"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Fernet ciphertext is URL-safe base64 text — stored as text on both dialects.
    value_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = _ts(default=utcnow, onupdate=utcnow, nullable=False)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
class Setting(Base):
    """Key/value config store — replaces preferences.json as the source of truth.

    Values are JSON so a setting can be a scalar, a list (locations) or a nested
    object (engine config). Never holds a credential.
    """
    __tablename__ = "settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONType, nullable=True)
    updated_at: Mapped[datetime] = _ts(default=utcnow, onupdate=utcnow, nullable=False)


class Profile(Base):
    """A resume-derived candidate profile. One row per user is active at a time."""
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    data: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resume_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = _ts(default=utcnow, onupdate=utcnow, nullable=False)

    resume: Mapped["Resume | None"] = relationship(foreign_keys=[resume_id])

    __table_args__ = (Index("ix_profiles_user", "user_id"),)


class Resume(Base):
    """An uploaded resume file. Exactly one row per user has is_active=True."""
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    folder: Mapped[str] = mapped_column(String(128), default="default", nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    parsed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "folder", "filename", name="uq_resume_user_folder_filename"),
        Index("ix_resumes_active", "is_active"),
        Index("ix_resumes_user", "user_id"),
    )


# --------------------------------------------------------------------------- #
# Runs, phases, events
# --------------------------------------------------------------------------- #
class Run(Base):
    """One execution of the pipeline, phase by phase."""
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. 20260801T093000
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.pending.value, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)  # auto|full|native
    engine: Mapped[str] = mapped_column(String(32), default="claude_code", nullable=False)
    trigger: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)  # manual|schedule|catchup
    slot_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    started_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = _ts(nullable=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    phases: Mapped[list["Phase"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="Phase.position")
    scan: Mapped["Scan | None"] = relationship(back_populates="run", uselist=False,
                                               cascade="all, delete-orphan")

    __table_args__ = (Index("ix_runs_started", "started_at"), Index("ix_runs_user", "user_id"))


class Phase(Base):
    """One phase of a run — the unit of stop / resume / rerun."""
    __tablename__ = "phases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    phase_key: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=PhaseStatus.pending.value, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = _ts(nullable=True)
    ended_at: Mapped[datetime | None] = _ts(nullable=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Small structured result (counts, output paths). Bulk artifacts stay on disk under
    # runs/<run_id>/ and are referenced by path — never inlined here.
    artifact: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    run: Mapped["Run"] = relationship(back_populates="phases")

    __table_args__ = (
        UniqueConstraint("run_id", "phase_key", name="uq_phase_run_key"),
        Index("ix_phases_run", "run_id"),
    )


class RunEvent(Base):
    """Durable event timeline — what the live UI streams and history replays.

    Persisting these is what lets a finished run's timeline survive a service restart
    (the v1 in-memory `RunManager.recent` lost it).
    """
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = _ts(default=utcnow, nullable=False)
    phase_key: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    stage: Mapped[str] = mapped_column(String(32), default="log", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="progress", nullable=False)
    msg: Mapped[str] = mapped_column(Text, default="", nullable=False)
    data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), default="engine", nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_event_run_seq"),
        Index("ix_events_run_seq", "run_id", "seq"),
    )


class Scan(Base):
    """The job-discovery result of one run — what the Home page groups jobs by."""
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    started_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = _ts(nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    engine: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    jobs_raw: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_after_filter: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_scored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tailored_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    report_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_counts: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    run: Mapped["Run"] = relationship(back_populates="scan")

    __table_args__ = (Index("ix_scans_started", "started_at"), Index("ix_scans_user", "user_id"))


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
class Job(Base):
    """A discovered job listing. `job_id` is the Layer A SHA1 of company|role|location.

    Deliberately global/shared, not user-scoped — the listing itself (company, role,
    JD text) is the same regardless of who's looking at it, and de-duplicating it once
    across every account avoids re-scraping the same posting per user. Per-user scoring,
    intel and salary judgments — which depend on *whose* profile produced them — live
    on `JobUserScore` instead.
    """
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    company: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    source_board: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    application_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    apply_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    jd_full: Mapped[str] = mapped_column(Text, default="", nullable=False)
    experience_req: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    exp_req_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    posted_date: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    last_date: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    # provenance
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)
    first_seen: Mapped[datetime] = _ts(default=utcnow, nullable=False)
    last_seen: Mapped[datetime] = _ts(default=utcnow, nullable=False)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    extra: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    scores: Mapped[list["JobUserScore"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")
    tailored: Mapped[list["TailoredResume"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")
    referrals: Mapped[list["Referral"]] = relationship(
        back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_jobs_scan", "scan_id"),
        Index("ix_jobs_last_seen", "last_seen"),
        Index("ix_jobs_company", "company"),
        Index("ix_jobs_stale", "is_stale"),
    )


class JobUserScore(Base):
    """One user's scoring/intel/salary judgment of one job (see CLAUDE.md "Scoring").
    Everything here depends on whose profile produced it, so — unlike `Job` — this is
    per-user and never shared."""
    __tablename__ = "job_user_scores"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), primary_key=True)

    # scoring
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    keyword_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    semantic_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    effective_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    location_weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    bar_fit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    learning_adj: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    score_confidence: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    matched_skills: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    missing_skills: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    # intelligence
    archetype: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    prep_focus: Mapped[str] = mapped_column(Text, default="", nullable=False)
    gap_signals: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # salary research
    market_salary: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    your_demand: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    salary_source: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    salary_min_lpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max_lpa: Mapped[float | None] = mapped_column(Float, nullable=True)

    updated_at: Mapped[datetime] = _ts(default=utcnow, onupdate=utcnow, nullable=False)

    job: Mapped["Job"] = relationship(back_populates="scores")

    __table_args__ = (
        Index("ix_job_scores_user_effective", "user_id", "effective_score"),
        Index("ix_job_scores_job", "job_id"),
    )


class Application(Base):
    """One user's application to a job, with a dated status trail."""
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=ApplicationStatus.applied.value, nullable=False)
    applied_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = _ts(default=utcnow, onupdate=utcnow, nullable=False)
    # [{"status": "...", "at": "ISO-8601", "note": "..."}] — append-only audit trail
    status_history: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    reminder_at: Mapped[datetime | None] = _ts(nullable=True)

    job: Mapped["Job"] = relationship(back_populates="applications")

    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="uq_application_user_job"),
        Index("ix_applications_status", "status"),
        Index("ix_applications_user", "user_id"),
    )


class TailoredResume(Base):
    """A resume tailored to one job for one user. Files live under
    users/<user_id>/resumes/tailored/<folder_name>/."""
    __tablename__ = "tailored_resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    folder_name: Mapped[str] = mapped_column(String(255), nullable=False)  # <JOBID>-<COMPANY>
    pdf_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tex_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    docx_path: Mapped[str] = mapped_column(Text, default="", nullable=False)
    base_resume_id: Mapped[int | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True)
    ats_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    ats_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    engine: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="done", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)

    job: Mapped["Job"] = relationship(back_populates="tailored")

    __table_args__ = (
        UniqueConstraint("user_id", "folder_name", name="uq_tailored_user_folder"),
        Index("ix_tailored_job", "job_id"),
        Index("ix_tailored_user", "user_id"),
    )


class Contact(Base):
    """An HR/recruiter contact, imported from a spreadsheet or added by hand —
    matched to jobs by company name (see core/repo/_company_match.py)."""
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    role: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)  # import|manual
    created_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_contacts_company", "company"),
        Index("ix_contacts_user", "user_id"),
    )


class Referral(Base):
    """A drafted referral-request message for one job + contact. Draft-only: nothing
    in this codebase sends it anywhere — the user copies/edits/sends it themselves."""
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=ReferralStatus.drafted.value, nullable=False)
    # [{"status": "...", "at": "ISO-8601", "note": "..."}] — same audit-trail shape as
    # Application.status_history.
    status_history: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    engine: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = _ts(default=utcnow, onupdate=utcnow, nullable=False)

    job: Mapped["Job"] = relationship(back_populates="referrals")
    contact: Mapped["Contact"] = relationship()

    __table_args__ = (
        Index("ix_referrals_job", "job_id"),
        Index("ix_referrals_contact", "contact_id"),
        Index("ix_referrals_user", "user_id"),
    )


# --------------------------------------------------------------------------- #
# Cost, feedback, caches
# --------------------------------------------------------------------------- #
class CostEntry(Base):
    """One metered LLM call. `usd == 0` with source='subscription' means a Pro/Max
    Claude Code run: tokens are real, the marginal dollar cost is not."""
    __tablename__ = "cost_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phase_key: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="run", nullable=False)  # run|tailor|chat|setup
    engine: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    model: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="metered", nullable=False)  # metered|subscription|estimated
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_write: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ts: Mapped[datetime] = _ts(default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_cost_ts", "ts"), Index("ix_cost_run", "run_id"), Index("ix_cost_user", "user_id"),
    )


class UserFeedback(Base):
    """Ported from schema/init.sql — drives the learning loop. Per-user: the same job
    can be 'applied' for one account and untouched for another."""
    __tablename__ = "user_feedback"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    feedback_date: Mapped[datetime] = _ts(default=utcnow, nullable=False)


class UrlSecurityCache(Base):
    """Ported from schema/init.sql — used by scripts/url_security.py."""
    __tablename__ = "url_security_cache"

    url_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_label: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    is_allowlist: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    final_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    redirect_hops: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    threats: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    checked_at: Mapped[datetime | None] = _ts(nullable=True)
    expires_at: Mapped[datetime | None] = _ts(nullable=True)


class ScheduleSlot(Base):
    """A recurring run time. APScheduler jobs are rebuilt from these rows at start."""
    __tablename__ = "schedule_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    time_hhmm: Mapped[str] = mapped_column(String(5), nullable=False)  # "09:30"
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    days: Mapped[str] = mapped_column(String(32), default="*", nullable=False)  # cron day_of_week
    last_fired_at: Mapped[datetime | None] = _ts(nullable=True)
    last_run_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    last_outcome: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    created_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_schedule_user_name"),
        Index("ix_schedule_user", "user_id"),
    )


class ChatMessage(Base):
    """Assistant conversation history, so the chat survives a page reload."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user|assistant|tool
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    context: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = _ts(default=utcnow, nullable=False)

    __table_args__ = (
        Index("ix_chat_conv", "conversation_id", "created_at"),
        Index("ix_chat_user", "user_id"),
    )


ALL_TABLES = [
    User, Session, UserSecret,
    Setting, Profile, Resume, Run, Phase, RunEvent, Scan, Job, JobUserScore, Application,
    TailoredResume, CostEntry, UserFeedback, UrlSecurityCache, ScheduleSlot, ChatMessage,
    Contact, Referral,
]
