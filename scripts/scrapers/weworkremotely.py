"""Native WeWorkRemotely scraper — pure Python, NO LLM, NO Apify.

WWR publishes per-category RSS feeds (no auth). We parse the programming feeds.
<item> fields: title ("Company: Role"), region, category, description (HTML), link.
"""
from __future__ import annotations

import re
import sys
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402


def _iso_date(rfc822: str) -> str:
    """RFC-822 pubDate -> YYYY-MM-DD (empty string if unparseable)."""
    try:
        return parsedate_to_datetime(rfc822).strftime("%Y-%m-%d")
    except Exception:
        return ""

FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
]


def fetch(keywords="software engineer", location="", max_results=20, hours_old=None, focus="india"):
    keyword_terms = split_terms(keywords)
    out = []
    seen = set()
    for feed in FEEDS:
        resp = http_get(feed, timeout=25)
        if not resp:
            continue
        try:
            root = ET.fromstring(resp.content)
        except Exception:  # noqa: BLE001
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            region = (item.findtext("region") or "Anywhere").strip()
            desc = strip_html(item.findtext("description") or "")
            # "Company: Role" split
            if ":" in title:
                company, role = title.split(":", 1)
            else:
                company, role = "", title
            company, role = company.strip(), role.strip()
            if not matches_keywords(f"{role} {desc[:300]}", keyword_terms):
                continue
            if not region_ok(f"remote {region}", focus):
                continue
            if link in seen:
                continue
            seen.add(link)
            out.append(build_job(
                company=company or "WeWorkRemotely",
                role=role or "See post",
                location=f"Remote ({region})",
                jd=desc,
                url=link,
                source="weworkremotely",
                posted=_iso_date(item.findtext("pubDate") or ""),
            ))
            if len(out) >= max_results:
                return out
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer", max_results=15, focus="both")
    print(f"weworkremotely: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
