"""Google Drive uploader — DEPRECATED (issue #12).

Drive upload is removed from the pipeline because base64 encoding of files > ~10 KB over the
MCP boundary is truncated, producing invalid payloads that the Drive MCP rejects.

Telegram is now the sole delivery mechanism (XLSX report + tailored resumes).
This file is kept for reference only and is no longer called by the /job-search skill.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FOLDER_NAME = "JobPilot Reports"
MANIFEST_OUT = "/tmp/jobpilot_drive_manifest.json"

MIME_BY_SUFFIX = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def collect_files() -> list:
    files = []
    # Newest report — prefer .xlsx, fall back to .csv.
    reports = sorted(
        [*(jobpilot_dir() / "reports").glob("*.xlsx"),
         *(jobpilot_dir() / "reports").glob("*.csv")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if reports:
        files.append(reports[0])
    tailored = jobpilot_dir() / "resumes" / "tailored"
    if tailored.exists():
        files.extend(sorted(tailored.glob("*.pdf")))
        files.extend(sorted(tailored.glob("*.docx")))
    return files


def upload_run() -> None:
    files = collect_files()
    manifest = {
        "folder_name": FOLDER_NAME,
        "files": [
            {
                "path": str(p.resolve()),
                "name": p.name,
                "mime": MIME_BY_SUFFIX.get(p.suffix.lower(), "application/octet-stream"),
            }
            for p in files
        ],
    }
    Path(MANIFEST_OUT).write_text(json.dumps(manifest, indent=2))
    print(f"[drive] Manifest written: {len(files)} files -> {MANIFEST_OUT}")


def main() -> None:
    if "--test" in sys.argv:
        test = Path("/tmp/jobpilot_drive_test.txt")
        test.write_text("JobPilot Drive connectivity test")
        manifest = {
            "folder_name": FOLDER_NAME,
            "files": [{"path": str(test), "name": test.name, "mime": "text/plain"}],
        }
        Path(MANIFEST_OUT).write_text(json.dumps(manifest, indent=2))
        print(f"[drive] Test manifest written -> {MANIFEST_OUT}")
    else:
        upload_run()


if __name__ == "__main__":
    main()
