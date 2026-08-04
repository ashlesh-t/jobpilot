"""The individual steps of `jobpilot setup`.

Each step is a function that takes the shared context, does its work, persists what it
learned immediately, and returns. Raising `GoBack` returns to the previous step; every
step is safe to re-enter, because none of them assume a blank slate.
"""
from __future__ import annotations

import re
import time

from . import prompts, theme
from .prompts import GoBack

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BOTFATHER_URL = "https://t.me/BotFather"
APIFY_TOKEN_URL = "https://console.apify.com/settings/integrations"
ANTHROPIC_KEYS_URL = "https://console.anthropic.com/settings/keys"
ADZUNA_SIGNUP_URL = "https://developer.adzuna.com/signup"
ADZUNA_DASHBOARD_URL = "https://developer.adzuna.com/admin/"


def _validate_email(value: str) -> str | None:
    return None if EMAIL_RE.match(value) else "That doesn't look like an email address."


# --------------------------------------------------------------------------- #
# 1 — Identity
# --------------------------------------------------------------------------- #
def step_identity(ctx: dict) -> None:
    from core.repo import settings as settings_repo

    theme.step_header(1, 6, "About you",
                      "Used on your tailored resumes and in the digest greeting.")
    prefs = settings_repo.preferences()

    name = prompts.ask_text("Your full name", default=prefs.get("name", ""),
                            allow_empty=False, allow_back=False,
                            help_text="as it should appear on your resume")
    email = prompts.ask_text("Your email", default=prefs.get("email", ""),
                             allow_empty=True, validate=_validate_email,
                             help_text="optional")

    settings_repo.update_preferences({"name": name, "email": email})
    ctx["name"] = name
    theme.success(f"Hi {name.split()[0]} — saved.")
    theme.out()


# --------------------------------------------------------------------------- #
# 2 — Storage
# --------------------------------------------------------------------------- #
def step_database(ctx: dict) -> None:
    from core import db
    from core.infra import docker
    from core.paths import jobpilot_dir

    theme.step_header(2, 6, "Storage",
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

    _run_v1_migration()
    theme.out()


def _run_v1_migration() -> None:
    """Import JobPilot v1 state if this machine has any. Silent when there's nothing."""
    from core import migrate_v1

    if migrate_v1.already_migrated() or not migrate_v1.has_v1_state():
        return
    theme.info("Found data from an earlier JobPilot version.")
    if not prompts.ask_confirm("Import it (jobs, profile, preferences, history)?",
                               default=True):
        return
    with theme.spinner("Importing…"):
        report = migrate_v1.migrate()
    counts = report.get("counts", {})
    moved = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
    theme.success(f"Imported {moved or 'nothing new'}. Your old files were left untouched.")
    for err in report.get("errors", [])[:3]:
        theme.warn(err)


# --------------------------------------------------------------------------- #
# 3 — Agent backend
# --------------------------------------------------------------------------- #
def step_backend(ctx: dict) -> None:
    from core import backends, secrets

    theme.step_header(3, 6, "AI backend",
                      "JobPilot needs an AI agent to read job descriptions, score them "
                      "and tailor your resume.")

    with theme.spinner("Looking for installed agents…"):
        probes = {b["id"]: b for b in backends.probe_all()}

    rows = []
    for bid in backends.PRIORITY:
        b = probes[bid]
        status = "ok" if b["ready"] else ("warn" if b["found"] else "skip")
        rows.append((b["label"], status, b["detail"]))
    theme.summary_table(rows)
    theme.out()

    choices = []
    for bid in backends.PRIORITY:
        b = probes[bid]
        hint = "ready" if b["ready"] else ("needs setup" if b["found"] else "not installed")
        if b.get("experimental"):
            hint += " · experimental"
        choices.append({"value": bid, "label": b["label"], "hint": hint})

    default = backends.best_available() or "claude_code"
    chosen = prompts.ask_select("Which one should JobPilot use?", choices, default=default)

    if chosen == "claude_code":
        _setup_claude_code(probes["claude_code"])
    elif chosen == "claude_api":
        _setup_claude_api(secrets)
    elif chosen == "gemini":
        _setup_gemini(secrets, probes["gemini"])
    else:
        _setup_generic_cli()

    backends.select(chosen)
    ctx["backend"] = chosen
    theme.out()


def _setup_claude_code(info: dict) -> None:
    from core import backends

    if not info["found"]:
        theme.warn("The Claude Code CLI isn't installed.")
        theme.info(f"Install it with:  {backends.CLAUDE_NPM}")
        theme.info(f"Or download it:   {backends.CLAUDE_INSTALL_URL}")
        if prompts.ask_confirm("Install it now with npm?", default=True):
            with theme.spinner("Installing @anthropic-ai/claude-code…"):
                ok, message = backends.install_claude_code()
            (theme.success if ok else theme.error)(message)
            if not ok:
                return
        else:
            theme.info("Install it, then re-run `jobpilot setup`.")
            return

    theme.info("Verifying your Claude login (this makes one small request)…")
    with theme.spinner("Checking…"):
        result = backends.probe("claude_code", deep=True)
    if result.authenticated:
        theme.success(f"Signed in — {result.detail}")
        return

    theme.warn(result.detail)
    theme.info("Run `claude login` in another terminal, then come back here.")
    if prompts.ask_confirm("Re-check now?", default=True):
        with theme.spinner("Checking…"):
            result = backends.probe("claude_code", deep=True)
        if result.authenticated:
            theme.success("Signed in.")
        else:
            theme.warn("Still not signed in — you can fix this later from My Info.")


def _setup_claude_api(secrets) -> None:
    from core import backends

    if secrets.has("ANTHROPIC_API_KEY"):
        theme.success(f"Existing key found: {secrets.mask(secrets.get('ANTHROPIC_API_KEY'))}")
        if not prompts.ask_confirm("Replace it?", default=False):
            return
    theme.info(f"Create a key at {ANTHROPIC_KEYS_URL}")
    theme.qr(ANTHROPIC_KEYS_URL)
    key = prompts.ask_secret("Paste your Anthropic API key")
    with theme.spinner("Verifying the key…"):
        ok, why = backends._anthropic_key_probe(key)
    if ok:
        secrets.set("ANTHROPIC_API_KEY", key)
        theme.success("Key verified and stored in your system keyring.")
    else:
        theme.error(why)
        if prompts.ask_confirm("Save it anyway?", default=False):
            secrets.set("ANTHROPIC_API_KEY", key)
            theme.warn("Saved unverified — check it later from My Info.")


def _setup_gemini(secrets, info: dict) -> None:
    theme.warn("The Gemini backend is experimental — Claude is the tested path.")
    if info["extras"].get("cli"):
        theme.success(f"Found the {info['extras']['cli']} CLI.")
    key = prompts.ask_secret("Gemini API key (leave blank to use the CLI's own login)",
                             allow_empty=True)
    if key:
        secrets.set("GEMINI_API_KEY", key)
        theme.success("Key stored.")


def _setup_generic_cli() -> None:
    from core.repo import settings as settings_repo

    theme.warn("Custom backends are experimental — JobPilot can't know your tool's "
               "output format, so progress narration may be sparse.")
    theme.info("Use {prompt} where the task text should go, e.g.  mytool run --prompt {prompt}")
    template = prompts.ask_text("Command template", allow_empty=False,
                                validate=lambda v: None if "{prompt}" in v
                                else "The template must contain {prompt}.")
    cfg = settings_repo.engine_config()
    cfg["command_template"] = template
    settings_repo.set("engine", cfg)
    theme.success("Template saved.")


# --------------------------------------------------------------------------- #
# 4 — Apify (optional)
# --------------------------------------------------------------------------- #
def step_apify(ctx: dict) -> None:
    from core import secrets

    theme.step_header(4, 6, "Extra job sources (optional)",
                      "JobPilot already scrapes ~8 sources for free. An Apify token "
                      "adds LinkedIn, Naukri, Glassdoor and Indeed; Adzuna adds another "
                      "free source on top of the built-in scrapers.")

    _setup_apify(secrets)
    _setup_adzuna(secrets)
    theme.out()


def _setup_apify(secrets) -> None:
    if secrets.has("APIFY_TOKEN"):
        theme.success(f"Existing Apify token: {secrets.mask(secrets.get('APIFY_TOKEN'))}")
        if not prompts.ask_confirm("Replace it?", default=False):
            return

    if not prompts.ask_confirm("Add an Apify token now?", default=False):
        theme.info("Skipped — you can add one any time from My Info.")
        return

    theme.info(f"Get a free token at {APIFY_TOKEN_URL}")
    theme.qr(APIFY_TOKEN_URL)
    token = prompts.ask_secret("Paste your Apify token", allow_empty=True)
    if not token:
        theme.info("Skipped.")
        return

    with theme.spinner("Verifying the token…"):
        ok, detail = _verify_apify(token)
    if ok:
        secrets.set("APIFY_TOKEN", token)
        theme.success(f"Verified — signed in as {detail}.")
    else:
        theme.error(detail)
        if prompts.ask_confirm("Save it anyway?", default=False):
            secrets.set("APIFY_TOKEN", token)


def _setup_adzuna(secrets) -> None:
    if secrets.has("ADZUNA_APP_ID") and secrets.has("ADZUNA_APP_KEY"):
        theme.success("Adzuna already connected.")
        if not prompts.ask_confirm("Replace it?", default=False):
            return

    if not prompts.ask_confirm("Add Adzuna (another free job source) now?", default=False):
        theme.info("Skipped — you can add it any time from My Info.")
        return

    theme.panel(
        f"1. Register for free at [bold]{ADZUNA_SIGNUP_URL}[/bold] — no card needed\n"
        f"2. Your App ID and App Key are both shown at [bold]{ADZUNA_DASHBOARD_URL}[/bold]\n"
        "3. Paste each one below\n\n"
        "[dim]Free tier is 1,000 calls/month — plenty for a couple of runs a day.[/dim]",
        title="Get Adzuna credentials",
    )
    theme.qr(ADZUNA_SIGNUP_URL)

    app_id = prompts.ask_secret("Paste your Adzuna App ID", allow_empty=True)
    if not app_id:
        theme.info("Skipped.")
        return
    app_key = prompts.ask_secret("Paste your Adzuna App Key", allow_empty=True)
    if not app_key:
        theme.info("Skipped.")
        return

    with theme.spinner("Verifying the credentials…"):
        ok, detail = _verify_adzuna(app_id, app_key)
    if ok:
        secrets.set("ADZUNA_APP_ID", app_id)
        secrets.set("ADZUNA_APP_KEY", app_key)
        theme.success("Verified and stored.")
    else:
        theme.error(detail)
        if prompts.ask_confirm("Save it anyway?", default=False):
            secrets.set("ADZUNA_APP_ID", app_id)
            secrets.set("ADZUNA_APP_KEY", app_key)


def _verify_adzuna(app_id: str, app_key: str) -> tuple[bool, str]:
    try:
        import requests
        r = requests.get(
            "https://api.adzuna.com/v1/api/jobs/gb/search/1",
            params={"app_id": app_id, "app_key": app_key, "results_per_page": 1,
                    "content-type": "application/json"},
            timeout=10)
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not reach Adzuna: {exc}"
    if r.status_code == 200:
        return True, "credentials valid"
    if r.status_code in (401, 403):
        return False, "Adzuna rejected that App ID/App Key pair — check both were copied in full."
    return False, f"Adzuna returned HTTP {r.status_code}."


def _verify_apify(token: str) -> tuple[bool, str]:
    try:
        import requests
        r = requests.get("https://api.apify.com/v2/users/me",
                         params={"token": token}, timeout=10)
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not reach Apify: {exc}"
    if r.status_code == 200:
        try:
            return True, r.json()["data"].get("username", "your account")
        except Exception:  # noqa: BLE001
            return True, "your account"
    if r.status_code in (401, 403):
        return False, "Apify rejected that token — check it was copied in full."
    return False, f"Apify returned HTTP {r.status_code}."


# --------------------------------------------------------------------------- #
# 5 — Notifications
# --------------------------------------------------------------------------- #
def step_notifications(ctx: dict) -> None:
    from core import secrets
    from core.repo import settings as settings_repo

    theme.step_header(5, 6, "Where should results go?",
                      "Every run sends a digest, the full spreadsheet, and any tailored "
                      "resumes. You can always read them in the web UI too.")

    channels: list[str] = []
    if _setup_telegram(secrets):
        channels.append("telegram")
    if _setup_discord(secrets):
        channels.append("discord")

    if not channels:
        theme.info("No delivery channel configured — results will only appear in the "
                   "web UI. You can add one later from My Info.")
    settings_repo.update_preferences({"notify_channels": channels})
    theme.out()


def _setup_telegram(secrets) -> bool:
    if secrets.has("TELEGRAM_BOT_TOKEN") and secrets.has("TELEGRAM_CHAT_ID"):
        theme.success("Telegram already connected.")
        if not prompts.ask_confirm("Reconnect it?", default=False):
            return True

    if not prompts.ask_confirm("Set up Telegram delivery?", default=True):
        return False

    theme.panel(
        "1. Open [bold]@BotFather[/bold] in Telegram (link or QR below)\n"
        "2. Send [bold]/newbot[/bold] and follow the two prompts\n"
        "3. It replies with [italic]“Use this token to access the HTTP API:”[/italic] "
        "followed by the token\n"
        "4. Paste the [bold]whole token[/bold] here — digits, colon and letters together, "
        "like [bold]123456789:AAH…[/bold]\n\n"
        "[dim]Not just the numbers, not just the letters, and none of the words "
        "around it.[/dim]",
        title="Create your bot",
    )
    theme.info(BOTFATHER_URL)
    theme.qr(BOTFATHER_URL)

    while True:
        token = prompts.ask_secret(
            "Paste the bot token", allow_empty=True,
            help_text="the whole thing, e.g. 123456789:AAH…",
        )
        if not token:
            theme.info("Skipped Telegram.")
            return False
        with theme.spinner("Checking the token…"):
            ok, name = _verify_telegram_bot(token)
        if ok:
            theme.success(f"Connected to @{name}.")
            break
        theme.error(name)
        if not prompts.ask_confirm("Try a different token?", default=True):
            return False

    secrets.set("TELEGRAM_BOT_TOKEN", token)

    chat_id = _capture_chat_id(token, name)
    if not chat_id:
        return False
    secrets.set("TELEGRAM_CHAT_ID", chat_id)

    with theme.spinner("Sending a test message…"):
        sent = _send_telegram_test(token, chat_id)
    if sent:
        theme.success("Test message delivered — check your phone.")
    else:
        theme.warn("Saved, but the test message didn't go through. "
                   "You can retest from My Info.")
    return True


def _capture_chat_id(token: str, bot_name: str) -> str | None:
    """Watch getUpdates until the user messages the bot — no copy-paste needed.

    This replaces the worst part of the v1 wizard, where the user had to fish a numeric
    chat ID out of a raw JSON response.
    """
    bot_url = f"https://t.me/{bot_name}"
    theme.panel(
        f"Open your bot and press [bold]Start[/bold] (or send it any message).\n"
        f"JobPilot will pick up the chat automatically — nothing to copy.\n\n"
        f"{bot_url}",
        title="Link your chat",
    )
    theme.qr(bot_url)

    deadline = time.monotonic() + 180
    with theme.spinner("Waiting for your message… (Ctrl-C to enter the ID manually)"):
        try:
            while time.monotonic() < deadline:
                chat_id = _poll_telegram_chat_id(token)
                if chat_id:
                    break
                time.sleep(2)
            else:
                chat_id = None
        except KeyboardInterrupt:
            chat_id = None

    if chat_id:
        theme.success(f"Linked to chat {chat_id}.")
        return chat_id

    theme.warn("Didn't see a message.")
    manual = prompts.ask_text(
        "Enter your chat ID manually (or leave blank to skip Telegram)",
        allow_empty=True, allow_back=False,
        validate=lambda v: None if v.lstrip("-").isdigit() else "Chat IDs are numeric.")
    return manual or None


def _verify_telegram_bot(token: str) -> tuple[bool, str]:
    try:
        import requests
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not reach Telegram: {exc}"
    if r.status_code == 200 and r.json().get("ok"):
        return True, r.json()["result"].get("username", "your bot")
    return False, "Telegram rejected that token — make sure you copied all of it."


def _poll_telegram_chat_id(token: str) -> str | None:
    try:
        import requests
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                         params={"timeout": 0, "limit": 10}, timeout=10)
        if r.status_code != 200:
            return None
        for update in reversed(r.json().get("result", [])):
            for key in ("message", "edited_message", "channel_post", "my_chat_member"):
                chat = (update.get(key) or {}).get("chat")
                if chat and chat.get("id") is not None:
                    return str(chat["id"])
    except Exception:  # noqa: BLE001
        return None
    return None


def _send_telegram_test(token: str, chat_id: str) -> bool:
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id,
                  "text": "✅ JobPilot is connected. Your job digests will arrive here."},
            timeout=10)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _setup_discord(secrets) -> bool:
    if secrets.has("DISCORD_WEBHOOK_URL"):
        theme.success("Discord already connected.")
        return True
    if not prompts.ask_confirm("Also deliver to Discord?", default=False):
        return False
    theme.info("Channel Settings → Integrations → Webhooks → New Webhook → Copy URL")
    url = prompts.ask_secret("Paste the webhook URL", allow_empty=True)
    if not url:
        return False
    if "discord.com/api/webhooks/" not in url:
        theme.error("That doesn't look like a Discord webhook URL.")
        return False
    secrets.set("DISCORD_WEBHOOK_URL", url)
    theme.success("Discord connected.")
    return True


# --------------------------------------------------------------------------- #
# 6 — Finish
# --------------------------------------------------------------------------- #
def step_finish(ctx: dict) -> None:
    from core.repo import settings as settings_repo

    theme.step_header(6, 6, "All set")
    _offer_tectonic()
    settings_repo.mark_setup_complete(True)
    settings_repo.export_preferences()

    rows = _final_summary()
    theme.summary_table(rows)
    theme.out()
    theme.panel(
        "Start JobPilot and finish the rest in your browser:\n\n"
        "  [bold]jobpilot start[/bold]\n\n"
        "There you'll upload your resume, set your job preferences,\n"
        "pick run times, and launch your first hunt.",
        title="Next step",
    )


def _offer_tectonic() -> None:
    """Tailored resumes compile to PDF only when tectonic is on PATH. Optional."""
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


def _final_summary() -> list[tuple[str, str, str]]:
    from core import backends, secrets
    from core.db import is_sqlite, ping
    from core.repo import settings as settings_repo

    rows: list[tuple[str, str, str]] = []
    prefs = settings_repo.preferences()
    rows.append(("You", "ok", prefs.get("name") or "—"))

    ok, detail = ping()
    rows.append(("Database", "ok" if ok else "fail",
                 ("SQLite" if is_sqlite() else "PostgreSQL") + f" — {detail}"))

    try:
        info = backends.probe(backends.selected())
        rows.append(("AI backend", "ok" if info.found else "warn", info.label))
    except Exception:  # noqa: BLE001
        rows.append(("AI backend", "warn", "not selected"))

    rows.append(("Apify", "ok" if secrets.has("APIFY_TOKEN") else "skip",
                 "extra sources enabled" if secrets.has("APIFY_TOKEN")
                 else "not set — free sources only"))

    has_adzuna = secrets.has("ADZUNA_APP_ID") and secrets.has("ADZUNA_APP_KEY")
    rows.append(("Adzuna", "ok" if has_adzuna else "skip",
                 "enabled" if has_adzuna else "not set — optional"))

    channels = prefs.get("notify_channels") or []
    rows.append(("Delivery", "ok" if channels else "skip",
                 ", ".join(channels) if channels else "web UI only"))

    from core import tailoring
    has_pdf = tailoring.has_tectonic()
    rows.append(("PDF compiler", "ok" if has_pdf else "skip",
                 "tectonic — tailored resumes compile to PDF" if has_pdf
                 else "not installed — tailored resumes stay as LaTeX source"))
    return rows


STEPS = [
    ("You", step_identity),
    ("Storage", step_database),
    ("AI backend", step_backend),
    ("Sources", step_apify),
    ("Delivery", step_notifications),
    ("Done", step_finish),
]
