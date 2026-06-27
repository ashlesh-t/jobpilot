"""Native Jobicy scraper — pure Python, NO LLM, NO Apify.

Jobicy exposes a clean JSON API: https://jobicy.com/api/v2/remote-jobs
Supports geo + tag filters. Fields: jobTitle, companyName, jobGeo, jobLevel,
jobExcerpt, jobDescription, url, pubDate.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

API = "https://jobicy.com/api/v2/remote-jobs"


def fetch(keywords="software engineer", location="", max_results=25, hours_old=None, focus="india"):
    keyword_terms = split_terms(keywords)
    # Jobicy's `geo` param has a fixed enum (no "india") and 400s on unknown values,
    # so we never send it — region_ok() post-filters by jobGeo instead.
    params = {"count": max(max_results, 50), "tag": "dev"}
    resp = http_get(API, params=params, timeout=25)
    if not resp:
        return []
    try:
        jobs_raw = resp.json().get("jobs", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in jobs_raw:
        geo = item.get("jobGeo", "") or "Anywhere"
        if not region_ok(geo, focus):
            continue
        jd = strip_html(item.get("jobDescription") or item.get("jobExcerpt", ""))
        role = item.get("jobTitle", "")
        if not matches_keywords(f"{role} {jd[:300]}", keyword_terms):
            continue
        out.append(build_job(
            company=item.get("companyName", ""),
            role=role,
            location=f"Remote ({geo})",
            jd=jd,
            url=item.get("url", ""),
            source="jobicy",
            posted=str(item.get("pubDate", ""))[:10],
            exp=item.get("jobLevel", ""),
        ))
        if len(out) >= max_results:
            break
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer", max_results=15, focus="both")
    print(f"jobicy: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
