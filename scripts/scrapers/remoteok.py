"""Native RemoteOK scraper — pure Python, NO LLM, NO Apify.

RemoteOK exposes a clean public JSON feed at https://remoteok.com/api .
First element is metadata/legal notice; the rest are jobs.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

API = "https://remoteok.com/api"


def fetch(keywords="software engineer", location="", max_results=30, hours_old=None, focus="india"):
    keyword_terms = split_terms(keywords)
    resp = http_get(API, timeout=25)
    if not resp:
        return []
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in data:
        if not isinstance(item, dict) or not item.get("position"):
            continue  # skip the legal/metadata header element
        role = item.get("position", "")
        company = item.get("company", "")
        location = item.get("location") or "Remote"
        tags = item.get("tags") or []
        jd = strip_html(item.get("description", ""))
        # Match on the role TITLE only. RemoteOK's sponsored listings carry bloated,
        # unrelated tag lists (a "Water Safety Specialist" tagged 'engineer', 'golang'),
        # so matching tags/JD yields false positives. Real dev roles name it in the title.
        if not matches_keywords(role, keyword_terms):
            continue
        if not region_ok(f"remote {location}", focus):
            continue
        url = item.get("apply_url") or item.get("url") or ""
        sal = ""
        if item.get("salary_min"):
            sal = f" Salary: {item.get('salary_min')}-{item.get('salary_max', '')} USD"
        out.append(build_job(
            company=company, role=role, location=f"Remote ({location})" if location else "Remote",
            jd=(jd + sal).strip(), url=url, source="remoteok",
            posted=str(item.get("date", ""))[:10],
            exp=", ".join(tags[:6]),
        ))
        if len(out) >= max_results:
            break
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer python", max_results=15, focus="both")
    print(f"remoteok: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
