"""Resume tailoring — build, validate and compile a resume aimed at one job.

Output contract (fixed; the UI and Telegram both depend on it):

    resumes/tailored/<JOBID>-<COMPANY>/
        FirstName_LastName_Resume.pdf
        FirstName_LastName_Resume.tex     # compiles standalone on Overleaf
        meta.json

The agent edits *content*, never layout: the template is ATS-safe by construction and
a rewritten layout is the fastest way to become unparseable. `validate_tex` enforces
that before anything is compiled.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .paths import tailored_dir
from .repo import tailored as tailored_repo

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "resume" / "ats_safe.tex"

MAX_PAGES = 2

#: Packages the template uses. Anything outside this set risks not being installed on
#: Overleaf or in tectonic's default set, which is the whole point of pinning it.
ALLOWED_PACKAGES = {
    "fontenc", "inputenc", "geometry", "enumitem", "titlesec", "hyperref",
    "parskip", "hyphenat",
}

REQUIRED_SECTIONS = ("Summary", "Skills", "Experience", "Education")

#: Constructs that quietly destroy ATS parsing.
BANNED_PATTERNS = [
    (r"\\begin\{tabular", "tables — an ATS reads the columns interleaved"),
    (r"\\begin\{multicols", "multi-column layout — parses as scrambled text"),
    (r"\\includegraphics", "images — invisible to an ATS, and often to a recruiter"),
    (r"\\begin\{tikzpicture", "TikZ graphics"),
    (r"\\fancyhead|\\fancyfoot", "header/footer text — frequently dropped when parsing"),
    (r"\\textcolor", "coloured text — can be dropped or mis-rendered"),
]


@dataclass
class ValidationResult:
    ok: bool
    problems: list[str]
    warnings: list[str]

    def as_dict(self) -> dict:
        return {"ok": self.ok, "problems": self.problems, "warnings": self.warnings}


def load_template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def resume_basename(full_name: str) -> str:
    return tailored_repo.resume_basename(full_name)


def folder_for(user_id: int, job_id: str, company: str) -> Path:
    return tailored_repo.folder_for(user_id, job_id, company)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_tex(source: str) -> ValidationResult:
    """Check a tailored .tex before compiling it. Cheap, and catches the real failures."""
    problems: list[str] = []
    warnings: list[str] = []

    if "\\documentclass" not in source or "\\begin{document}" not in source:
        problems.append("not a complete LaTeX document")

    for pattern, why in BANNED_PATTERNS:
        if re.search(pattern, source):
            problems.append(f"uses {why}")

    used = set(re.findall(r"\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}", source))
    extra = {p.strip() for group in used for p in group.split(",")} - ALLOWED_PACKAGES
    if extra:
        problems.append(
            f"uses packages outside the ATS-safe set ({', '.join(sorted(extra))}) — "
            f"these may not exist on Overleaf")

    for section in REQUIRED_SECTIONS:
        if not re.search(rf"\\section\{{\s*{section}", source, re.I):
            problems.append(f"missing the {section} section")

    # Only look for real placeholders in live LaTeX — the template's own header comment
    # documents the {{NAME}} convention and would otherwise trip this every time.
    live = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("%"))
    unfilled = re.findall(r"\{\{[A-Z_]+\}\}", live)
    if unfilled:
        problems.append(
            f"still contains unfilled placeholders: {', '.join(sorted(set(unfilled)))}")

    body = source.split("\\begin{document}", 1)[-1]
    if len(body) > 9000:
        warnings.append("the content is long — it may not fit two pages")
    if len(body) < 600:
        warnings.append("the content is very short — check nothing was dropped")

    return ValidationResult(ok=not problems, problems=problems, warnings=warnings)


def count_pages(pdf: Path) -> int | None:
    try:
        from PyPDF2 import PdfReader
        return len(PdfReader(str(pdf)).pages)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Compilation
# --------------------------------------------------------------------------- #
def has_tectonic() -> bool:
    return shutil.which("tectonic") is not None


def compile_pdf(tex_source: str, out_dir: Path, basename: str) -> tuple[Path | None, str]:
    """Compile with tectonic. Returns (pdf_path, message); (None, why) on failure.

    Compiles in a temp directory so a failed run never leaves a broken PDF next to a
    good .tex — the user would have no way to tell which was current.
    """
    if not has_tectonic():
        return None, ("tectonic isn't installed, so no PDF was produced. The .tex is "
                      "ready to compile — paste it into Overleaf.")

    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        tex_file = tmp_path / f"{basename}.tex"
        tex_file.write_text(tex_source, encoding="utf-8")
        try:
            proc = subprocess.run(
                ["tectonic", str(tex_file), "--outdir", str(tmp_path), "--chatter", "minimal"],
                capture_output=True, text=True, timeout=180,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return None, f"tectonic failed: {exc}"

        pdf = tmp_path / f"{basename}.pdf"
        if proc.returncode != 0 or not pdf.exists():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
            return None, "tectonic could not compile it: " + " / ".join(tail)

        target = out_dir / f"{basename}.pdf"
        shutil.copy2(pdf, target)
        return target, "compiled"


# --------------------------------------------------------------------------- #
# ATS scoring
# --------------------------------------------------------------------------- #
def ats_score(text: str, jd_skills: list[str]) -> float:
    """Share of the job's skills that appear in the document, 0–100.

    Deliberately the same shape as the pipeline's `keyword_score`, so before/after is
    comparable with the score the job was ranked on.
    """
    if not jd_skills:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for skill in jd_skills if skill.lower() in lowered)
    return round(hits / len(jd_skills) * 100, 1)


# --------------------------------------------------------------------------- #
# Persisting a result
# --------------------------------------------------------------------------- #
def write_result(*, user_id: int, job_id: str, company: str, full_name: str, tex_source: str,
                 jd_skills: list[str], base_text: str = "", engine: str = "",
                 cost_usd: float = 0.0, base_resume_id: int | None = None) -> dict:
    """Write the folder, compile, score, and record it. Never raises on a compile error —
    a .tex the user can take to Overleaf is still a useful result."""
    folder = folder_for(user_id, job_id, company)
    folder.mkdir(parents=True, exist_ok=True)
    basename = resume_basename(full_name)

    validation = validate_tex(tex_source)

    tex_path = folder / f"{basename}.tex"
    tex_path.write_text(tex_source, encoding="utf-8")

    pdf_path, message = (None, "not compiled — the document failed validation")
    if validation.ok:
        pdf_path, message = compile_pdf(tex_source, folder, basename)

    pages = count_pages(pdf_path) if pdf_path else None
    if pages and pages > MAX_PAGES:
        validation.warnings.append(
            f"{pages} pages — most recruiters expect at most {MAX_PAGES}")

    before = ats_score(base_text, jd_skills) if base_text else None
    after = ats_score(tex_source, jd_skills)

    meta = {
        "job_id": job_id,
        "company": company,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "engine": engine,
        "matched_skills": [s for s in jd_skills if s.lower() in tex_source.lower()],
        "missing_skills": [s for s in jd_skills if s.lower() not in tex_source.lower()],
        "ats_before": before,
        "ats_after": after,
        "pages": pages,
        "compile": message,
        "validation": validation.as_dict(),
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    record = tailored_repo.upsert(
        user_id,
        job_id,
        company=company,
        pdf_path=str(pdf_path) if pdf_path else "",
        tex_path=str(tex_path),
        ats_before=before,
        ats_after=after,
        engine=engine,
        cost_usd=cost_usd,
        status="done" if validation.ok else "warning",
        error="; ".join(validation.problems),
        meta=meta,
        base_resume_id=base_resume_id,
    )
    record["message"] = message
    record["validation"] = validation.as_dict()
    return record


def list_folder(user_id: int, folder_name: str) -> list[dict]:
    root = tailored_dir(user_id) / folder_name
    if not root.exists():
        return []
    return [
        {"name": p.name, "size": p.stat().st_size, "suffix": p.suffix.lower()}
        for p in sorted(root.iterdir()) if p.is_file()
    ]
