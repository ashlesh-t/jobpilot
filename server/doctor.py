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
    rows += _check_engines()
    rows += _check_notifiers()
    rows.append(_check_apify())
    rows.append(_check_telegram_scraper())

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
