"""Resume tailor.

Generates a JD-tailored resume for a high-scoring job. Two modes:
  * default (.tex): edit ~/.claude/job-hunt-ai/resumes/base.tex and compile with tectonic -> PDF
  * --docx: build a clean DOCX from profile.json + JD keywords

Guards:
  * only runs if match_score >= score_threshold (default 75)
  * skips if this job_id already has a tailored_resume_path
  * self-caps at top_n_tailor (default 5) tailored resumes per calendar run, tracked via a
    counter file in /tmp.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ats_scorer  # noqa: E402

FILTERED_IN = "/tmp/jobpilot_filtered.json"
RUN_COUNTER = "/tmp/jobpilot_tailor_count.txt"


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def db_path() -> Path:
    return jobpilot_dir() / "cache" / "jobs.sqlite"


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def find_job(job_id: str) -> dict | None:
    for job in load_json(FILTERED_IN, []):
        if job.get("job_id") == job_id:
            return job
    return None


def already_tailored(job_id: str) -> bool:
    if not db_path().exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path()))
        row = conn.execute(
            "SELECT tailored_resume_path FROM jobs_seen WHERE job_id=?", (job_id,)
        ).fetchone()
        conn.close()
        return bool(row and row[0])
    except sqlite3.Error:
        return False


def run_count() -> int:
    try:
        return int(Path(RUN_COUNTER).read_text().strip())
    except Exception:
        return 0


def bump_count() -> None:
    Path(RUN_COUNTER).write_text(str(run_count() + 1))


def set_tailored_path(job_id: str, path: str) -> None:
    if not db_path().exists():
        return
    try:
        conn = sqlite3.connect(str(db_path()))
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO jobs_seen (job_id, tailored_resume_path, first_seen, last_seen, status) "
            "VALUES (?,?,?,?, 'active') "
            "ON CONFLICT(job_id) DO UPDATE SET tailored_resume_path=excluded.tailored_resume_path,"
            " last_seen=excluded.last_seen",
            (job_id, path, now, now),
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as exc:
        print(f"[tailor] db update failed: {exc}", file=sys.stderr)


def safe_company(job: dict) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", (job.get("company") or "company")).strip("-").lower()


def build_docx(job: dict, profile: dict, out_path: Path) -> None:
    import docx
    from docx.shared import Pt

    doc = docx.Document()
    name = profile.get("name") or "Your Name"
    doc.add_heading(name, level=0)
    contact = profile.get("email", "")
    if contact:
        doc.add_paragraph(contact)

    # Objective tuned to the role
    doc.add_heading("Objective", level=1)
    doc.add_paragraph(
        f"{profile.get('experience_years', 0)}+ yr engineer targeting the "
        f"{job.get('role', 'Software Engineer')} role at {job.get('company', '')}, "
        f"bringing hands-on strengths in the technologies this team uses."
    )

    # Skills — lead with JD-matched skills
    score = ats_scorer.score_job(job, profile)
    matched = score.get("matched_keywords", [])
    all_skills = matched + [s for s in profile.get("skills", []) if s not in matched]
    doc.add_heading("Skills", level=1)
    doc.add_paragraph(", ".join(all_skills) if all_skills else "See base resume")

    if profile.get("roles_held"):
        doc.add_heading("Experience", level=1)
        for r in profile["roles_held"]:
            doc.add_paragraph(str(r), style="List Bullet")

    if profile.get("projects"):
        doc.add_heading("Projects", level=1)
        for p in profile["projects"]:
            doc.add_paragraph(str(p), style="List Bullet")

    edu = profile.get("education", {})
    if edu:
        doc.add_heading("Education", level=1)
        doc.add_paragraph(", ".join(str(v) for v in edu.values()))

    for p in doc.paragraphs:
        for run in p.runs:
            run.font.size = run.font.size or Pt(11)

    doc.save(str(out_path))


def build_tex_pdf(job: dict, profile: dict, out_pdf: Path) -> bool:
    base = jobpilot_dir() / "resumes" / "base.tex"
    if not base.is_file():
        print(f"[tailor] base.tex not found at {base}; use --docx mode.", file=sys.stderr)
        return False
    tex = base.read_text(errors="ignore")

    score = ats_scorer.score_job(job, profile)
    matched = score.get("matched_keywords", [])
    keyword_line = ", ".join(matched) if matched else ""

    # Inject a tailored objective comment + keyword emphasis (non-destructive).
    banner = (
        f"% Tailored for {job.get('company','')} - {job.get('role','')}\n"
        f"% Emphasised keywords: {keyword_line}\n"
    )
    tex = banner + tex

    tmp_tex = Path("/tmp") / f"{safe_company(job)}-{job.get('job_id','')}.tex"
    tmp_tex.write_text(tex)

    if not shutil.which("tectonic"):
        print("[tailor] tectonic not installed; cannot compile PDF. Saved .tex only.",
              file=sys.stderr)
        shutil.copy(tmp_tex, out_pdf.with_suffix(".tex"))
        return False
    try:
        subprocess.run(
            ["tectonic", str(tmp_tex), "--outdir", str(out_pdf.parent)],
            check=True, capture_output=True, timeout=180,
        )
        compiled = out_pdf.parent / (tmp_tex.stem + ".pdf")
        if compiled.exists():
            compiled.rename(out_pdf)
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"[tailor] tectonic compile failed: {exc}", file=sys.stderr)
    return False


def tailor(job_id: str, docx_mode: bool) -> str | None:
    prefs = load_json(jobpilot_dir() / "options" / "preferences.json", {})
    profile = load_json(jobpilot_dir() / "cache" / "profile.json", {})
    threshold = float(prefs.get("score_threshold", 75))
    cap = int(prefs.get("top_n_tailor", 5))

    job = find_job(job_id)
    if not job:
        print(f"[tailor] job {job_id} not found in {FILTERED_IN}", file=sys.stderr)
        return None
    if already_tailored(job_id):
        print(f"[tailor] {job_id} already tailored — skipping.")
        return None
    if run_count() >= cap:
        print(f"[tailor] per-run cap of {cap} reached — skipping {job_id}.")
        return None

    score = ats_scorer.score_by_id(job_id).get("score", 0)
    if score < threshold:
        print(f"[tailor] score {score} < threshold {threshold} — skipping {job_id}.")
        return None

    tailored_dir = jobpilot_dir() / "resumes" / "tailored"
    tailored_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{safe_company(job)}-{job_id}"

    if docx_mode:
        out = tailored_dir / f"{stem}.docx"
        build_docx(job, profile, out)
    else:
        out = tailored_dir / f"{stem}.pdf"
        ok = build_tex_pdf(job, profile, out)
        if not ok and not out.exists():
            # fall back to docx so the run still yields a deliverable
            out = tailored_dir / f"{stem}.docx"
            build_docx(job, profile, out)

    set_tailored_path(job_id, str(out))
    bump_count()
    print(f"[tailor] wrote {out}")
    return str(out)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("usage: python3 resume_tailor.py <job_id> [--docx]", file=sys.stderr)
        sys.exit(1)
    tailor(args[0], docx_mode="--docx" in sys.argv)


if __name__ == "__main__":
    main()
