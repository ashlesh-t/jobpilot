"""Native Instahyre scraper — pure Python, NO LLM, NO Apify.

Instahyre (instahyre.com) is a curated India tech hiring platform.
Uses their public job search API (no auth required for browsing).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

API = "https://www.instahyre.com/api/v1/opportunity"


def fetch(keywords="software engineer", max_results=25, focus="both"):
    if focus == "global":
        print("[instahyre] India-only board — skipping for global-only focus", file=sys.stderr)
        return []

    keyword_terms = split_terms(keywords)
    params = {
        "query": keywords,
        "page": 1,
        "page_size": min(max_results, 50),
        "job_type": "full_time",
    }
    resp = http_get(API, params=params, headers={"Accept": "application/json"}, timeout=25)
    if not resp:
        return []

    try:
        data = resp.json()
    except Exception:
        print("[instahyre] API did not return JSON — skipping", file=sys.stderr)
        return []

    jobs_raw = (
        data.get("results")
        or data.get("opportunities")
        or data.get("jobs")
        or (data if isinstance(data, list) else [])
    )
    out = []
    for item in jobs_raw:
        if not isinstance(item, dict):
            continue
        role     = item.get("title") or item.get("role") or item.get("designation") or ""
        company  = (item.get("company") or {}).get("name") or item.get("company_name") or ""
        location = item.get("location") or item.get("city") or "India"
        jd       = strip_html(item.get("description") or item.get("job_description") or "")
        slug     = item.get("slug") or item.get("id") or ""
        url      = f"https://www.instahyre.com/opportunity/{slug}" if slug else item.get("url", "")
        posted   = str(item.get("created_at") or item.get("posted_at") or "")[:10]
        exp      = str(item.get("experience") or item.get("exp_required") or "")

        if not role:
            continue
        if not matches_keywords(f"{role} {company} {jd[:300]}", keyword_terms):
            continue
        if not region_ok(location, focus):
            continue

        out.append(build_job(
            company=company,
            role=role,
            location=location,
            jd=jd,
            url=url,
            source="instahyre",
            posted=posted,
            exp=exp,
        ))
        if len(out) >= max_results:
            break

    print(f"[instahyre] {len(out)} jobs fetched", file=sys.stderr)
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer python", max_results=10, focus="india")
    print(f"instahyre: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:3], indent=2, ensure_ascii=False))
