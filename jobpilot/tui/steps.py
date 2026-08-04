"""The individual steps of `jobpilot setup`.

Each step is a function that takes the shared context, does its work, persists what it
learned immediately, and returns. Raising `GoBack` returns to the previous step; every
step is safe to re-enter, because none of them assume a blank slate.

`jobpilot setup` is an *instance* bootstrap now, not full per-account configuration:
it migrates the database, lets you pick storage, and creates or claims the first
login. Resume, preferences, AI backend and delivery channels are all per-account and
live in the browser (the `SetupWizard`/Settings page on first login) — the CLI no
longer collects any of that.
"""
from __future__ import annotations

import re

from . import prompts, theme

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: str) -> str | None:
    return None if EMAIL_RE.match(value) else "That doesn't look like an email address."


# --------------------------------------------------------------------------- #
# 1 — Storage
# --------------------------------------------------------------------------- #
def step_database(ctx: dict) -> None:
    from core import db
    from core.infra import docker
    from core.paths import jobpilot_dir

    theme.step_header(1, 3, "Storage",
                      "JobPilot keeps everything on your machine. Nothing is uploaded.")
    theme.info(f"Data directory: {jobpilot_dir()}")

    available, detail = docker.docker_available()
    if not available:
        theme.warn(f"Docker unavailable — {detail}")
        theme.info("Using SQLite instead. Everything works; Postgres is only faster "
                   "once you have tens of thousands of jobs.")
        choice = "sqlite"
    else:
        theme.success(detail)
        choice = prompts.ask_select(
            "Which database should JobPilot use?",
            [
                {"value": "postgres", "label": "PostgreSQL in Docker",
                 "hint": "recommended — a managed local container"},
                {"value": "sqlite", "label": "SQLite file",
                 "hint": "zero infrastructure, single file"},
            ],
            default="postgres",
        )

    if choice == "postgres":
        with theme.spinner("Starting the jobpilot-postgres container (first run pulls "
                           "the image, ~30s)…"):
            result = docker.provision()
        if result["backend"] == "postgres":
            theme.success(result["message"])
        else:
            theme.warn(result["message"])
    else:
        url = db.sqlite_url()
        db.save_url(url, backend="sqlite", container="")
        db.dispose()
        with theme.spinner("Preparing the database…"):
            db.init_db(url)
        theme.success("SQLite database ready.")

    theme.out()


# --------------------------------------------------------------------------- #
# 2 — Account
# --------------------------------------------------------------------------- #
def step_account(ctx: dict) -> None:
    """Create the first login on a fresh instance, claim an upgraded legacy account,
    or confirm there's nothing left to do here — creating any *further* account is
    the web signup flow now (`POST /api/auth/signup`), not the CLI."""
    from core.repo import users as users_repo

    theme.step_header(2, 3, "Account",
                      "Everything else — resume, preferences, AI backend, delivery — "
                      "is configured per-account in the browser after you log in.")

    if users_repo.count() == 0:
        user = _create_first_account()
    else:
        legacy = users_repo.find_legacy()
        user = _claim_legacy_account(legacy) if legacy else None

    if user is None:
        theme.success("This instance already has an account configured.")
        theme.info("Nothing left to do here — log in at the URL `jobpilot start` prints.")
        ctx["user_id"] = None
        theme.out()
        return

    ctx["user_id"] = user["id"]
    _run_v1_migration(user["id"])
    theme.out()


def _create_first_account() -> dict:
    from core.repo import users as users_repo

    theme.info("No accounts exist yet on this instance — let's create the first one.")
    username = prompts.ask_text("Choose a username", allow_empty=False, allow_back=False)
    email = prompts.ask_text("Email (optional)", allow_empty=True, allow_back=False,
                             validate=_validate_email)
    password = _ask_new_password()
    user = users_repo.create(username=username, password=password,
                             email=email or None, is_admin=True)
    theme.success(f"Account '{user['username']}' created — you're the instance admin.")
    return user


def _claim_legacy_account(legacy: dict) -> dict:
    from core.repo import users as users_repo

    theme.panel(
        "This machine was upgraded from an earlier single-user JobPilot install. "
        "Claiming its account keeps every existing job, preference, resume and run "
        "history under your new login.",
        title="Claim your existing data",
    )
    while True:
        username = prompts.ask_text("Choose a username", allow_empty=False, allow_back=False)
        password = _ask_new_password()
        user = users_repo.claim_legacy(legacy["id"], username=username, password=password)
        if user is not None:
            theme.success(f"Claimed as '{user['username']}' — your data is preserved.")
            return user
        theme.warn("Could not claim that account — it may already have been claimed.")
        legacy = users_repo.find_legacy()
        if legacy is None:
            theme.info("Looks like it was just claimed elsewhere — creating a fresh "
                       "account for you instead.")
            return _create_first_account()


def _ask_new_password() -> str:
    while True:
        password = prompts.ask_secret("Choose a password", allow_back=False)
        confirm = prompts.ask_secret("Confirm password", allow_back=False)
        if password == confirm:
            return password
        theme.warn("Passwords didn't match — try again.")


def _run_v1_migration(user_id: int) -> None:
    """Import JobPilot v1 state if this machine has any. Silent when there's nothing."""
    from core import migrate_v1

    if migrate_v1.already_migrated() or not migrate_v1.has_v1_state():
        return
    theme.info("Found data from an earlier JobPilot version.")
    if not prompts.ask_confirm("Import it (jobs, profile, preferences, history)?",
                               default=True):
        return
    with theme.spinner("Importing…"):
        report = migrate_v1.migrate(user_id)
    counts = report.get("counts", {})
    moved = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
    theme.success(f"Imported {moved or 'nothing new'}. Your old files were left untouched.")
    for err in report.get("errors", [])[:3]:
        theme.warn(err)


# --------------------------------------------------------------------------- #
# 3 — Finish
# --------------------------------------------------------------------------- #
def step_finish(ctx: dict) -> None:
    theme.step_header(3, 3, "All set")
    _offer_tectonic()

    rows = _final_summary(ctx.get("user_id"))
    theme.summary_table(rows)
    theme.out()
    theme.panel(
        "Start JobPilot and finish the rest in your browser:\n\n"
        "  [bold]jobpilot start[/bold]\n\n"
        "There you'll log in, upload your resume, set your job preferences,\n"
        "pick an AI backend, connect delivery, and launch your first hunt.",
        title="Next step",
    )


def _offer_tectonic() -> None:
    """Tailored resumes compile to PDF only when tectonic is on PATH. Optional and
    instance-wide, so this stays a CLI concern even though the rest of the wizard
    moved to the browser."""
    from core import backends, tailoring

    if tailoring.has_tectonic():
        return

    theme.info("No PDF compiler found — tailored resumes would come out as LaTeX "
               "source instead of a ready-to-send PDF.")
    if not prompts.ask_confirm("Install the PDF compiler (tectonic) now?", default=True):
        theme.info("Skipped. Install it later with:  "
                   + "  or  ".join(backends.tectonic_install_hints()))
        return

    with theme.spinner("Downloading tectonic (~30s, no admin rights needed)…"):
        ok, message = backends.install_tectonic()
    (theme.success if ok else theme.warn)(message)


def _final_summary(user_id: int | None) -> list[tuple[str, str, str]]:
    from core.db import is_sqlite, ping
    from core.repo import users as users_repo
    from core import tailoring

    rows: list[tuple[str, str, str]] = []
    if user_id is not None:
        user = users_repo.get_by_id(user_id)
        rows.append(("Account", "ok", user["username"] if user else "—"))
    else:
        rows.append(("Account", "ok", "already configured"))

    ok, detail = ping()
    rows.append(("Database", "ok" if ok else "fail",
                 ("SQLite" if is_sqlite() else "PostgreSQL") + f" — {detail}"))

    has_pdf = tailoring.has_tectonic()
    rows.append(("PDF compiler", "ok" if has_pdf else "skip",
                 "tectonic — tailored resumes compile to PDF" if has_pdf
                 else "not installed — tailored resumes stay as LaTeX source"))
    return rows


STEPS = [
    ("Storage", step_database),
    ("Account", step_account),
    ("Done", step_finish),
]
