"""Telegram notifier — thin HTTP wrapper.

Claude builds the digest text in the job-search skill and passes it via --digest.
This script only handles the actual Telegram API calls.

Usage:
  python3 telegram_notify.py --digest "text" --csv /path/to/report.csv
  python3 telegram_notify.py --test
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets import get_secret  # noqa: E402

import requests


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def api(method: str) -> str:
    token = get_secret("TELEGRAM_BOT_TOKEN")
    return f"https://api.telegram.org/bot{token}/{method}"


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


if __name__ == "__main__":
    main()
