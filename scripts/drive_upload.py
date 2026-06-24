"""Google Drive uploader.

Uploads the run's CSV and any newly generated tailored resumes to a "JobPilot Reports" Drive
folder (created if absent).

Preferred path: a Google Drive MCP connector available in the Claude session (the calling
skill handles that). This script implements the standalone fallback: the Drive REST API using a
service-account key whose path is provided via secrets.py as GOOGLE_SERVICE_ACCOUNT_JSON.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets import get_secret_optional  # noqa: E402

FOLDER_NAME = "JobPilot Reports"
DRIVE_API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def _service():
    """Build a Drive service via service-account creds. Returns None if unavailable."""
    key_path = get_secret_optional("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not key_path or not Path(os.path.expanduser(key_path)).is_file():
        return None
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            os.path.expanduser(key_path),
            scopes=["https://www.googleapis.com/auth/drive.file"],
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as exc:  # noqa: BLE001
        print(f"[drive] could not build service: {exc}", file=sys.stderr)
        return None


def ensure_folder(service) -> str | None:
    try:
        q = (
            f"name = '{FOLDER_NAME}' and mimeType = 'application/vnd.google-apps.folder' "
            "and trashed = false"
        )
        res = service.files().list(q=q, fields="files(id,name)").execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]
        meta = {"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
        folder = service.files().create(body=meta, fields="id").execute()
        return folder["id"]
    except Exception as exc:  # noqa: BLE001
        print(f"[drive] folder ensure failed: {exc}", file=sys.stderr)
        return None


def upload_file(service, folder_id: str, path: Path) -> str | None:
    try:
        from googleapiclient.http import MediaFileUpload

        meta = {"name": path.name, "parents": [folder_id]}
        media = MediaFileUpload(str(path), resumable=False)
        created = service.files().create(
            body=meta, media_body=media, fields="id,webViewLink"
        ).execute()
        return created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}"
    except Exception as exc:  # noqa: BLE001
        print(f"[drive] upload failed for {path.name}: {exc}", file=sys.stderr)
        return None


def collect_files() -> list:
    files = []
    reports = sorted((jobpilot_dir() / "reports").glob("*.csv"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    if reports:
        files.append(reports[0])
    files.extend((jobpilot_dir() / "resumes" / "tailored").glob("*"))
    return files


def upload_run() -> list:
    service = _service()
    if service is None:
        print("[drive] No service-account creds and no MCP connector available — skipping. "
              "Set GOOGLE_SERVICE_ACCOUNT_JSON or use the Drive MCP connector.", file=sys.stderr)
        return []
    folder_id = ensure_folder(service)
    if not folder_id:
        return []
    links = []
    for path in collect_files():
        link = upload_file(service, folder_id, path)
        if link:
            links.append(link)
            print(f"[drive] uploaded {path.name} -> {link}")
    return links


def main() -> None:
    if "--test" in sys.argv:
        service = _service()
        if service is None:
            print("Drive not configured — nothing uploaded.")
            return
        folder_id = ensure_folder(service)
        test = Path("/tmp/jobpilot_drive_test.txt")
        test.write_text("JobPilot Drive connectivity test")
        link = upload_file(service, folder_id, test)
        print(f"Test upload: {link}")
    else:
        links = upload_run()
        print(f"Uploaded {len(links)} file(s) to '{FOLDER_NAME}'.")


if __name__ == "__main__":
    main()
