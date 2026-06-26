"""Resume parser — dumb text extractor only.

Extracts raw text from PDF/DOCX/TEX and writes it to /tmp/jobpilot_resume_raw.txt.
Computes the file hash and updates resume_hash + resume_path in preferences.json.
Writes a skeleton profile.json with profile_verified: false so Claude knows to verify.

Claude reads /tmp/jobpilot_resume_raw.txt and builds the real profile.json during /job-setup.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".tex":
        import re
        tex = path.read_text(errors="ignore")
        tex = re.sub(r"%.*", "", tex)
        tex = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", tex)
        tex = re.sub(r"[{}\\$&#~^_]", " ", tex)
        return re.sub(r"\s+", " ", tex).strip()
    if suffix == ".docx":
        try:
            import docx
            doc = docx.Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as exc:
            print(f"[parser] docx read failed: {exc}", file=sys.stderr)
            return ""
    if suffix == ".pdf":
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(path))
            return "\n".join((pg.extract_text() or "") for pg in reader.pages)
        except Exception:
            pass
        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                return "\n".join(pg.extract_text() or "" for pg in pdf.pages)
        except Exception as exc:
            print(f"[parser] pdf read failed: {exc}", file=sys.stderr)
            return ""
    return path.read_text(errors="ignore")


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python3 resume_parser.py <path> [--drive-file-id <id>]", file=sys.stderr)
        sys.exit(1)

    path = Path(os.path.expanduser(sys.argv[1]))
    if not path.is_file():
        print(f"resume not found: {path}", file=sys.stderr)
        sys.exit(1)

    drive_file_id = ""
    if "--drive-file-id" in sys.argv:
        idx = sys.argv.index("--drive-file-id")
        if idx + 1 < len(sys.argv):
            drive_file_id = sys.argv[idx + 1]

    raw_text = extract_text(path)
    resume_hash = file_hash(path)

    # Write raw text for Claude to read
    raw_out = Path("/tmp/jobpilot_resume_raw.txt")
    raw_out.write_text(raw_text, encoding="utf-8")
    print(f"[parser] Raw text ({len(raw_text)} chars) -> {raw_out}", file=sys.stderr)

    # Update preferences.json with hash and path (used for cache invalidation)
    prefs_path = jobpilot_dir() / "options" / "preferences.json"
    prefs = {}
    if prefs_path.exists():
        try:
            prefs = json.loads(prefs_path.read_text())
        except Exception:
            prefs = {}
    prev_hash = prefs.get("resume_hash", "")
    prefs["resume_hash"] = resume_hash
    prefs["resume_path"] = str(path)
    if drive_file_id:
        prefs["resume_drive_file_id"] = drive_file_id
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(json.dumps(prefs, indent=2))

    # Write skeleton profile.json — Claude will fill in the real content
    profile_path = jobpilot_dir() / "cache" / "profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    if profile_path.exists():
        try:
            existing = json.loads(profile_path.read_text())
        except Exception:
            existing = {}
    else:
        existing = {}

    # If resume changed, reset profile_verified so Claude re-reads the new resume
    if prev_hash and prev_hash != resume_hash:
        existing["profile_verified"] = False
        print("[parser] Resume hash changed — resetting profile_verified to false", file=sys.stderr)
    elif "profile_verified" not in existing:
        existing["profile_verified"] = False

    existing["hash"] = resume_hash
    profile_path.write_text(json.dumps(existing, indent=2))

    # Print raw text to stdout so the calling skill can optionally capture it
    print(raw_text)


if __name__ == "__main__":
    main()
