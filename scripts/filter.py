"""Layer A hard filter — pure Python, NO LLM.

Applies location, experience, CTC/company-quality, and keyword pre-filters in order.
Reads /tmp/jobpilot_deduped.json + preferences.json + profile.json, writes
/tmp/jobpilot_filtered.json, and prints a breakdown by rejection reason.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

DEDUPED_IN = "/tmp/jobpilot_deduped.json"
FILTERED_OUT = "/tmp/jobpilot_filtered.json"

SERVICE_COMPANIES = [
    "tcs", "infosys", "wipro", "hcl", "cognizant", "accenture",
    "capgemini", "ltimindtree", "mphasis", "tech mahindra",
]


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def parse_years(text: str):
    """Extract a representative years-of-experience number from JD text. None if unknown."""
    if not text:
        return None
    t = text.lower()
    m = re.search(r"(\d+)\s*(?:-|to|–)\s*(\d+)\s*(?:\+)?\s*years?", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*\+?\s*years?", t)
    if m:
        return int(m.group(1))
    return None


def estimate_ctc(job: dict):
    """Best-effort LPA extraction from JD text. None if unknown."""
    text = (job.get("jd_full") or "") + " " + (job.get("experience_req") or "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?)", text, re.I)
    if m:
        return float(m.group(2))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?)", text, re.I)
    if m:
        return float(m.group(1))
    return None


def location_ok(job: dict, prefs: dict) -> bool:
    loc = (job.get("location") or "").lower()
    if prefs.get("remote_ok", True) and "remote" in loc:
        return True
    for pref_loc in prefs.get("locations", []):
        pl = pref_loc.lower()
        if pl == "remote" and "remote" in loc:
            return True
        if pl != "remote" and pl in loc:
            return True
    # Unknown location: keep (don't drop silently)
    return not loc


def experience_ok(job: dict, prefs: dict) -> bool:
    user_exp = int(prefs.get("experience_years", 0) or 0)
    yrs = parse_years((job.get("jd_full") or "") + " " + (job.get("experience_req") or ""))
    if yrs is None:
        return True  # unknown -> keep
    return (user_exp - 1) <= yrs <= (user_exp + 2)


def ctc_company_ok(job: dict, prefs: dict):
    """Returns (keep: bool, ctc_unknown_flag: bool)."""
    company = (job.get("company") or "").lower().strip()
    is_service = company in SERVICE_COMPANIES
    est = estimate_ctc(job)
    floor = float(prefs.get("target_ctc_min_lpa", 0) or 0)
    ctc_unknown = est is None
    ctc_ok = est is None or est >= floor
    keep = (not is_service) or ctc_ok
    return keep, ctc_unknown


def keyword_ok(job: dict, profile: dict) -> bool:
    skills = [s.lower() for s in profile.get("skills", []) if s]
    if not skills:
        return True  # no profile skills known -> don't block
    jd = (job.get("jd_full") or "").lower()
    return any(skill in jd for skill in skills)


def main() -> int:
    jobs = load_json(DEDUPED_IN, [])
    prefs = load_json(jobpilot_dir() / "options" / "preferences.json", {})
    profile = load_json(jobpilot_dir() / "cache" / "profile.json", {})

    kept = []
    reasons = {"location": 0, "experience": 0, "ctc_company": 0, "keyword": 0}

    for job in jobs:
        if not location_ok(job, prefs):
            reasons["location"] += 1
            continue
        if not experience_ok(job, prefs):
            reasons["experience"] += 1
            continue
        keep_ctc, ctc_unknown = ctc_company_ok(job, prefs)
        if not keep_ctc:
            reasons["ctc_company"] += 1
            continue
        if not keyword_ok(job, profile):
            reasons["keyword"] += 1
            continue
        if ctc_unknown:
            job["ctc_unknown"] = True
        kept.append(job)

    Path(FILTERED_OUT).write_text(json.dumps(kept, indent=2, ensure_ascii=False))
    print(
        f"Filter: {len(jobs)} in -> {len(kept)} kept | "
        f"dropped by location={reasons['location']}, experience={reasons['experience']}, "
        f"ctc/company={reasons['ctc_company']}, keyword={reasons['keyword']} -> {FILTERED_OUT}"
    )
    return len(kept)


if __name__ == "__main__":
    main()
