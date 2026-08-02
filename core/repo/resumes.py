"""Resume repository — folders of uploaded resumes with exactly one active file.

Replaces the Google Drive dependency: files are uploaded through the UI into
`<jobpilot_dir>/resumes/<folder>/` and the active one is what every tailoring or
profile-extraction step reads.
"""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

from sqlalchemy import select

from ..db import session_scope
from ..models import Resume
from ..paths import ensure_dirs, resumes_dir

ALLOWED_SUFFIXES = {".pdf", ".docx", ".tex", ".txt", ".md"}
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str) -> str:
    cleaned = _SAFE.sub("_", (name or "").strip()).strip("._-")
    return cleaned or "resume"


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _iso(dt):
    return dt.isoformat() if dt else None


def to_dict(r: Resume) -> dict:
    exists = Path(r.path).exists()
    return {
        "id": r.id,
        "folder": r.folder,
        "filename": r.filename,
        "label": r.label or r.filename,
        "path": r.path,
        "suffix": Path(r.filename).suffix.lower(),
        "hash": r.file_hash,
        "is_active": r.is_active,
        "uploaded_at": _iso(r.uploaded_at),
        "size": Path(r.path).stat().st_size if exists else 0,
        "missing": not exists,
    }


def add(source: Path | str, *, folder: str = "default", filename: str | None = None,
        label: str = "", make_active: bool | None = None) -> dict:
    """Copy a file into the resume tree and register it. Overwrites same folder+filename."""
    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(src)
    folder = safe_name(folder)
    name = safe_name(filename or src.name)
    if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported resume type {Path(name).suffix!r}; "
                         f"allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}")

    ensure_dirs()
    dest_dir = resumes_dir() / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)

    with session_scope() as s:
        row = s.scalar(select(Resume).where(Resume.folder == folder, Resume.filename == name))
        first = s.scalar(select(Resume).limit(1)) is None
        if row is None:
            row = Resume(folder=folder, filename=name, path=str(dest))
            s.add(row)
        row.path = str(dest)
        row.label = label or row.label or Path(name).stem
        row.file_hash = file_hash(dest)
        s.flush()
        # First resume ever uploaded becomes active automatically — one less click.
        if make_active or (make_active is None and first):
            _activate(s, row.id)
        s.flush()
        return to_dict(row)


def _activate(session, resume_id: int) -> None:
    for other in session.scalars(select(Resume)).all():
        other.is_active = other.id == resume_id


def set_active(resume_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(Resume, resume_id)
        if row is None:
            return None
        _activate(s, resume_id)
        s.flush()
        return to_dict(row)


def active() -> dict | None:
    with session_scope() as s:
        row = s.scalar(select(Resume).where(Resume.is_active.is_(True)))
        return to_dict(row) if row else None


def active_path() -> Path | None:
    a = active()
    if not a or a["missing"]:
        return None
    return Path(a["path"])


def get(resume_id: int) -> dict | None:
    with session_scope() as s:
        row = s.get(Resume, resume_id)
        return to_dict(row) if row else None


def list_all() -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(Resume).order_by(Resume.folder, Resume.filename)).all()
        return [to_dict(r) for r in rows]


def folders() -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for r in list_all():
        grouped.setdefault(r["folder"], []).append(r)
    return [{"folder": k, "resumes": v} for k, v in sorted(grouped.items())]


def rename_folder(old: str, new: str) -> int:
    old, new = safe_name(old), safe_name(new)
    src, dest = resumes_dir() / old, resumes_dir() / new
    if src.exists():
        if dest.exists():
            raise ValueError(f"folder {new!r} already exists")
        src.rename(dest)
    with session_scope() as s:
        rows = s.scalars(select(Resume).where(Resume.folder == old)).all()
        for r in rows:
            r.folder = new
            r.path = str(dest / r.filename)
        return len(rows)


def set_parsed_text(resume_id: int, text: str) -> None:
    with session_scope() as s:
        row = s.get(Resume, resume_id)
        if row is not None:
            row.parsed_text = text


def remove(resume_id: int, *, delete_file: bool = True) -> bool:
    with session_scope() as s:
        row = s.get(Resume, resume_id)
        if row is None:
            return False
        was_active = row.is_active
        path = Path(row.path)
        s.delete(row)
        s.flush()
        if delete_file and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        if was_active:
            nxt = s.scalar(select(Resume).order_by(Resume.uploaded_at.desc()))
            if nxt is not None:
                nxt.is_active = True
        return True
