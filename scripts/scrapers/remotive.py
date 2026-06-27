"""Native Remotive scraper — pure Python, NO LLM, NO Apify.

Remotive exposes a clean JSON API: https://remotive.com/api/remote-jobs?search=...
Fields: title, company_name, candidate_required_location, salary, description, url.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, region_ok, strip_html  # noqa: E402

API = "https://remotive.com/api/remote-jobs"


def fetch(keywords="software engineer", location="", max_results=25, hours_old=None, focus="india"):
    search = (keywords or "").strip()[:60]
    resp = http_get(API, params={"search": search, "limit": max(max_results, 30)}, timeout=25)
    if not resp:
        return []
    try:
        jobs_raw = resp.json().get("jobs", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in jobs_raw:
        req_loc = item.get("candidate_required_location", "") or "Worldwide"
        if not region_ok(req_loc, focus):
            continue
        jd = strip_html(item.get("description", ""))
        sal = item.get("salary") or ""
        jd_full = (jd + (f"  Salary: {sal}" if sal else "")).strip()
        out.append(build_job(
            company=item.get("company_name", ""),
            role=item.get("title", ""),
            location=f"Remote ({req_loc})",
            jd=jd_full,
            url=item.get("url", ""),
            source="remotive",
            posted=str(item.get("publication_date", ""))[:10],
            exp=item.get("job_type", ""),
        ))
        if len(out) >= max_results:
            break
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("backend python", max_results=15, focus="both")
    print(f"remotive: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
