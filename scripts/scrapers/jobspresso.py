"""Native Jobspresso scraper — pure Python, NO LLM, NO Apify.

Jobspresso publishes a standard WordPress job-listing RSS feed:
https://jobspresso.co/feed/?post_type=job_listing

Confirmed live shape: <title> is the role only (no company). Company name (and
sometimes a location, separated by a "<br>" + compass glyph) lives in the
<dc:creator> element instead — the standard WordPress "post author" field,
repurposed here as the employer name.
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

FEED_URL = "https://jobspresso.co/feed/?post_type=job_listing"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_SPLIT_RE = re.compile(r"<br\s*/?>|⚲")


def _split_creator(creator: str) -> tuple[str, str]:
    """dc:creator is "Company" or "Company<br>⚲ Location" — split on either marker."""
    parts = [p.strip(" ⌂⚲") for p in _SPLIT_RE.split(creator or "") if p.strip()]
    company = parts[0] if parts else ""
    location = parts[1] if len(parts) > 1 else ""
    return company, location


def fetch(keywords="software engineer", location="", max_results=25, hours_old=None, focus="india"):
    keyword_terms = split_terms(keywords)
    resp = http_get(FEED_URL, timeout=25)
    if not resp:
        return []
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        print(f"[jobspresso] XML parse error: {exc}", file=sys.stderr)
        return []

    out = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        creator_el = item.find(f"{{{_DC_NS}}}creator")
        desc_el = item.find("description")
        pub_el = item.find("pubDate")

        role = (title_el.text or "").strip() if title_el is not None else ""
        if not role:
            continue
        company, loc_text = _split_creator(creator_el.text if creator_el is not None else "")
        loc_text = loc_text or "Remote"
        if not region_ok(loc_text, focus):
            continue
        jd = strip_html((desc_el.text or "") if desc_el is not None else "")
        if not matches_keywords(f"{role} {jd[:400]}", keyword_terms):
            continue
        url = (link_el.text or "").strip() if link_el is not None else ""
        posted = ""
        if pub_el is not None and pub_el.text:
            try:
                posted = parsedate_to_datetime(pub_el.text).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                posted = ""

        out.append(build_job(
            company=company,
            role=role,
            location=loc_text,
            jd=jd,
            url=url,
            source="jobspresso",
            posted=posted,
        ))
        if len(out) >= max_results:
            break
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer", max_results=15, focus="both")
    print(f"jobspresso: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
