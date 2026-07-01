"""Native YC startup jobs scraper — pure Python, NO LLM, NO Apify.

YC Work at a Startup (workatastartup.com) is a React SPA backed by Algolia
search with a restricted API key — it is not scrapeable without a valid
authenticated session.

Fallback approach: HN Firebase Jobs API
  https://hacker-news.firebaseio.com/v0/jobstories.json
Returns HN job posts from YC-affiliated startups. Each item has a direct
apply URL and a description in the `text` field. Returns ~30 recent posts
at any given time, all from real YC-backed companies.
"""
from __future__ import annotations

import html as _html_mod
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, matches_keywords, region_ok, split_terms  # noqa: E402

_JOBSTORIES_URL = "https://hacker-news.firebaseio.com/v0/jobstories.json"
_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"

_YC_BATCH_RE = re.compile(r"\(YC\s+[WSF]\d{2}\)", re.I)


def _strip_hn_html(text: str) -> str:
    text = _html_mod.unescape(text or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _parse_hn_job(item: dict) -> dict | None:
    """Extract company, role, location from an HN job story."""
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    text = _strip_hn_html(item.get("text") or "")
    posted_ts = item.get("time", 0)

    if not title:
        return None

    company = ""
    role = ""
    location = "Remote"

    # Pattern: "Company (YC S24) is hiring <Role>" — most common HN job title format
    m_hiring = re.search(
        r"^(.+?)\s*(?:\(YC\s+[WSF]\d{2,4}\))?\s+[Ii]s\s+[Hh]iring\s+(?:a\s+|an\s+)?(.+?)(?:\s*[—\-]\s*|\s*\|.*|$)",
        title, re.I,
    )
    if m_hiring:
        company = m_hiring.group(1).strip()
        role = m_hiring.group(2).strip()
    else:
        # Fallback: "Company — Role" or "Company - Role" or "Company | Role"
        for sep in (" — ", " – ", " | ", " - "):
            if sep in title:
                parts = title.split(sep, 1)
                company = _YC_BATCH_RE.sub("", parts[0]).strip()
                role = parts[1].strip()
                break

    # Last resort: treat whole title as company, use generic role
    if not company:
        company = _YC_BATCH_RE.sub("", title).strip()
        company = re.sub(r"\s+[Ii]s\s+[Hh]iring.*$", "", company).strip()
    if not role:
        role = "Software Engineer"

    # Remove any remaining YC batch markers from company
    company = _YC_BATCH_RE.sub("", company).strip()

    # Posted date from Unix timestamp
    from datetime import datetime, timezone
    posted = datetime.fromtimestamp(posted_ts, tz=timezone.utc).strftime("%Y-%m-%d") if posted_ts else ""

    return {
        "company": company[:80],
        "role": role[:100],
        "location": location,
        "jd": text[:800],
        "url": url,
        "posted": posted,
    }


def fetch(keywords="software engineer", max_results=30, focus="both"):
    keyword_terms = split_terms(keywords)

    try:
        resp = requests.get(_JOBSTORIES_URL, timeout=15)
        if resp.status_code != 200:
            print(f"[yc] HN jobstories API returned {resp.status_code} — skipping",
                  file=sys.stderr)
            return []
        story_ids = resp.json()
    except Exception as exc:
        print(f"[yc] Failed to fetch job story IDs: {exc}", file=sys.stderr)
        return []

    out = []
    fetched = 0
    for story_id in story_ids:
        if len(out) >= max_results:
            break
        try:
            item_resp = requests.get(_ITEM_URL.format(story_id), timeout=10)
            if item_resp.status_code != 200:
                continue
            item = item_resp.json()
            fetched += 1
        except Exception:
            continue

        parsed = _parse_hn_job(item)
        if not parsed:
            continue

        if not matches_keywords(
            f"{parsed['role']} {parsed['company']} {parsed['jd'][:300]}", keyword_terms
        ):
            continue
        if not region_ok(parsed["location"], focus):
            continue

        out.append(build_job(
            company=parsed["company"],
            role=parsed["role"],
            location=parsed["location"],
            jd=parsed["jd"],
            url=parsed["url"],
            source="yc_startup",
            posted=parsed["posted"],
        ))

    print(f"[yc] {fetched} HN job stories fetched → {len(out)} matched", file=sys.stderr)
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer python", max_results=10, focus="both")
    print(f"yc_startup: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:3], indent=2, ensure_ascii=False))
