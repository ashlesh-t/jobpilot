"""Native Wellfound public scraper — pure Python, NO LLM, NO Apify.

Wellfound (wellfound.com, formerly AngelList) exposes a public job search
without auth for basic listing. This scraper uses their public JSON search
endpoint (no Cloudflare session needed for the initial listing page).

Note: The Apify actor (blackfalcondata/wellfound-scraper) handles full JD
extraction and Cloudflare-protected pages. This scraper covers only the
basic public listing for when Apify is unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

# Wellfound's public job search — returns JSON with Accept: application/json
API = "https://wellfound.com/l/2bbpk"
SEARCH_API = "https://wellfound.com/jobs"


def fetch(keywords="software engineer", max_results=20, focus="both"):
    keyword_terms = split_terms(keywords)
    params = {"q": keywords}
    if focus == "india":
        params["locations[]"] = "India"

    resp = http_get(
        SEARCH_API,
        params=params,
        headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        timeout=25,
    )
    if not resp:
        return []

    try:
        data = resp.json()
    except Exception:
        print("[wellfound_rss] Public endpoint did not return JSON — skipping", file=sys.stderr)
        return []

    jobs_raw = (
        data.get("jobs")
        or data.get("results")
        or data.get("jobListings")
        or (data if isinstance(data, list) else [])
    )
    out = []
    for item in jobs_raw:
        if not isinstance(item, dict):
            continue
        role     = item.get("title") or item.get("role") or ""
        company  = (item.get("startup") or item.get("company") or {})
        if isinstance(company, dict):
            company = company.get("name") or company.get("company_name") or ""
        location = item.get("location") or item.get("locationNames") or "Remote"
        if isinstance(location, list):
            location = ", ".join(location)
        jd       = strip_html(item.get("description") or item.get("jobDescription") or "")
        url      = item.get("url") or item.get("jobUrl") or item.get("applyUrl") or ""
        posted   = str(item.get("liveStartAt") or item.get("postedAt") or "")[:10]

        if not role:
            continue
        if not matches_keywords(f"{role} {jd[:400]}", keyword_terms):
            continue
        if not region_ok(str(location), focus):
            continue

        out.append(build_job(
            company=str(company),
            role=role,
            location=str(location),
            jd=jd,
            url=url,
            source="wellfound_rss",
            posted=posted,
        ))
        if len(out) >= max_results:
            break

    print(f"[wellfound_rss] {len(out)} jobs fetched", file=sys.stderr)
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer python", max_results=10, focus="both")
    print(f"wellfound_rss: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:3], indent=2, ensure_ascii=False))
