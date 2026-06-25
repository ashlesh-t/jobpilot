"""Google Drive uploader — manifest approach.

Writes a JSON manifest listing files to upload. The calling Claude skill reads this manifest
and uploads each file via the Google Drive MCP connector (MCP tools cannot be called from
Python directly).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FOLDER_NAME = "JobPilot Reports"
MANIFEST_OUT = "/tmp/jobpilot_drive_manifest.json"


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def collect_files() -> list:
    files = []
    reports = sorted(
        (jobpilot_dir() / "reports").glob("*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if reports:
        files.append(reports[0])
    tailored = jobpilot_dir() / "resumes" / "tailored"
    if tailored.exists():
        files.extend(tailored.glob("*.pdf"))
    return files


def upload_run() -> None:
    files = collect_files()
    manifest = {
        "folder_name": FOLDER_NAME,
        "files": [
            {
                "path": str(p.resolve()),
                "name": p.name,
                "mime": "text/csv" if p.suffix == ".csv" else "application/pdf",
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
