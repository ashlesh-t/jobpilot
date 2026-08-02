"""Doctor — health checks for engines, notifiers, secrets, and job sources.

Two depths:
  * quick (default): configuration/availability only — fast, no network scraping.
  * live (?live=true): additionally runs each native scraper with a tiny cap and a
    per-source timeout so the user can tell "source is dead" from "filter ate everything".

Returns a list of {name, category, status: ok|warn|fail, detail} rows the UI renders as a
✅/⚠️/❌ table.
"""
from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

from common import REPO_DIR, jobpilot_dir, load_prefs  # noqa: E402

sys.path.insert(0, str(REPO_DIR / "scripts"))
sys.path.insert(0, str(REPO_DIR / "scripts" / "scrapers"))

# Native sources to probe in live mode: (module, callable-args)
_NATIVE_SOURCES = [
    ("remoteok", {}),
    ("remotive", {}),
    ("weworkremotely", {}),
    ("arbeitnow", {}),
    ("jobicy", {}),
    ("internshala", {"location": "Bengaluru"}),
    ("hasjob", {}),
    ("yc_startup", {}),
]


def _row(name, category, status, detail=""):
    return {"name": name, "category": category, "status": status, "detail": detail}


def _check_engines() -> list[dict]:
    import engines  # noqa
    rows = []
    for info in engines.list_engines():
        status = "ok" if info["available"] else "warn"
        rows.append(_row(info["label"], "engine", status,
                         info["reason"] or ("metered" if info["metered"] else "ready")))
    return rows


def _check_backend(live: bool) -> list[dict]:
    """The selected agent backend, with a real authentication probe in live mode.

    In quick mode this only reports installation — verifying a Claude Code login costs
    a full round trip, which is too slow for a page load.
    """
    from core import backends  # noqa

    try:
        chosen = backends.selected()
        info = backends.probe(chosen, deep=live)
    except Exception as exc:  # noqa: BLE001
        return [_row("Agent backend", "engine", "fail", str(exc)[:160])]

    if info.ready:
        status = "ok"
    elif info.found:
        status = "warn"
    else:
        status = "fail"
    detail = info.detail or ""
    if not info.ready and info.auth_hint:
        detail = f"{detail} — {info.auth_hint}".strip(" —")
    return [_row(f"Backend: {info.label}", "engine", status, detail)]


def _check_database() -> list[dict]:
    from core import db  # noqa
    from core.infra import docker  # noqa

    rows = []
    ok, detail = db.ping()
    rows.append(_row("Database", "storage", "ok" if ok else "fail", detail))

    st = docker.status()
    if not st.installed:
        rows.append(_row("Docker", "storage", "warn",
                         "not installed — JobPilot is using SQLite (fully supported)"))
    elif not st.running:
        rows.append(_row("Docker", "storage", "warn", st.detail))
    elif st.container_running:
        rows.append(_row("Docker", "storage", "ok",
                         f"{docker.CONTAINER} running on port {st.port}"))
    else:
        rows.append(_row("Docker", "storage", "warn", st.detail))
    return rows


def _check_profile_and_resume() -> list[dict]:
    from core.repo import profiles, resumes  # noqa

    rows = []
    active = resumes.active()
    if active is None:
        rows.append(_row("Active resume", "profile", "fail",
                         "no resume uploaded — add one on the Job Hunt page"))
    elif active["missing"]:
        rows.append(_row("Active resume", "profile", "fail",
                         f"file missing on disk: {active['path']}"))
    else:
        rows.append(_row("Active resume", "profile", "ok",
                         f"{active['folder']}/{active['filename']}"))

    profile = profiles.current()
    if profile is None:
        rows.append(_row("Profile", "profile", "fail", "not built yet — run setup"))
    elif not profile.get("profile_verified"):
        rows.append(_row("Profile", "profile", "warn",
                         "extracted but not confirmed — review it to enable scoring"))
    else:
        rows.append(_row("Profile", "profile", "ok",
                         f"verified for {profile.get('name') or 'you'}"))
    return rows


def _check_tectonic() -> dict:
    import shutil

    if shutil.which("tectonic"):
        return _row("LaTeX (tectonic)", "tailoring", "ok", "PDF tailoring available")
    return _row("LaTeX (tectonic)", "tailoring", "warn",
                "not installed — resume tailoring falls back to DOCX")


def _check_notifiers() -> list[dict]:
    import notify  # noqa
    rows = []
    for info in notify.list_notifiers():
        status = "ok" if info["available"] else "warn"
        rows.append(_row(info["label"], "notify", status, info["reason"] or "ready"))
    return rows


def _check_apify() -> dict:
    from jp_secrets import get_secret_optional  # noqa
    token = get_secret_optional("APIFY_TOKEN")
    if not token:
        return _row("Apify", "paid-sources", "warn", "APIFY_TOKEN not set — native-only runs")
    try:
        import requests  # noqa
        r = requests.get("https://api.apify.com/v2/users/me",
                         params={"token": token}, timeout=8)
        if r.status_code == 200:
            return _row("Apify", "paid-sources", "ok", "token valid")
        return _row("Apify", "paid-sources", "fail", f"token check HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        return _row("Apify", "paid-sources", "warn", f"could not verify: {exc}")


def _check_telegram_scraper() -> dict:
    session = jobpilot_dir() / "cache" / "telegram.session"
    from jp_secrets import get_secret_optional  # noqa
    creds = bool(get_secret_optional("TELEGRAM_API_ID") and
                 get_secret_optional("TELEGRAM_API_HASH"))
    if session.exists():
        return _row("Telegram channels", "source", "ok", "session present")
    if creds:
        return _row("Telegram channels", "source", "warn",
                    "API creds set but not authenticated — run the Connections wizard")
    return _row("Telegram channels", "source", "warn", "not configured (optional)")


def _run_source(mod_name: str, extra: dict) -> dict:
    """Run one native scraper with a tiny cap and a hard timeout."""
    def _call():
        mod = __import__(mod_name)
        return mod.fetch(keywords="software engineer backend",
                         max_results=3, focus="india", **extra)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_call)
            jobs = fut.result(timeout=25)
        n = len(jobs or [])
        if n > 0:
            return _row(mod_name, "source", "ok", f"{n} sample jobs")
        return _row(mod_name, "source", "warn", "0 jobs (may be keyword/time window)")
    except concurrent.futures.TimeoutError:
        return _row(mod_name, "source", "fail", "timed out (>25s)")
    except Exception as exc:  # noqa: BLE001
        return _row(mod_name, "source", "fail", str(exc)[:120])


def run_doctor(live: bool = False) -> dict:
    rows: list[dict] = []
    # One failing check must never blank the whole table — that's precisely when the
    # user needs the other rows most.
    for label, check in (
        ("Agent backend", lambda: _check_backend(live)),
        ("Database", _check_database),
        ("Profile", _check_profile_and_resume),
        ("Engines", _check_engines),
        ("Notifiers", _check_notifiers),
        ("Apify", lambda: [_check_apify()]),
        ("LaTeX", lambda: [_check_tectonic()]),
        ("Telegram channels", lambda: [_check_telegram_scraper()]),
    ):
        try:
            rows += check()
        except Exception as exc:  # noqa: BLE001
            rows.append(_row(label, "check", "fail", f"check itself failed: {exc}"[:200]))

    if live:
        disabled = set()
        try:
            import json
            actors = json.loads((REPO_DIR / "config" / "actors.json").read_text())
            disabled = set(actors.get("disabled_native_sources", []))
        except Exception:
            pass
        for mod_name, extra in _NATIVE_SOURCES:
            if mod_name in disabled:
                rows.append(_row(mod_name, "source", "warn", "disabled in actors.json"))
                continue
            rows.append(_run_source(mod_name, extra))

    summary = {
        "ok": sum(1 for r in rows if r["status"] == "ok"),
        "warn": sum(1 for r in rows if r["status"] == "warn"),
        "fail": sum(1 for r in rows if r["status"] == "fail"),
    }
    return {"rows": rows, "summary": summary, "live": live}
