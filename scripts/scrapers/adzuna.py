"""Native Adzuna scraper — pure Python, NO LLM, NO Apify.

Official free API (developer.adzuna.com): 1,000 calls/month (~33/day) on the free
tier, so this is called at most once per run, not once per location. Degrades to
[] silently if ADZUNA_APP_ID/ADZUNA_APP_KEY aren't configured — same pattern as
Apify with no token.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/ — for jp_secrets
sys.path.insert(0, str(Path(__file__).resolve().parent))          # scrapers/ — for _common
from _common import build_job, http_get, region_ok, strip_html  # noqa: E402

BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


def _country_for(focus: str) -> str:
    if focus in ("india", "both"):
        return "in"
    if focus == "us":
        return "us"
    return "gb"


def fetch(keywords="software engineer", location="", max_results=25, hours_old=None, focus="india"):
    from jp_secrets import get_secret_optional  # noqa

    app_id = get_secret_optional("ADZUNA_APP_ID")
    app_key = get_secret_optional("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        return []  # not configured — a silent, expected degrade, not an error

    country = _country_for(focus)
    resp = http_get(
        BASE.format(country=country),
        params={
            "app_id": app_id, "app_key": app_key,
            "what": keywords, "where": location,
            "results_per_page": min(max_results, 50),
            "content-type": "application/json",
        },
        timeout=25,
    )
    if not resp:
        return []
    try:
        results = resp.json().get("results", [])
    except Exception:  # noqa: BLE001
        return []

    out = []
    for item in results:
        role = item.get("title", "")
        company = (item.get("company") or {}).get("display_name", "")
        if not role or not company:
            continue
        loc_text = (item.get("location") or {}).get("display_name", "") or "Unknown"
        if not region_ok(loc_text, focus):
            continue
        jd = strip_html(item.get("description", ""))
        sal_min, sal_max = item.get("salary_min"), item.get("salary_max")
        if sal_min and sal_max:
            jd = f"{jd}  Salary: {sal_min:.0f}-{sal_max:.0f}".strip()
        out.append(build_job(
            company=company,
            role=role,
            location=loc_text,
            jd=jd,
            url=item.get("redirect_url", ""),
            source="adzuna",
            posted=str(item.get("created", ""))[:10],
        ))
        if len(out) >= max_results:
            break
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer", max_results=10, focus="india")
    print(f"adzuna: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
