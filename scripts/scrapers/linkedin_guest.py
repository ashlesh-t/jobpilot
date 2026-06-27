"""Native LinkedIn guest API scraper — pure Python, NO LLM, NO Apify.

Uses LinkedIn's public (unauthenticated) job search API endpoint.
Returns job title, company, location, and apply URL — NO full JD.
All results have has_jd=False; Claude scores on title+company only.

Rate-limited to 3 pages max with 2s sleep between pages.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, split_terms, strip_html  # noqa: E402

ENDPOINT = (
    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
)

# Extra headers that help avoid soft-blocking on this endpoint.
_EXTRA_HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Referer": "https://www.linkedin.com/jobs/search/",
}


def _parse_cards(html: str) -> list[dict]:
    """Extract raw job fields from the HTML fragment LinkedIn returns."""
    jobs = []
    # Each job is an <li> containing a job card div.
    cards = re.findall(r"<li>(.*?)</li>", html, re.S)
    for card in cards:
        # Entity URN → unique job ID from LinkedIn
        m_urn = re.search(r'data-entity-urn="urn:li:jobPosting:(\d+)"', card)
        if not m_urn:
            continue
        job_id_li = m_urn.group(1)

        m_title = re.search(
            r'class="base-search-card__title"[^>]*>(.*?)</h3>', card, re.S
        ) or re.search(r'class="[^"]*job-title[^"]*"[^>]*>(.*?)</[^>]+>', card, re.S)
        role = strip_html(m_title.group(1)) if m_title else ""

        m_company = re.search(
            r'class="[^"]*base-search-card__subtitle[^"]*"[^>]*>(.*?)</[^>]+>', card, re.S
        ) or re.search(r'class="[^"]*company[^"]*"[^>]*>(.*?)</[^>]+>', card, re.S)
        company = strip_html(m_company.group(1)) if m_company else ""

        m_loc = re.search(
            r'class="[^"]*job-search-card__location[^"]*"[^>]*>(.*?)</span>', card, re.S
        ) or re.search(r'class="[^"]*location[^"]*"[^>]*>(.*?)</span>', card, re.S)
        location = strip_html(m_loc.group(1)) if m_loc else ""

        m_url = re.search(r'href="(https://[^"]*linkedin\.com/jobs/view/[^"?]+)', card)
        url = m_url.group(1).split("?")[0] if m_url else (
            f"https://www.linkedin.com/jobs/view/{job_id_li}"
        )

        m_date = re.search(r'datetime="([^"]+)"', card)
        posted = m_date.group(1)[:10] if m_date else ""

        if not role or not company:
            continue

        jobs.append({
            "_li_id": job_id_li,
            "role": role,
            "company": company,
            "location": location,
            "url": url,
            "posted": posted,
        })
    return jobs


def fetch(keywords: str = "", location: str = "Bengaluru",
          max_results: int = 25, hours_old: int = 24,
          focus: str = "india") -> list[dict]:
    """Return up to max_results LinkedIn jobs (no JD — title/company/location/URL only).

    Never raises. Rate-limited to 3 pages × 25 results = 75 max.
    """
    keyword_terms = split_terms(keywords)
    # Time filter: r86400 = last 24h, r604800 = last 7 days
    time_filter = "r86400" if hours_old <= 24 else "r604800"

    out: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(3):
        params = {
            "keywords": keywords,
            "location": location,
            "start": page * 25,
            "f_TPR": time_filter,
            "f_JT": "F",        # full-time only
        }
        resp = http_get(ENDPOINT, params=params, headers=_EXTRA_HEADERS, timeout=20)
        if not resp or not resp.text.strip():
            break

        cards = _parse_cards(resp.text)
        if not cards:
            break  # LinkedIn returned empty page — stop paginating

        for c in cards:
            li_id = c["_li_id"]
            if li_id in seen_ids:
                continue
            if not matches_keywords(c["role"], keyword_terms):
                continue
            seen_ids.add(li_id)

            job = build_job(
                company=c["company"],
                role=c["role"],
                location=c["location"] or location,
                jd="",
                url=c["url"],
                source="linkedin-guest",
                posted=c["posted"],
            )
            # Override has_jd — LinkedIn guest never returns a description.
            job["has_jd"] = False
            out.append(job)

            if len(out) >= max_results:
                return out

        if page < 2:
            time.sleep(2)  # be polite — LinkedIn soft-blocks aggressive scrapers

    return out


if __name__ == "__main__":
    import json as _json
    results = fetch("software engineer backend", "Bengaluru", max_results=10)
    print(f"linkedin_guest: {len(results)} jobs", file=sys.stderr)
    print(_json.dumps(results[:3], indent=2, ensure_ascii=False))
