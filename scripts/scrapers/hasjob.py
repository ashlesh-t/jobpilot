"""Native Hasjob scraper — pure Python, NO LLM, NO Apify.

Hasjob (hasjob.co) is an India-focused tech job board with a public JSON API.
Endpoint: https://hasjob.co/api/1/jobs (paginated, no auth required).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

_ENDPOINTS = [
    "https://hasjob.co/api/1/jobs",
    "https://hasjob.co/api/jobs",
    "https://hasjob.co/search.json",
]


def fetch(keywords="software engineer", max_results=25, focus="both"):
    if focus == "global":
        print("[hasjob] India-only board — skipping for global-only focus", file=sys.stderr)
        return []

    keyword_terms = split_terms(keywords)
    params = {"q": keywords, "l": "", "page": 1}
    resp = None
    for endpoint in _ENDPOINTS:
        resp = http_get(endpoint, params=params, timeout=20)
        if resp and resp.status_code == 200:
            break
        resp = None
    if not resp:
        return []

    try:
        data = resp.json()
    except Exception:
        print("[hasjob] API did not return JSON — skipping", file=sys.stderr)
        return []

    jobs_raw = data if isinstance(data, list) else data.get("jobs", data.get("results", []))
    out = []
    for item in jobs_raw:
        if not isinstance(item, dict):
            continue
        role     = item.get("headline") or item.get("title") or item.get("position") or ""
        company  = item.get("company") or item.get("org") or item.get("employer") or ""
        location = item.get("location") or item.get("city") or "India"
        jd       = strip_html(item.get("description") or item.get("text") or "")
        url      = item.get("url") or item.get("apply_url") or item.get("link") or ""
        posted   = str(item.get("posted_at") or item.get("created") or "")[:10]

        if not role:
            continue
        if not matches_keywords(f"{role} {company} {jd[:300]}", keyword_terms):
            continue
        if not region_ok(location, focus):
            continue

        out.append(build_job(
            company=company,
            role=role,
            location=location or "India",
            jd=jd,
            url=url,
            source="hasjob",
            posted=posted,
        ))
        if len(out) >= max_results:
            break

    print(f"[hasjob] {len(out)} jobs fetched", file=sys.stderr)
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer python", max_results=10, focus="india")
    print(f"hasjob: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:3], indent=2, ensure_ascii=False))
