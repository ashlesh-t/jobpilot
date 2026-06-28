"""Native YC Work at a Startup scraper — pure Python, NO LLM, NO Apify.

Fetches engineering job listings from https://www.workatastartup.com using
their public company search API (no auth required).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

API = "https://www.workatastartup.com/companies"


def fetch(keywords="software engineer", max_results=30, focus="both"):
    keyword_terms = split_terms(keywords)
    params = {
        "demographic": "",
        "has_jobs": "true",
        "query": keywords,
        "remote": "true",
        "roles": "eng",
        "layout": "list-compact",
    }
    resp = http_get(API, params=params, headers={"Accept": "application/json"}, timeout=30)
    if not resp:
        return []

    try:
        data = resp.json()
    except Exception:
        print("[yc] API did not return JSON — skipping", file=sys.stderr)
        return []

    # Response shape: {"companies": [{"name", "jobs": [{"title", "location", "url", "description"}]}]}
    companies = data if isinstance(data, list) else data.get("companies", [])
    out = []
    for company in companies:
        if not isinstance(company, dict):
            continue
        company_name = company.get("name") or company.get("company_name") or ""
        jobs = company.get("jobs") or []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            role = job.get("title") or job.get("role") or ""
            location = job.get("location") or "Remote"
            jd = strip_html(job.get("description") or job.get("job_description") or "")
            url = job.get("url") or job.get("apply_url") or ""
            if not role:
                continue
            if not matches_keywords(f"{role} {jd[:400]}", keyword_terms):
                continue
            if not region_ok(location, focus):
                continue
            out.append(build_job(
                company=company_name,
                role=role,
                location=location,
                jd=jd,
                url=url,
                source="yc_startup",
                posted=job.get("created_at", "")[:10],
            ))
            if len(out) >= max_results:
                return out

    print(f"[yc] {len(out)} jobs fetched", file=sys.stderr)
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer python", max_results=10, focus="both")
    print(f"yc_startup: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:3], indent=2, ensure_ascii=False))
