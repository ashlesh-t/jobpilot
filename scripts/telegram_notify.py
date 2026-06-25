"""Telegram notifier.

Sends two calls: sendDocument (the CSV) and sendMessage (a formatted digest of the top 3).
Tokens come from secrets.py. Run directly to send a connectivity test message.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets import get_secret  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
DIVIDER = "━━━━━━━━━━━━━━━━━━━━"


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def api(method: str) -> str:
    token = get_secret("TELEGRAM_BOT_TOKEN")
    return f"https://api.telegram.org/bot{token}/{method}"


def slot_now() -> str:
    hour = datetime.now(IST).hour
    return "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"


def latest_csv() -> Path | None:
    reports = jobpilot_dir() / "reports"
    files = sorted(reports.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def send_document(csv_path: Path) -> None:
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    with csv_path.open("rb") as fh:
        requests.post(
            api("sendDocument"),
            data={"chat_id": chat_id},
            files={"document": (csv_path.name, fh)},
            timeout=60,
        )


def send_message(text: str) -> None:
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    requests.post(
        api("sendMessage"),
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=30,
    )


def build_digest(jobs: list, total_found: int, survived_filter: int, tailored_count: int) -> str:
    date = datetime.now(IST).strftime("%Y-%m-%d")
    lines = [f"🎯 JobPilot — {date}, {slot_now()}", DIVIDER, "🏆 Top matches:"]
    top = sorted(jobs, key=lambda j: j.get("match_score", 0) or 0, reverse=True)[:3]
    for rank, job in enumerate(top, 1):
        is_gform = str(job.get("apply_url_type", "")).startswith("⚠️") or \
            job.get("apply_url_type") == "google_form"
        lines.append(
            f"{rank}. {job.get('role', '')} @ {job.get('company', '')} "
            f"(Score: {job.get('match_score', 0)})"
        )
        lines.append(
            f"   💰 {job.get('est_package_range', '?')} LPA | 📍 {job.get('location', '')}"
        )
        lines.append(f"   🔗 {job.get('application_url', '')}")
        if is_gform:
            lines.append("   ⚠️ Google Form — fill carefully!")
    lines.append("")
    lines.append(
        f"📊 {total_found} found → {survived_filter} matched → "
        f"{tailored_count} resumes tailored"
    )
    lines.append("CSV + tailored resumes uploaded to Drive.")
    lines.append(DIVIDER)
    return "\n".join(lines)


def load_jobs_for_digest() -> list:
    """Pull top jobs from the filtered file enriched with scores (best-effort)."""
    try:
        jobs = json.loads(Path("/tmp/jobpilot_filtered.json").read_text())
    except Exception:
        return []
    return jobs


def send_tailored_resumes() -> int:
    """Send each tailored PDF via sendDocument. Returns count successfully sent."""
    tailored_dir = jobpilot_dir() / "resumes" / "tailored"
    if not tailored_dir.exists():
        return 0
    pdfs = sorted(tailored_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime)
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    count = 0
    for pdf in pdfs:
        try:
            with pdf.open("rb") as fh:
                resp = requests.post(
                    api("sendDocument"),
                    data={"chat_id": chat_id, "caption": f"Tailored resume: {pdf.stem}"},
                    files={"document": (pdf.name, fh)},
                    timeout=60,
                )
                resp.raise_for_status()
                count += 1
        except Exception as exc:
            print(f"[telegram] failed to send {pdf.name}: {exc}", file=sys.stderr)
    return count


def main_send() -> None:
    csv_path = latest_csv()
    jobs = load_jobs_for_digest()
    try:
        raw = len(json.loads(Path("/tmp/jobpilot_raw.json").read_text()))
    except Exception:
        raw = len(jobs)
    survived = len(jobs)

    if csv_path:
        send_document(csv_path)
    tailored = send_tailored_resumes()
    send_message(build_digest(jobs, raw, survived, tailored))


if __name__ == "__main__":
    if "--test" in sys.argv:
        send_message("JobPilot connected ✅")
        print("Sent test message: JobPilot connected ✅")
    else:
        main_send()
        print("Digest sent.")
