"""Native Himalayas scraper — pure Python, NO LLM, NO Apify.

Himalayas exposes a free public JSON API, no auth: https://himalayas.app/jobs/api
Fields (confirmed live): title, companyName, locationRestrictions (list),
description (HTML), applicationLink, pubDate (unix seconds).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

API = "https://himalayas.app/jobs/api"


def fetch(keywords="software engineer", location="", max_results=25, hours_old=None, focus="india"):
    keyword_terms = split_terms(keywords)
    resp = http_get(API, params={"limit": max(max_results * 2, 50), "offset": 0}, timeout=25)
    if not resp:
        return []
    try:
        jobs_raw = resp.json().get("jobs", [])
    except Exception:  # noqa: BLE001
        return []

    out = []
    for item in jobs_raw:
        role = item.get("title", "")
        company = item.get("companyName", "")
        if not role or not company:
            continue
        restrictions = item.get("locationRestrictions") or []
        loc_text = ", ".join(restrictions) if isinstance(restrictions, list) else str(restrictions)
        loc_text = loc_text or "Worldwide"
        if not region_ok(loc_text, focus):
            continue
        jd = strip_html(item.get("description", "") or item.get("excerpt", ""))
        if not matches_keywords(f"{role} {jd[:400]}", keyword_terms):
            continue
        posted_ts = item.get("pubDate")
        posted = ""
        if isinstance(posted_ts, (int, float)) and posted_ts > 0:
            posted = datetime.fromtimestamp(posted_ts, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append(build_job(
            company=company,
            role=role,
            location=f"Remote ({loc_text})",
            jd=jd,
            url=item.get("applicationLink", ""),
            source="himalayas",
            posted=posted,
        ))
        if len(out) >= max_results:
            break
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("backend engineer", max_results=15, focus="both")
    print(f"himalayas: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
