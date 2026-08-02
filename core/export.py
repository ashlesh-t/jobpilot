"""CSV and XLSX export for job lists.

Reuses `scripts/report_generator.COLUMNS` so a download from the UI has exactly the same
columns, in the same order, as the spreadsheet that arrives on Telegram. A user comparing
the two should never find them different.

Streams into an in-memory buffer — these are at most a few thousand rows, and a temp file
on disk would need cleaning up.
"""
from __future__ import annotations

import csv
import io
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _columns() -> list[tuple[str, str, int]]:
    try:
        from report_generator import COLUMNS
        return list(COLUMNS)
    except Exception:
        # Report generator unavailable (minimal install) — a reduced but still useful set.
        return [
            ("#", "_row", 5),
            ("Company", "company", 22),
            ("Role", "role", 30),
            ("Location", "location", 20),
            ("Match Score", "score", 11),
            ("Rank Score", "effective_score", 11),
            ("Matched Skills", "matched_skills", 28),
            ("Missing Skills", "missing_skills", 26),
            ("Market Salary", "market_salary", 15),
            ("Apply Link", "application_url", 40),
            ("Source Board", "source_board", 14),
            ("Job ID", "job_id", 18),
        ]


# Columns the database knows about that the pipeline report doesn't carry.
EXTRA_COLUMNS = [
    ("Application Status", "application_status", 16),
    ("Applied On", "applied_at", 14),
]


def _cell(job: dict, key: str, row_number: int) -> Any:
    if key == "_row":
        return row_number
    value = job.get(key, "")
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items())
    if value is None:
        return ""
    if key in ("applied_at", "first_seen", "last_seen") and isinstance(value, str):
        return value[:10]
    return value


def _headers(include_application: bool) -> list[tuple[str, str, int]]:
    cols = _columns()
    if include_application:
        cols = cols + EXTRA_COLUMNS
    return cols


def default_filename(prefix: str = "jobpilot-jobs", suffix: str = "csv") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{prefix}-{stamp}.{suffix}"


def to_csv(jobs: Iterable[dict], *, include_application: bool = True) -> bytes:
    cols = _headers(include_application)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header for header, _key, _w in cols])
    for i, job in enumerate(jobs, start=1):
        writer.writerow([_cell(job, key, i) for _h, key, _w in cols])
    # BOM so Excel opens UTF-8 correctly on Windows without a manual import step.
    return buffer.getvalue().encode("utf-8-sig")


def to_xlsx(jobs: Iterable[dict], *, include_application: bool = True,
            title: str = "Jobs") -> bytes | None:
    """Styled workbook, or None when openpyxl isn't installed (caller falls back to CSV)."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        return None

    cols = _headers(include_application)
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31] or "Jobs"

    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF")
    for c, (header, _key, width) in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=c, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = width
    ws.freeze_panes = "A2"

    # Same score bands as the emailed report, so colours mean the same thing everywhere.
    green = PatternFill("solid", fgColor="C6EFCE")
    yellow = PatternFill("solid", fgColor="FFEB9C")

    jobs = list(jobs)
    for r, job in enumerate(jobs, start=2):
        try:
            score = float(job.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        fill = green if score >= 75 else yellow if score >= 60 else None
        for c, (_h, key, _w) in enumerate(cols, start=1):
            cell = ws.cell(row=r, column=c, value=_cell(job, key, r - 1))
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if fill:
                cell.fill = fill
            if key == "application_url" and job.get("application_url"):
                cell.hyperlink = job["application_url"]
                cell.font = Font(color="1F4E79", underline="single")
        ws.row_dimensions[r].height = 48

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def export(jobs: Iterable[dict], fmt: str = "csv", *, title: str = "Jobs",
           include_application: bool = True) -> tuple[bytes, str, str]:
    """Return (content, media_type, filename). Falls back to CSV if XLSX isn't possible."""
    jobs = list(jobs)
    if fmt == "xlsx":
        data = to_xlsx(jobs, include_application=include_application, title=title)
        if data is not None:
            return (
                data,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                default_filename(suffix="xlsx"),
            )
        # openpyxl missing — a CSV the user can open beats an error page.
    return to_csv(jobs, include_application=include_application), "text/csv", default_filename()
