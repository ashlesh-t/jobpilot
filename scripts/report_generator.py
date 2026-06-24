"""Report generator.

Combines filtered jobs with ATS scores and salary research, then writes a dated CSV to
~/.claude/job-hunt-ai/reports/YYYY-MM-DD-<slot>.csv (slot by IST hour).
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ats_scorer  # noqa: E402
import salary_research  # noqa: E402

FILTERED_IN = "/tmp/jobpilot_filtered.json"
IST = timezone(timedelta(hours=5, minutes=30))

COLUMNS = [
    "job_id", "company", "company_blurb", "team_if_known", "role_type", "experience_req",
    "other_req", "jd_full", "jd_summary_points", "application_url", "apply_url_type",
    "source_board", "posted_date", "match_score", "why_score", "missing_keywords",
    "resume_additions_suggested", "est_package_range", "package_sources",
    "demand_estimate", "contact_for_referral",
]


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def slot_now() -> str:
    hour = datetime.now(IST).hour
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def classify_apply_url(url: str) -> str:
    u = (url or "").lower()
    if not u:
        return "other"
    if "greenhouse.io" in u:
        return "greenhouse"
    if "lever.co" in u:
        return "lever"
    if "ashbyhq.com" in u:
        return "ashby"
    if "workday" in u or "myworkdayjobs" in u:
        return "workday"
    if "docs.google.com/forms" in u or "forms.gle" in u:
        return "google_form"
    if "linkedin.com" in u:
        return "linkedin_easy"
    if any(s in u for s in ("greenhouse", "lever", "ashby")):
        return "other"
    return "company_direct"


def summarize_jd(jd: str) -> str:
    """<=5 bullet lines summarising the JD (no LLM — heuristic sentence pick)."""
    sentences = [s.strip() for s in jd.replace("\n", " ").split(".") if len(s.strip()) > 25]
    picks = sentences[:5]
    return "\n".join(f"- {s}" for s in picks) if picks else "- See full JD"


def build_rows(jobs: list) -> list:
    rows = []
    for job in jobs:
        jid = job.get("job_id", "")
        score_data = ats_scorer.score_by_id(jid) if jid else {}
        score = score_data.get("score", 0)

        salary = {}
        if score and score >= 60:
            salary = salary_research.research(
                job.get("company", ""), job.get("role", ""), job.get("location", "")
            )

        apply_type = classify_apply_url(job.get("application_url", ""))
        apply_type_cell = f"⚠️ {apply_type}" if apply_type == "google_form" else apply_type

        est_range = ""
        if salary:
            est_range = f"{salary.get('min_lpa', '')}-{salary.get('max_lpa', '')}"

        rows.append({
            "job_id": jid,
            "company": job.get("company", ""),
            "company_blurb": job.get("company_blurb", ""),
            "team_if_known": job.get("team", ""),
            "role_type": job.get("role", ""),
            "experience_req": job.get("experience_req", ""),
            "other_req": job.get("other_req", ""),
            "jd_full": job.get("jd_full", ""),
            "jd_summary_points": summarize_jd(job.get("jd_full", "")),
            "application_url": job.get("application_url", ""),
            "apply_url_type": apply_type_cell,
            "source_board": job.get("source_board", ""),
            "posted_date": job.get("posted_date", ""),
            "match_score": score,
            "why_score": score_data.get("why", ""),
            "missing_keywords": ", ".join(score_data.get("missing_keywords", [])),
            "resume_additions_suggested": "; ".join(score_data.get("suggested_additions", [])),
            "est_package_range": est_range,
            "package_sources": ", ".join(salary.get("sources", [])) if salary else "",
            "demand_estimate": salary.get("demand_estimate", "") if salary else "",
            "contact_for_referral": job.get("contact_for_referral", ""),
        })
    rows.sort(key=lambda r: r["match_score"] or 0, reverse=True)
    return rows


def write_csv(rows: list) -> Path:
    reports = jobpilot_dir() / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    fname = f"{datetime.now(IST).strftime('%Y-%m-%d')}-{slot_now()}.csv"
    out = reports / fname
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return out


def main() -> None:
    jobs = load_json(FILTERED_IN, [])
    rows = build_rows(jobs)
    path = write_csv(rows)
    print(f"Wrote {len(rows)} rows -> {path}")


if __name__ == "__main__":
    main()
