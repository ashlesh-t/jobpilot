"""Telegram notifier — thin HTTP wrapper.

Claude builds the digest text in the job-search skill and passes it via --digest.
This script only handles the actual Telegram API calls.

Usage:
  python3 telegram_notify.py --digest "text" --csv /path/to/report.csv
  python3 telegram_notify.py --test
"""
from __future__ import annotations

from datetime import datetime
import os
import sys
from pathlib import Path

from scripts.report_generator import IST

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets import get_secret  # noqa: E402

import requests


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def api(method: str) -> str:
    token = get_secret("TELEGRAM_BOT_TOKEN")
    return f"https://api.telegram.org/bot{token}/{method}"


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


def send_document(path: Path) -> None:
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    with path.open("rb") as fh:
        requests.post(
            api("sendDocument"),
            data={"chat_id": chat_id},
            files={"document": (path.name, fh)},
            timeout=60,
        )


def send_message(text: str) -> None:
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    requests.post(
        api("sendMessage"),
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=30,
    ).raise_for_status()


def send_document(file_path: Path, caption: str = "") -> None:
    chat_id = get_secret("TELEGRAM_CHAT_ID")
    with file_path.open("rb") as fh:
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        requests.post(
            api("sendDocument"),
            data=data,
            files={"document": (file_path.name, fh)},
            timeout=60,
        ).raise_for_status()
def _score(job: dict):
    return job.get("score", job.get("match_score", 0)) or 0


def _effective(job: dict):
    return _score(job) * (job.get("location_weight") or 1.0)


def build_digest(jobs: list, total_found: int, survived_filter: int, tailored_count: int,
                 apify_skipped: bool = False) -> str:
    date = datetime.now(IST).strftime("%Y-%m-%d")
    lines = [f"🎯 JobPilot — {date}, {slot_now()}", DIVIDER, "🏆 Top matches:"]
    top = sorted(jobs, key=_effective, reverse=True)[:3]
    for rank, job in enumerate(top, 1):
        apply_type = str(job.get("apply_type", job.get("apply_url_type", "")))
        url = str(job.get("application_url", "")).lower()
        is_gform = (apply_type.startswith("⚠️") or "google_form" in apply_type
                    or "docs.google.com/forms" in url or "forms.gle" in url)
        salary = job.get("market_salary") or job.get("est_package_range") or "?"
        lines.append(
            f"{rank}. {job.get('role', '')} @ {job.get('company', '')} "
            f"(Score: {round(_score(job))})"
        )
        lines.append(f"   💰 {salary} | 📍 {job.get('location', '')}")
        lines.append(f"   🔗 {job.get('application_url', '')}")
        if is_gform:
            lines.append("   ⚠️ Google Form — fill carefully!")
    lines.append("")
    lines.append(
        f"📊 {total_found} found → {survived_filter} matched → "
        f"{tailored_count} resumes tailored"
    )
    if apify_skipped:
        lines.append("⚠️ LinkedIn/Glassdoor/Naukri skipped — Apify credits exhausted.")
    lines.append("Report + tailored resumes uploaded to Drive.")
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


def main() -> None:
    args = sys.argv[1:]

    if "--test" in args:
        send_message("JobPilot connected ✅")
        print("Sent test message: JobPilot connected ✅")
        return

    digest = ""
    csv_path = None

    if "--digest" in args:
        idx = args.index("--digest")
        if idx + 1 < len(args):
            digest = args[idx + 1]

    if "--csv" in args:
        idx = args.index("--csv")
        if idx + 1 < len(args):
            csv_path = Path(args[idx + 1])

    if csv_path and csv_path.is_file():
        try:
            send_document(csv_path)
            print(f"[telegram] sent CSV: {csv_path.name}")
        except Exception as exc:
            print(f"[telegram] CSV send failed: {exc}", file=sys.stderr)

    tailored = send_tailored_resumes()
    if tailored:
        print(f"[telegram] sent {tailored} tailored resume(s)")

    if digest:
        try:
            send_message(digest)
            print("[telegram] digest sent")
        except Exception as exc:
            print(f"[telegram] digest send failed: {exc}", file=sys.stderr)
    elif not csv_path:
        print("usage: python3 telegram_notify.py --digest 'text' [--csv path]", file=sys.stderr)
        print("       python3 telegram_notify.py --test", file=sys.stderr)
def _arg(flag: str) -> str | None:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main_send() -> None:
    # Optional overrides from the skill: --digest "text", --report/--xlsx/--csv <path>
    digest_override = _arg("--digest")
    report_override = _arg("--report") or _arg("--xlsx") or _arg("--csv")
    apify_skipped = "--apify-skipped" in sys.argv

    report_path = Path(os.path.expanduser(report_override)) if report_override else latest_report()
    jobs = load_jobs_for_digest()
    try:
        raw = len(json.loads(Path("/tmp/jobpilot_raw.json").read_text()))
    except Exception:
        raw = len(jobs)
    survived = len(jobs)

    if report_path and report_path.exists():
        send_document(report_path)
    tailored = send_tailored_resumes()
    digest = digest_override or build_digest(jobs, raw, survived, tailored, apify_skipped)
    send_message(digest)


if __name__ == "__main__":
    main()
