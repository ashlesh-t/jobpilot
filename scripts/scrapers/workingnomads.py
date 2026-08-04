"""Native WorkingNomads scraper — pure Python, NO LLM, NO Apify.

Free JSON API, no auth: https://www.workingnomads.com/api/exposed_jobs/
(note: the .co domain 301-redirects to .com — call .com directly).
Response is a bare array. Fields (confirmed live): title, company_name,
category_name, tags, location, description, pub_date, url.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

API = "https://www.workingnomads.com/api/exposed_jobs/"


def fetch(keywords="software engineer", location="", max_results=25, hours_old=None, focus="india"):
    keyword_terms = split_terms(keywords)
    resp = http_get(API, timeout=25)
    if not resp:
        return []
    try:
        jobs_raw = resp.json()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(jobs_raw, list):
        return []

    out = []
    for item in jobs_raw:
        if not isinstance(item, dict):
            continue
        role = item.get("title", "")
        company = item.get("company_name", "")
        if not role or not company:
            continue
        loc_text = item.get("location") or "Worldwide"
        if not region_ok(loc_text, focus):
            continue
        jd = strip_html(item.get("description", ""))
        tags = item.get("tags", "")
        text_for_match = f"{role} {tags} {jd[:400]}"
        if not matches_keywords(text_for_match, keyword_terms):
            continue
        out.append(build_job(
            company=company,
            role=role,
            location=f"Remote ({loc_text})",
            jd=jd,
            url=item.get("url", ""),
            source="workingnomads",
            posted=str(item.get("pub_date", ""))[:10],
        ))
        if len(out) >= max_results:
            break
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("backend developer", max_results=15, focus="both")
    print(f"workingnomads: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
