"""Native Hasjob scraper — pure Python, NO LLM, NO Apify.

Hasjob (hasjob.co) is an India-focused tech job board. The old JSON API
endpoints (/api/1/jobs, /api/jobs, /search.json) all return 404 as of 2026.
The working source is the public Atom feed at https://hasjob.co/feed which
returns recent listings in RSS/Atom XML format.

Parsing uses Python's built-in xml.etree.ElementTree — no external deps.
"""
from __future__ import annotations

import html
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

_FEED_URL = "https://hasjob.co/feed"
_ATOM_NS = "http://www.w3.org/2005/Atom"


def _unescape(text: str) -> str:
    return html.unescape(text or "")


def _extract_company_from_content(html_text: str) -> str:
    """Extract company name from the Atom content HTML.

    Hasjob content starts with:
      <p><strong><a href="...">Company Name</a></strong><br/>Location</p>
    """
    m = re.search(r"<strong>(?:<a[^>]*>)?([^<]+)(?:</a>)?</strong>", html_text)
    if m:
        return _unescape(m.group(1)).strip()
    return ""


def _parse_feed(xml_text: str) -> list[dict]:
    """Parse an Atom feed and return a list of raw entry dicts."""
    entries = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        print(f"[hasjob] XML parse error: {exc}", file=sys.stderr)
        return entries

    ns = {"a": _ATOM_NS}
    for entry in root.findall("a:entry", ns):
        title_el = entry.find("a:title", ns)
        link_el = entry.find("a:link", ns)
        loc_el = entry.find("a:location", ns)
        pub_el = entry.find("a:published", ns)
        content_el = entry.find("a:content", ns)

        raw_title = _unescape((title_el.text or "") if title_el is not None else "")
        url = (link_el.attrib.get("href", "") if link_el is not None else "")
        location = _unescape((loc_el.text or "") if loc_el is not None else "India")
        published = ((pub_el.text or "")[:10] if pub_el is not None else "")
        content_raw = (content_el.text or "") if content_el is not None else ""
        jd_html = _unescape(content_raw)
        jd = strip_html(jd_html)

        # Prefer company from HTML content (more reliable than title split)
        company = _extract_company_from_content(content_raw)

        # Title format may be "Job Role - Company Name" or just "Job Role"
        if not company and " - " in raw_title:
            role, company = raw_title.rsplit(" - ", 1)
        else:
            role = raw_title

        entries.append({
            "role": role.strip(),
            "company": company.strip(),
            "location": location.strip() or "India",
            "url": url,
            "posted": published,
            "jd": jd,
        })
    return entries


def fetch(keywords="software engineer", max_results=25, focus="both"):
    if focus == "global":
        print("[hasjob] India-only board — skipping for global-only focus", file=sys.stderr)
        return []

    keyword_terms = split_terms(keywords)
    resp = http_get(_FEED_URL, timeout=20)
    if not resp or resp.status_code != 200:
        print(f"[hasjob] Feed unavailable (status={getattr(resp, 'status_code', 'N/A')})",
              file=sys.stderr)
        return []

    raw_entries = _parse_feed(resp.text)
    out = []
    for item in raw_entries:
        if not item["role"]:
            continue
        if not matches_keywords(f"{item['role']} {item['company']} {item['jd'][:300]}",
                                keyword_terms):
            continue
        if not region_ok(item["location"], focus):
            continue

        out.append(build_job(
            company=item["company"],
            role=item["role"],
            location=item["location"],
            jd=item["jd"],
            url=item["url"],
            source="hasjob",
            posted=item["posted"],
        ))
        if len(out) >= max_results:
            break

    print(f"[hasjob] {len(raw_entries)} feed entries → {len(out)} matched", file=sys.stderr)
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software engineer python", max_results=10, focus="india")
    print(f"hasjob: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:3], indent=2, ensure_ascii=False))
