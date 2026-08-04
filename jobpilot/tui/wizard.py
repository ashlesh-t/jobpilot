"""Wizard driver — runs the steps, handles back-navigation and clean aborts."""
from __future__ import annotations

from . import prompts, theme
from .prompts import Aborted, GoBack
from .steps import STEPS


def run_setup(*, non_interactive: bool = False, start_at: int = 0) -> int:
    """Run the full setup flow. Returns a process exit code."""
    from jobpilot.paths import inject_path

    inject_path()  # make core/ importable from a pipx install or a checkout

    from core.paths import ensure_dirs
    ensure_dirs()

    # The account step needs a working schema to query `users`, and it runs before
    # storage is finalized — so bring whatever database is currently resolved (SQLite
    # by default) up to head first. Step 1 (Storage) re-runs this against Postgres if
    # the user picks it, before the account step ever touches the database.
    _ensure_schema()

    if non_interactive or not prompts.is_interactive():
        return _headless()

    theme.banner()
    names = [name for name, _ in STEPS]
    ctx: dict = {}
    index = max(0, min(start_at, len(STEPS) - 1))

    while index < len(STEPS):
        theme.rail(names, index)
        _, step = STEPS[index]
        try:
            step(ctx)
        except GoBack:
            if index == 0:
                theme.info("Already at the first step.")
                continue
            index -= 1
            continue
        except Aborted:
            theme.out()
            theme.warn("Setup cancelled. Everything you already confirmed was saved — "
                       "run `jobpilot setup` again to pick up where you left off.")
            return 130
        except Exception as exc:  # noqa: BLE001
            theme.error(f"That step failed: {exc}")
            if not prompts.is_interactive():
                return 1
            try:
                choice = prompts.ask_select(
                    "What now?",
                    [
                        {"value": "retry", "label": "Try that step again"},
                        {"value": "skip", "label": "Skip it for now",
                         "hint": "you can finish it later from My Info"},
                        {"value": "quit", "label": "Quit setup"},
                    ],
                    allow_back=False,
                )
            except Aborted:
                return 130
            if choice == "retry":
                continue
            if choice == "quit":
                return 1
        index += 1

    return 0


def _ensure_schema() -> None:
    """Create/upgrade the schema on the resolved DSN. Never fatal — if the saved DSN
    points at a Postgres container that is down, fall back to SQLite so setup can run
    and the storage step can re-provision."""
    from core import db

    try:
        db.init_db()
        return
    except Exception as exc:  # noqa: BLE001
        theme.warn(f"Saved database unreachable ({exc}); using the local SQLite file.")

    try:
        url = db.sqlite_url()
        db.save_url(url, backend="sqlite", container="")
        db.dispose()
        db.init_db(url)
    except Exception as exc:  # noqa: BLE001
        theme.error(f"Could not prepare a database: {exc}")


def _headless() -> int:
    """Non-interactive setup: create the data dir, a database, and — on a fresh
    instance — a first account with a generated password (printed once, since there's
    no prompt to ask for one). Nothing else here asks."""
    import secrets as pysecrets

    from core import db
    from core.infra import docker
    from core.paths import jobpilot_dir
    from core.repo import settings as settings_repo
    from core.repo import users as users_repo

    print(f"==> JobPilot setup (non-interactive) — {jobpilot_dir()}")
    result = docker.provision()
    print(f"==> Database: {result['backend']} — {result['message']}")

    user_id: int | None = None
    if users_repo.count() == 0:
        password = pysecrets.token_urlsafe(12)
        user = users_repo.create(username="admin", password=password, is_admin=True)
        user_id = user["id"]
        print(f"==> Created account 'admin' with a generated password: {password}")
        print("    Log in and change it from My Info.")
    elif users_repo.find_legacy() is not None:
        print("==> An upgraded legacy account is waiting to be claimed — run "
              "`jobpilot setup` interactively (or use the web login) to finish.")
    else:
        print("==> This instance already has an account configured.")

    if user_id is not None:
        from core import migrate_v1
        if migrate_v1.has_v1_state() and not migrate_v1.already_migrated():
            report = migrate_v1.migrate(user_id)
            print(f"==> Imported v1 state: {report['counts']}")
        settings_repo.export_preferences(user_id)

    ok, detail = db.ping()
    print(f"==> Database check: {'ok' if ok else 'FAILED'} — {detail}")
    print("==> Run `jobpilot start` and finish setup in the browser.")
    return 0 if ok else 1
