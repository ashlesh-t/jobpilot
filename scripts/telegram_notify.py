"""Telegram notifier — thin HTTP wrapper.

Claude builds the digest text in the job-search skill and passes it via --digest.
This script only handles the actual Telegram API calls.

Usage:
  python3 telegram_notify.py --digest "text" [--xlsx /path/to/report.xlsx]
  python3 telegram_notify.py --test
  python3 telegram_notify.py --credit-alert --slots '[1,2]'
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets import get_secret, get_secret_optional  # noqa: E402

import requests

IST = timezone(timedelta(hours=5, minutes=30))
DIVIDER = "─" * 40


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def _bot_token() -> str:
    return get_secret("TELEGRAM_BOT_TOKEN")


def _chat_id() -> str:
    return get_secret("TELEGRAM_CHAT_ID")


def api(method: str) -> str:
    return f"https://api.telegram.org/bot{_bot_token()}/{method}"


def slot_now() -> str:
    hour = datetime.now(IST).hour
    return "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"


def latest_report() -> Path | None:
    """Newest report in reports/ — prefer .xlsx, fall back to .csv."""
    reports = jobpilot_dir() / "reports"
    files = sorted(
        [*reports.glob("*.xlsx"), *reports.glob("*.csv")],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    return files[0] if files else None


# --------------------------------------------------------------------------- #
# Core send helpers
# --------------------------------------------------------------------------- #

def send_message(text: str) -> None:
    requests.post(
        api("sendMessage"),
        data={"chat_id": _chat_id(), "text": text, "disable_web_page_preview": True},
        timeout=30,
    ).raise_for_status()


def send_message_get_id(text: str) -> int | None:
    """Send a message and return the Telegram message_id (for later deletion)."""
    resp = requests.post(
        api("sendMessage"),
        data={"chat_id": _chat_id(), "text": text, "disable_web_page_preview": True},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("result", {}).get("message_id")


def delete_message(message_id: int) -> None:
    """Delete a previously sent message from the chat (e.g. after reading a token)."""
    try:
        requests.post(
            api("deleteMessage"),
            data={"chat_id": _chat_id(), "message_id": message_id},
            timeout=10,
        )
    except Exception:
        pass  # Best-effort — message may already be gone


def send_document(file_path: Path, caption: str = "") -> None:
    data: dict = {"chat_id": _chat_id()}
    if caption:
        data["caption"] = caption
    with file_path.open("rb") as fh:
        requests.post(
            api("sendDocument"),
            data=data,
            files={"document": (file_path.name, fh)},
            timeout=60,
        ).raise_for_status()


# --------------------------------------------------------------------------- #
# Operational alerts
# --------------------------------------------------------------------------- #

def send_credit_alert(exhausted_slots: list[int]) -> None:
    """⛔ Send alert when all Apify token slots are exhausted."""
    slots_str = ", ".join(str(s) for s in exhausted_slots)
    text = (
        "⛔⛔⛔ JOBPILOT — APIFY CREDIT EXHAUSTED ⛔⛔⛔\n\n"
        f"Slots tried: [{slots_str}]. All tokens are out of credits or invalid.\n\n"
        "Quick actions (pick one):\n\n"
        "  A) Create a NEW free Apify account:\n"
        "     → https://apify.com/sign-up  (different email)\n"
        "     → Settings → Integrations → copy API token\n"
        "     → Run in terminal:\n"
        "       python3 scripts/apify_token_update.py --slot 2\n\n"
        "  B) Top up credits on existing account:\n"
        "     → https://console.apify.com/billing\n"
        "     → Run:\n"
        "       python3 scripts/apify_token_update.py --slot 1\n\n"
        "  C) Subscribe to Apify Starter ($49/mo, unlimited scraping)\n\n"
        f"{DIVIDER}\n"
        "Until fixed, pipeline runs NATIVE-ONLY:\n"
        "Internshala, RemoteOK, LinkedIn guest, Telegram channels, HN.\n"
        "No action needed — it keeps running automatically."
    )
    try:
        send_message(text)
    except Exception as exc:
        print(f"[telegram] credit alert send failed: {exc}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Digest building
# --------------------------------------------------------------------------- #

def _score(job: dict) -> float:
    return float(job.get("score", job.get("match_score", 0)) or 0)


def _effective(job: dict) -> float:
    return _score(job) * float(job.get("location_weight") or 1.0)


def build_digest(jobs: list, total_found: int, survived_filter: int, tailored_count: int,
                 apify_skipped: bool = False, run_mode: str = "full") -> str:
    date = datetime.now(IST).strftime("%Y-%m-%d")
    mode_label = "native-only" if run_mode == "native" else "full (native + Apify)"
    lines = [f"JobPilot — {date}, {slot_now()} [{mode_label}]", DIVIDER, "Top matches:"]
    top = sorted(jobs, key=_effective, reverse=True)[:5]
    for rank, job in enumerate(top, 1):
        url = str(job.get("application_url", "")).lower()
        apply_type = str(job.get("apply_type", ""))
        is_gform = (
            "google_form" in apply_type
            or "docs.google.com/forms" in url
            or "forms.gle" in url
        )
        salary = job.get("market_salary") or job.get("salary_range") or "?"
        has_jd = job.get("has_jd", True)
        suffix = " [no JD]" if not has_jd else ""
        unverified = " [unverified link]" if job.get("url_suspicious") else ""
        lines.append(
            f"{rank}. {job.get('role', '')}{suffix} @ {job.get('company', '')} "
            f"(Score: {round(_score(job))})"
        )
        lines.append(f"   {salary} | {job.get('location', '')}")
        lines.append(f"   {job.get('application_url', '')}{unverified}")
        if is_gform:
            lines.append("   [Google Form — fill carefully]")
    lines.append("")
    lines.append(
        f"{total_found} found -> {survived_filter} matched -> "
        f"{tailored_count} resumes tailored"
    )
    if run_mode == "native":
        lines.append("⚠️ Native-only run: LinkedIn/Glassdoor/Naukri/Cutshort/Wellfound skipped.")
        lines.append("   Next run will be full (native + Apify).")
    elif apify_skipped:
        lines.append("⚠️ Apify credits exhausted — LinkedIn/Glassdoor/Naukri skipped this run.")
    lines.append("Report + tailored resumes sent via Telegram.")
    lines.append(DIVIDER)
    return "\n".join(lines)


def load_jobs_for_digest() -> list:
    """Top jobs for the digest — prefer the scored file, fall back to filtered."""
    for path in ("/tmp/jobpilot_scored.json", "/tmp/jobpilot_filtered.json"):
        try:
            return json.loads(Path(path).read_text())
        except Exception:
            continue
    return []


def send_tailored_resumes() -> int:
    tailored_dir = jobpilot_dir() / "resumes" / "tailored"
    if not tailored_dir.exists():
        return 0
    count = 0
    for pdf in sorted(tailored_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime):
        try:
            send_document(pdf, caption=f"Tailored resume: {pdf.stem}")
            count += 1
        except Exception as exc:
            print(f"[telegram] failed to send {pdf.name}: {exc}", file=sys.stderr)
    return count


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #

def _arg(flag: str) -> str | None:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main() -> None:
    args = sys.argv[1:]

    if "--test" in args:
        send_message("JobPilot connected")
        print("Sent test message.")
        return

    if "--credit-alert" in args:
        slots_raw = _arg("--slots")
        slots = json.loads(slots_raw) if slots_raw else [1]
        send_credit_alert(slots)
        print(f"[telegram] credit alert sent for slots {slots}")
        return

    digest_override = _arg("--digest")
    report_override = _arg("--report") or _arg("--xlsx") or _arg("--csv")
    apify_skipped = "--apify-skipped" in args
    run_mode = _arg("--run-mode") or "full"

    report_path = Path(os.path.expanduser(report_override)) if report_override else latest_report()
    jobs = load_jobs_for_digest()

    try:
        raw = len(json.loads(Path("/tmp/jobpilot_raw.json").read_text()))
    except Exception:
        raw = len(jobs)
    survived = len(jobs)

    if report_path and report_path.exists():
        try:
            send_document(report_path)
            print(f"[telegram] sent report: {report_path.name}")
        except Exception as exc:
            print(f"[telegram] report send failed: {exc}", file=sys.stderr)

    tailored = send_tailored_resumes()
    if tailored:
        print(f"[telegram] sent {tailored} tailored resume(s)")

    digest = digest_override or build_digest(jobs, raw, survived, tailored, apify_skipped, run_mode)
    try:
        send_message(digest)
        print("[telegram] digest sent")
    except Exception as exc:
        print(f"[telegram] digest send failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
