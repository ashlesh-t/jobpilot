"""Native SimplifyJobs scraper — pure Python, NO LLM, NO Apify.

SimplifyJobs (github.com/SimplifyJobs) publishes a community + auto-maintained
`listings.json` for new-grad and internship roles — free, no auth, updated
hourly/daily. Ideal for a fresher/entry-level search. The file is large (~12 MB,
~18k entries including historical/inactive ones), so this scraper filters
aggressively before building job dicts.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms  # noqa: E402

# Both repos share the exact same listings.json shape (SimplifyJobs org convention).
FEEDS = {
    "new-grad": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
    "internships": "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
}


def _fetch_feed(url: str, keyword_terms, focus: str, max_results: int) -> list[dict]:
    # The file is ~12 MB — needs a longer timeout than the usual small JSON APIs.
    resp = http_get(url, timeout=45, retries=1)
    if not resp:
        return []
    try:
        entries = resp.json()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(entries, list):
        return []

    out = []
    for item in entries:
        if not isinstance(item, dict) or not item.get("active", False):
            continue
        role = item.get("title", "")
        company = item.get("company_name", "")
        if not role or not company:
            continue
        locations = item.get("locations") or []
        location = ", ".join(locations) if isinstance(locations, list) else str(locations)
        if not region_ok(location, focus):
            continue
        if not matches_keywords(f"{role} {company}", keyword_terms):
            continue
        posted_ts = item.get("date_posted")
        posted = ""
        if isinstance(posted_ts, (int, float)) and posted_ts > 0:
            posted = datetime.fromtimestamp(posted_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        sponsorship = item.get("sponsorship") or ""
        jd = f"Sponsorship: {sponsorship}" if sponsorship else ""
        out.append(build_job(
            company=company,
            role=role,
            location=location,
            jd=jd,
            url=item.get("url", ""),
            source="simplify-jobs",
            posted=posted,
        ))
        if len(out) >= max_results:
            break
    return out


def fetch(keywords="software engineer", location="", max_results=25, hours_old=None, focus="india"):
    keyword_terms = split_terms(keywords)
    out: list[dict] = []
    for label, url in FEEDS.items():
        remaining = max_results - len(out)
        if remaining <= 0:
            break
        try:
            out += _fetch_feed(url, keyword_terms, focus, remaining)
        except Exception as exc:  # noqa: BLE001
            print(f"[simplify_jobs] {label} feed failed: {exc}", file=sys.stderr)
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer backend", max_results=15, focus="both")
    print(f"simplify_jobs: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
