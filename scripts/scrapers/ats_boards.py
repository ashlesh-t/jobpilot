"""Native ATS-direct scraper — pure Python, NO LLM, NO Apify.

Hits the free, public, no-auth job-postings APIs six ATS platforms publish
directly, for whichever companies in config/target_companies.json have a
verified `ats`+`token` (never guessed — see that file's own note). This
replaces the slow, capped, LLM-token-costing WebFetch career-page crawl the
discover phase does for the same companies.

Company-driven, not keyword-driven: `keywords` only lightly filters, the real
selection is "does this company have a token configured". Each per-ATS fetch is
isolated in its own try/except — one company's ATS being down or renamed must
never take down the others.
"""
from __future__ import annotations

import html as _html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, region_ok, strip_html  # noqa: E402

TARGET_COMPANIES_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "target_companies.json"


def _load_companies() -> list[dict]:
    try:
        cfg = json.loads(TARGET_COMPANIES_PATH.read_text())
    except Exception:
        return []
    if not cfg.get("enabled", True):
        return []
    return [c for c in cfg.get("companies", []) if c.get("ats") and c.get("token")]


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _greenhouse_html(text: str) -> str:
    """Greenhouse's `content` field is HTML-escaped HTML (literal "&lt;h2&gt;"), so
    the tags must be unescaped before strip_html's tag-stripping regex can see them."""
    return strip_html(_html.unescape(text or ""))


def _fetch_greenhouse(token: str, company: str, focus: str, cap: int) -> list[dict]:
    resp = http_get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                    params={"content": "true"}, timeout=20)
    if not resp:
        return []
    try:
        jobs = resp.json().get("jobs", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in jobs:
        loc = (item.get("location") or {}).get("name", "")
        if not region_ok(loc, focus):
            continue
        out.append(build_job(
            company=company, role=item.get("title", ""), location=loc,
            jd=_greenhouse_html(item.get("content", "")),
            url=item.get("absolute_url", ""), source=f"direct-greenhouse-{_slug(company)}",
            posted=str(item.get("updated_at", ""))[:10],
        ))
        if len(out) >= cap:
            break
    return out


def _fetch_lever(token: str, company: str, focus: str, cap: int) -> list[dict]:
    resp = http_get(f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"}, timeout=20)
    if not resp:
        return []
    try:
        jobs = resp.json()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(jobs, list):
        return []
    out = []
    for item in jobs:
        loc = (item.get("categories") or {}).get("location", "")
        if not region_ok(loc, focus):
            continue
        posted_ms = item.get("createdAt")
        posted = ""
        if isinstance(posted_ms, (int, float)) and posted_ms > 0:
            from datetime import datetime, timezone
            posted = datetime.fromtimestamp(posted_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append(build_job(
            company=company, role=item.get("text", ""), location=loc,
            jd=item.get("descriptionPlain", "") or strip_html(item.get("description", "")),
            url=item.get("hostedUrl", ""), source=f"direct-lever-{_slug(company)}",
            posted=posted,
        ))
        if len(out) >= cap:
            break
    return out


def _fetch_ashby(token: str, company: str, focus: str, cap: int) -> list[dict]:
    resp = http_get(f"https://api.ashbyhq.com/posting-api/job-board/{token}",
                    params={"includeCompensation": "true"}, timeout=20)
    if not resp:
        return []
    try:
        jobs = resp.json().get("jobs", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in jobs:
        loc = item.get("location", "")
        if not region_ok(loc, focus):
            continue
        out.append(build_job(
            company=company, role=item.get("title", ""), location=loc,
            jd=item.get("descriptionPlain", "") or strip_html(item.get("descriptionHtml", "")),
            url=item.get("jobUrl", ""), source=f"direct-ashby-{_slug(company)}",
            posted=str(item.get("publishedAt", ""))[:10],
        ))
        if len(out) >= cap:
            break
    return out


def _fetch_workable(token: str, company: str, focus: str, cap: int) -> list[dict]:
    resp = http_get(f"https://apply.workable.com/api/v1/widget/accounts/{token}",
                    params={"details": "true"}, timeout=20)
    if not resp:
        return []
    try:
        jobs = resp.json().get("jobs", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in jobs:
        loc_obj = item.get("location") or {}
        loc = loc_obj.get("location_str") or ", ".join(
            filter(None, [loc_obj.get("city"), loc_obj.get("country")]))
        if not region_ok(loc, focus):
            continue
        jd = strip_html(item.get("full_description") or item.get("description") or "")
        out.append(build_job(
            company=company, role=item.get("title", ""), location=loc or "Unknown",
            jd=jd, url=item.get("url") or item.get("application_url", ""),
            source=f"direct-workable-{_slug(company)}",
        ))
        if len(out) >= cap:
            break
    return out


_FETCHERS = {
    "greenhouse": _fetch_greenhouse,
    "lever": _fetch_lever,
    "ashby": _fetch_ashby,
    "workable": _fetch_workable,
}


def fetch(keywords="", location="", max_results=100, hours_old=None, focus="india") -> list[dict]:
    companies = _load_companies()
    if not companies:
        return []
    per_company_cap = max(1, max_results // max(len(companies), 1)) or 20

    out = []
    for entry in companies:
        # Same convention the discover phase already uses: an "india"-tagged company
        # only matters for an india/both run, a "global"-tagged one for global/us/both.
        company_focus = entry.get("focus", "global")
        if focus != "both":
            if company_focus == "india" and focus != "india":
                continue
            if company_focus == "global" and focus not in ("global", "us"):
                continue
        ats = entry.get("ats")
        token = entry.get("token")
        fetcher = _FETCHERS.get(ats)
        if not fetcher or not token:
            continue
        try:
            jobs = fetcher(token, entry["name"], focus, per_company_cap)
            print(f"[ats_boards] {entry['name']} ({ats}): {len(jobs)} jobs", file=sys.stderr)
            out += jobs
        except Exception as exc:  # noqa: BLE001
            print(f"[ats_boards] {entry['name']} ({ats}) failed: {exc}", file=sys.stderr)
        if len(out) >= max_results:
            break
    return out[:max_results]


if __name__ == "__main__":
    jobs = fetch(max_results=50, focus="both")
    print(f"ats_boards: {len(jobs)} jobs total", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
