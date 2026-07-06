"""Layer A hard filter — pure Python, NO LLM.

Applies location, deadline, experience, and CTC/company hard filters.
All other filtering (role relevance, keyword match) is handled by Claude in Layer B.

Reads /tmp/jobpilot_deduped.json + preferences.json, writes /tmp/jobpilot_filtered.json.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEDUPED_IN = "/tmp/jobpilot_deduped.json"
FILTERED_OUT = "/tmp/jobpilot_filtered.json"

IST = ZoneInfo("Asia/Kolkata")

SERVICE_COMPANIES = [
    "tcs", "infosys", "wipro", "hcl", "cognizant", "accenture",
    "capgemini", "ltimindtree", "mphasis", "tech mahindra",
]

# Cities that appear under more than one name. A user preference for any spelling
# should match a job listed under an alias (Bengaluru ⟷ Bangalore, etc.).
CITY_ALIASES = {
    "bengaluru": ["bangalore", "blr"],
    "bangalore": ["bengaluru", "blr"],
    "gurugram": ["gurgaon"],
    "gurgaon": ["gurugram"],
    "mumbai": ["bombay", "navi mumbai", "thane"],
    "pune": ["pimpri", "pcmc"],
    "delhi": ["new delhi", "ncr", "delhi ncr"],
    "noida": ["greater noida"],
    "kolkata": ["calcutta"],
    "chennai": ["madras"],
    "hyderabad": ["secunderabad", "hyd"],
    "trivandrum": ["thiruvananthapuram"],
}


def _loc_variants(pref_loc: str):
    """A preference location plus all of its known spelling aliases (lowercased)."""
    pl = (pref_loc or "").lower().strip()
    return {pl, *CITY_ALIASES.get(pl, [])}


def _loc_matches(pref_loc: str, job_loc: str) -> bool:
    """Whether a job's location text satisfies a single preference location."""
    pl = (pref_loc or "").lower().strip()
    loc = (job_loc or "").lower()
    if pl == "remote":
        return "remote" in loc or "work from home" in loc or "anywhere" in loc
    return any(v and v in loc for v in _loc_variants(pl))


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


def seen_job_ids() -> set:
    if not db_path().exists():
        return set()
    try:
        conn = sqlite3.connect(str(db_path()))
        rows = conn.execute(
            "SELECT job_id FROM jobs_seen WHERE status = 'active'"
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}
    except sqlite3.Error:
        return set()


def extract_exp_req(job: dict) -> int:
    """Minimum years of experience the JD requires.

    Returns 0 for fresher/entry-level, the lower bound N for an "N+ years" /
    "N-M years" requirement, or -1 when nothing is stated (don't penalise).
    Checks the structured experience_req field first, then the JD body.
    """
    exp_field = (job.get("experience_req") or "").lower()
    jd = (job.get("jd_full") or "").lower()

    # Fresher signals anywhere -> 0
    if re.search(r"fresher|entry[\s-]?level|new\s+grad|0\s*[-0-]\s*1\s*year|no\s+experience",
                 exp_field + " " + jd):
        fresher = 0
    else:
        fresher = None

    for text in (exp_field, jd):
        if not text:
            continue
        # "3-5 years", "3 to 5 years", "2 – 4 yrs"
        m = re.search(r"(\d+)\s*(?:-|-|to)\s*\d+\s*(?:\+)?\s*(?:years?|yrs?)", text)
        if m:
            return int(m.group(1))
        # "3+ years", "minimum 3 years", "3 years", "3 year(s)"
        m = re.search(r"(?:minimum\s+|min\.?\s+|at least\s+)?(\d+)\s*\+?\s*(?:years?|yrs?|year\(s\))",
                      text)
        if m:
            return int(m.group(1))

    return 0 if fresher == 0 else -1


def location_ok(job: dict, prefs: dict) -> bool:
    loc = (job.get("location") or "").lower()
    if not loc:
        return True  # unknown location — keep, Claude will judge

    if prefs.get("remote_ok", True) and ("remote" in loc or "work from home" in loc):
        return True
    for pref_loc in prefs.get("locations", []):
        if _loc_matches(pref_loc, loc):
            return True
    return False


def _load_locations_cache() -> dict:
    """Load canonical city entries from locations.json.

    Returns the 'canonical' dict (city_key → {aliases, weight, priority_rank}).
    Returns {} if the file is missing or unreadable — caller falls back to CITY_ALIASES.
    """
    cache_path = jobpilot_dir() / "cache" / "locations.json"
    try:
        return json.loads(cache_path.read_text()).get("canonical", {})
    except Exception:
        return {}


def location_weight(job: dict, prefs: dict) -> float:
    """Return a location fit weight (0.7–1.0) for sorting.

    Layer A (cache): tries locations.json first — alias-aware, Claude-seeded at setup.
    Layer B (fallback): uses CITY_ALIASES + preference-index weights if cache absent.
    Logs which alias matched (or 'no match') to stderr for debugging.
    """
    loc = (job.get("location") or "").lower()
    canonical = _load_locations_cache()

    if canonical:
        for city_key, city_data in canonical.items():
            aliases = [a.lower() for a in (city_data.get("aliases") or [])]
            all_variants = [city_key.lower()] + aliases
            matched = next((v for v in all_variants if v and v in loc), None)
            if matched:
                weight = float(city_data.get("weight", 1.0))
                print(
                    f"[filter] '{loc}' matched canonical '{city_key}' "
                    f"via '{matched}' → weight {weight}",
                    file=sys.stderr,
                )
                return weight
        print(f"[filter] '{loc}' — no canonical match → weight 0.75", file=sys.stderr)
        return 0.75  # unknown location — neutral weight

    # Fallback: use CITY_ALIASES + preference-index weights (no locations.json present)
    priority = prefs.get("location_priority") or prefs.get("locations", [])
    for i, pref_loc in enumerate(priority):
        if _loc_matches(pref_loc, loc):
            if i == 0:
                return 1.0
            elif i == 1:
                return 0.85
            else:
                return 0.7
    return 0.75  # unknown location — neutral weight


def deadline_passed(job: dict) -> bool:
    """True if last_date is set AND the deadline has already passed (IST midnight)."""
    ld = (job.get("last_date") or "").strip()
    if not ld:
        return False
    for fmt in ("%Y-%m-%d", "%d %b'%y", "%d %b %Y", "%d/%m/%Y", "%d-%b-%Y"):
        try:
            dt = datetime.strptime(ld, fmt).replace(tzinfo=IST)
            return dt.date() < datetime.now(IST).date()
        except ValueError:
            continue
    return False  # unparseable format — keep the job


def ctc_company_ok(job: dict, prefs: dict, user_exp: int = 0) -> tuple[bool, bool]:
    """Check CTC threshold and optionally filter service companies.

    For early-career candidates (experience_years <= 2) the CTC filter is soft:
    jobs below target_ctc_min_lpa are kept but flagged with ctc_flag="below_target"
    so Claude can deprioritise rather than hard-drop them.

    Returns (keep, ctc_unknown).
    - (False, False): hard drop (experienced candidates only, CTC confirmed below min)
    - (True, False): keep, CTC confirmed ok (or soft-flagged for freshers)
    - (True, True): keep, CTC not found in JD — flag for Claude to judge
    """
    company = (job.get("company") or "").lower().strip()
    if prefs.get("avoid_service_companies", False):
        if any(s in company for s in SERVICE_COMPANIES):
            return False, False

    min_ctc = float(prefs.get("target_ctc_min_lpa") or 0)
    if min_ctc <= 0:
        return True, True  # no CTC preference set — keep, unknown

    is_early_career = user_exp <= 2

    text = ((job.get("jd_full") or "") + " " + (job.get("experience_req") or "")).lower()
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:[-–]\s*\d+(?:\.\d+)?\s*)?(?:lpa|l\.p\.a|lakhs?)\b", text
    )
    if m:
        found = float(m.group(1))
        if found >= min_ctc:
            return True, False  # CTC meets target — keep
        if is_early_career:
            # Soft filter: flag but don't drop — freshers have less negotiating power
            job["ctc_flag"] = "below_target"
            return True, False
        return False, False  # Hard drop for experienced candidates

    return True, True  # CTC unknown — keep, flag for Claude


def main() -> int:
    jobs = load_json(DEDUPED_IN, [])
    prefs = load_json(jobpilot_dir() / "options" / "preferences.json", {})
    seen = seen_job_ids()

    kept = []
    dropped_seen = 0
    soft_ctc_flagged = 0
    reasons = {"location": 0, "expired": 0, "experience": 0, "ctc_company": 0}

    user_exp = int(prefs.get("experience_years", 0) or 0)
    # A fresher (0-1 yr) shouldn't see roles demanding 3+ yrs; scale the cap with the user.
    exp_cap = max(3, user_exp + 2)

    for job in jobs:
        jid = job.get("job_id", "")
        if jid in seen:
            dropped_seen += 1
            continue
        if deadline_passed(job):
            reasons["expired"] += 1
            continue
        if not location_ok(job, prefs):
            reasons["location"] += 1
            continue
        exp_req = extract_exp_req(job)
        job["exp_req_years"] = exp_req
        if exp_req >= exp_cap:
            reasons["experience"] += 1
            continue
        keep_ctc, ctc_unknown = ctc_company_ok(job, prefs, user_exp)
        if not keep_ctc:
            reasons["ctc_company"] += 1
            continue
        if ctc_unknown:
            job["ctc_unknown"] = True
        if job.get("ctc_flag") == "below_target":
            soft_ctc_flagged += 1
        job["location_weight"] = location_weight(job, prefs)
        kept.append(job)

    Path(FILTERED_OUT).write_text(json.dumps(kept, indent=2, ensure_ascii=False))
    soft_note = f" ({soft_ctc_flagged} soft-flagged below-target CTC)" if soft_ctc_flagged else ""
    print(
        f"Filter: {len(jobs)} in → {len(kept)} kept | "
        f"seen={dropped_seen} location={reasons['location']} expired={reasons['expired']} "
        f"exp={reasons['experience']} ctc={reasons['ctc_company']}{soft_note} → {FILTERED_OUT}"
    )
    return len(kept)


if __name__ == "__main__":
    main()
