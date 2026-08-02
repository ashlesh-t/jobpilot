"""Deliver a finished run — Layer A, pure Python, NO LLM.

Builds the digest from the run's scored artifact and sends it, the report spreadsheet,
and any tailored resumes to every channel in `preferences.notify_channels`. Writes a
receipt artifact so the UI can show, per channel, whether delivery actually worked.

    python3 scripts/notify_run.py [--input scored.json] [--report PATH]
                                  [--run-mode full|native] [--digest TEXT]

Never raises: a delivery failure is recorded and reported, not thrown, because the run's
results are already safe on disk and in the database by the time this runs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jp_paths  # noqa: E402


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def _load(path: str, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _prefs() -> dict:
    return _load(str(jobpilot_dir() / "options" / "preferences.json"), {})


def _latest_report() -> Path | None:
    reports = jobpilot_dir() / "reports"
    if not reports.exists():
        return None
    files = sorted([*reports.glob("*.xlsx"), *reports.glob("*.csv")],
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _tailored_documents() -> list[tuple[str, str]]:
    """Resumes tailored during *this* run only — never the whole historical folder."""
    root = jobpilot_dir() / "resumes" / "tailored"
    if not root.exists():
        return []
    run_id = os.environ.get("JOBPILOT_RUN_ID", "")
    cutoff = 0.0
    if run_id:
        run_dir = jp_paths.run_dir()
        if run_dir and run_dir.exists():
            cutoff = run_dir.stat().st_mtime
    docs: list[tuple[str, str]] = []
    for pdf in sorted(root.rglob("*.pdf"), key=lambda p: p.stat().st_mtime):
        if pdf.stat().st_mtime >= cutoff:
            docs.append((str(pdf), f"Tailored resume: {pdf.parent.name}"))
    return docs


def build(jobs: list, counts: dict, run_mode: str) -> str:
    """Digest text. Delegates to telegram_notify so one wording change covers all
    channels; falls back to a minimal summary if that module can't be imported."""
    try:
        import telegram_notify
        return telegram_notify.build_digest(
            jobs,
            total_found=counts.get("raw", 0),
            survived_filter=counts.get("filtered", 0),
            tailored_count=counts.get("tailored", 0),
            apify_skipped=run_mode == "native",
            run_mode=run_mode,
        )
    except Exception:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        top = sorted(jobs, key=lambda j: float(j.get("score") or 0), reverse=True)[:5]
        lines = [f"JobPilot — {date}", f"{len(jobs)} scored jobs", ""]
        for i, job in enumerate(top, 1):
            lines.append(f"{i}. {job.get('role','')} @ {job.get('company','')} "
                         f"({round(float(job.get('score') or 0))})")
            lines.append(f"   {job.get('application_url','')}")
        return "\n".join(lines)


def deliver(digest: str, report: Path | None, documents: list[tuple[str, str]],
            channels: list[str]) -> dict[str, str]:
    """Send to every configured channel. Returns {channel: 'ok' | 'error: …'}."""
    results: dict[str, str] = {}
    docs = list(documents)
    if report and report.exists():
        docs.insert(0, (str(report), f"JobPilot report — {report.name}"))

    if "telegram" in channels:
        try:
            import telegram_notify
            telegram_notify.send_message(digest)
            for path, caption in docs:
                try:
                    telegram_notify.send_document(Path(path), caption=caption)
                except Exception as exc:  # noqa: BLE001
                    print(f"[notify] telegram document {path}: {exc}", file=sys.stderr)
            results["telegram"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["telegram"] = f"error: {exc}"

    others = [c for c in channels if c != "telegram"]
    if others:
        try:
            import notify
            results.update(notify.fan_out(others, digest=digest, documents=docs))
        except Exception as exc:  # noqa: BLE001
            for c in others:
                results[c] = f"error: {exc}"
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deliver a finished JobPilot run")
    ap.add_argument("--input", default=jp_paths.artifact("scored"))
    ap.add_argument("--report", default="", help="report path (defaults to the newest)")
    ap.add_argument("--run-mode", default="full", choices=["full", "native", "auto"])
    ap.add_argument("--digest", default="", help="override the generated digest text")
    args = ap.parse_args(argv)

    jobs = _load(args.input, None)
    if jobs is None:
        jobs = _load(jp_paths.artifact("filtered"), [])
    counts = {
        "raw": len(_load(jp_paths.artifact("raw"), [])),
        "filtered": len(_load(jp_paths.artifact("filtered"), [])),
        "tailored": len(_tailored_documents()),
    }

    channels = _prefs().get("notify_channels") or []
    receipt_path = jp_paths.artifact("notify_receipt")

    if not channels:
        print("[notify] no channels configured — results are in the web UI only")
        Path(receipt_path).write_text(json.dumps(
            {"channels": {}, "skipped": "no channels configured"}, indent=2))
        return 0

    digest = args.digest or build(jobs, counts, args.run_mode)
    report = Path(args.report) if args.report else _latest_report()
    results = deliver(digest, report, _tailored_documents(), channels)

    Path(receipt_path).write_text(json.dumps({
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "channels": results,
        "report": str(report) if report else "",
        "documents": [p for p, _ in _tailored_documents()],
        "digest_preview": digest[:500],
    }, indent=2, ensure_ascii=False))

    for channel, outcome in results.items():
        print(f"[notify] {channel}: {outcome}")
    # Delivery problems are reported, never fatal — the run itself succeeded.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
