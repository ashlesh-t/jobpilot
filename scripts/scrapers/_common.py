"""Shared helpers for native scrapers — pure Python, NO LLM, NO Apify.

Every native scraper returns a list of dicts in the canonical JobPilot schema:

    {
      "job_id", "company", "role", "location", "experience_req",
      "jd_full", "application_url", "source_board", "posted_date",
      "last_date"   # application deadline (empty string = unknown)
    }

job_id uses the SAME hash as apify_scraper.make_job_id so native + Apify results
dedupe consistently in dedupe.py.
"""
from __future__ import annotations

import hashlib
import html as _html
import re
import sys
from datetime import datetime, timezone

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Location tokens that count as "open to an India-based candidate".
INDIA_OK_TOKENS = (
    "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "pune", "delhi",
    "chennai", "gurgaon", "gurugram", "noida", "kolkata", "ahmedabad", "remote",
    "anywhere", "worldwide", "world wide", "global", "asia",
)


def http_get(url, params=None, headers=None, timeout=20, retries=2):
    """GET with shared browser headers and light retry. Returns a Response or None."""
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    last = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            if resp.status_code == 200:
                return resp
            last = f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
    if last:
        print(f"[scraper] GET {url} failed: {last}", file=sys.stderr)
    return None


def make_job_id(company: str, role: str, location: str, source: str) -> str:
    """Identical to apify_scraper.make_job_id — keep in sync for cross-source dedup."""
    raw = f"{source}|{company}|{role}|{location}".lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def strip_html(text) -> str:
    """Remove tags + unescape entities + collapse whitespace."""
    if not text:
        return ""
    text = re.sub(r"(?is)<br\s*/?>", "\n", str(text))
    text = re.sub(r"(?is)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean(text) -> str:
    """Collapse whitespace in a short field (company/role/location)."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", _html.unescape(str(text))).strip()


def region_ok(location_text: str, focus: str) -> bool:
    """Whether a job is geographically relevant for the chosen market focus.

    - global / both: keep everything.
    - india: keep only jobs that name an Indian city, or are remote/worldwide/anywhere.
      This stops US/EU-only remote boards from flooding an India-first search.
    """
    if focus != "india":
        return True
    loc = (location_text or "").lower()
    if not loc:
        return True  # unknown location — keep, let later filters decide
    return any(tok in loc for tok in INDIA_OK_TOKENS)


def build_job(*, company, role, location, jd="", url="", source,
              posted="", exp="", last_date="") -> dict:
    """Assemble one normalized job dict (canonical JobPilot schema)."""
    company = clean(company)
    role = clean(role)
    location = clean(location) or "Unknown"
    board = clean(source) or "native"
    return {
        "job_id": make_job_id(company, role, location, board),
        "company": company,
        "role": role,
        "location": location,
        "experience_req": clean(exp),
        "jd_full": (jd or "").strip(),
        "application_url": clean(url),
        "source_board": board,
        "posted_date": clean(posted) or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "last_date": clean(last_date),
    }


# Generic noise words that pollute keyword matching (match "full-time", "tech stack",
# "entry-level", "0-2 years", etc.). Kept out of the matching term list.
_STOPTERMS = {
    "full", "stack", "new", "grad", "graduate", "entry", "level", "years", "year",
    "the", "and", "for", "with", "role", "roles", "type", "types",
}


def split_terms(keywords: str, limit: int = 8) -> list:
    """Meaningful, de-duplicated lowercase keyword terms for coarse pre-filtering."""
    terms = []
    for tok in re.split(r"[\s,/]+", (keywords or "").lower()):
        tok = tok.strip()
        if len(tok) > 2 and tok not in _STOPTERMS and tok not in terms:
            terms.append(tok)
    return terms[:limit]


def matches_keywords(text: str, keyword_terms) -> bool:
    """True if any keyword term appears in text (case-insensitive). Empty terms -> True."""
    if not keyword_terms:
        return True
    t = (text or "").lower()
    return any(k.lower() in t for k in keyword_terms if k)
