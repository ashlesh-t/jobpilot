"""Native Arbeitnow scraper — pure Python, NO LLM, NO Apify.

Arbeitnow exposes a clean JSON board: https://www.arbeitnow.com/api/job-board-api
Fields: title, company_name, location, remote (bool), description, url, tags.
Mostly EU/remote — for india focus, region_ok keeps only India/remote/worldwide roles.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

API = "https://www.arbeitnow.com/api/job-board-api"


def fetch(keywords="software engineer", location="", max_results=20, hours_old=None, focus="india"):
    keyword_terms = split_terms(keywords)
    resp = http_get(API, timeout=25)
    if not resp:
        return []
    try:
        data = resp.json().get("data", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in data:
        role = item.get("title", "")
        jd = strip_html(item.get("description", ""))
        tags = item.get("tags") or []
        if not matches_keywords(f"{role} {' '.join(tags)} {jd[:300]}", keyword_terms):
            continue
        loc = item.get("location", "") or ""
        is_remote = bool(item.get("remote"))
        loc_label = f"Remote ({loc})" if is_remote else (loc or "Unknown")
        if not region_ok(loc_label if not is_remote else f"remote {loc}", focus):
            continue
        out.append(build_job(
            company=item.get("company_name", ""),
            role=role,
            location=loc_label,
            jd=jd,
            url=item.get("url", ""),
            source="arbeitnow",
            posted=str(item.get("created_at", ""))[:10],
            exp=", ".join((item.get("job_types") or [])[:4]),
        ))
        if len(out) >= max_results:
            break
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer", max_results=15, focus="both")
    print(f"arbeitnow: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
