"""Native Internshala scraper — pure Python, NO LLM, NO Apify.

Internshala has no clean JSON API, but its public listing pages are server-rendered
with stable job cards. We parse those directly. India full-time "jobs" (not
internships) are the default; freshers are the target audience.

Verified card structure (2026-06) — anchored on stable class names, NOT the
`<!-- ... -->` comment markers (their closing markers are absent on city pages):
  <div class="... individual_internship_<id>" internshipId="<id>" employment_type="job"
       data-href='/job/detail/<slug>'>
    <a class="job-title-href" id="job_title">TITLE</a>
    <p class="company-name"> COMPANY </p>
    <p class="row-1-item locations"><span><a>Bangalore</a></span></p>
    <div class="row-1-item"><i class="ic-16-money"></i><span class="desktop">₹ ...</span></div>
    <div class="row-1-item"><i class="ic-16-briefcase"></i><span>1 year(s)</span></div>
    <div class="about_job">...<div class="text">JD…</div></div>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, region_ok, split_terms, strip_html  # noqa: E402

BASE = "https://internshala.com"

# Map role signals -> Internshala category slugs. software-development is the broad
# default and is checked first so a mixed "SWE/Backend/ML-AI" search doesn't get
# narrowed to ML. A secondary ML/data category is added by category_slugs() when
# those signals are present.
SOFTWARE_SIGNALS = ("swe", "software", "backend", "back end", "full stack", "fullstack",
                    "developer", "engineer", "java", "python", "golang", "node", "web",
                    "frontend", "front end")
SECONDARY_MAP = [
    (("machine learning", "ml-ai", "ml/ai", " ml ", "deep learning", "computer vision",
      "nlp", "ai engineer", "ai/ml"), "machine-learning"),
    (("data scien", "data analyst", "data engineer", "analytics"), "data-science"),
    (("devops", "sre", "infrastructure", "cloud"), "devops"),
]


def category_slugs(keywords: str) -> list:
    """Ordered, de-duplicated Internshala category slugs for a keyword blob."""
    kw = f" {(keywords or '').lower()} "
    slugs = []
    if any(s in kw for s in SOFTWARE_SIGNALS) or True:  # always include the broad category
        slugs.append("software-development")
    for needles, slug in SECONDARY_MAP:
        if any(n in kw for n in needles) and slug not in slugs:
            slugs.append(slug)
    return slugs


def _city_slug(location: str) -> str:
    loc = (location or "").lower().strip()
    aliases = {"bengaluru": "bangalore", "gurugram": "gurgaon"}
    loc = aliases.get(loc, loc)
    return re.sub(r"[^a-z0-9]+", "-", loc).strip("-")


def _parse_cards(html: str, keyword_terms, employment_filter):
    jobs = []
    seen_ids = set()
    boundaries = [m.start() for m in re.finditer(r'individual_internship_\d+"', html)]
    for idx, start in enumerate(boundaries):
        end = boundaries[idx + 1] if idx + 1 < len(boundaries) else len(html)
        card = html[start:end]

        m_id = re.search(r'individual_internship_(\d+)"', card)
        iid = m_id.group(1) if m_id else None
        if not iid or iid in seen_ids:
            continue

        m_emp = re.search(r'employment_type="(\w+)"', card)
        emp = (m_emp.group(1) if m_emp else "job").lower()
        if employment_filter and emp not in employment_filter:
            continue

        m_href = re.search(r"data-href=['\"]([^'\"]+)['\"]", card)
        href = m_href.group(1) if m_href else f"/job/detail/{iid}"
        url = href if href.startswith("http") else BASE + href

        m_title = re.search(r'id="job_title"[^>]*>(.*?)</a>', card, re.S) or \
            re.search(r'job-title-href[^>]*>(.*?)</a>', card, re.S)
        title = strip_html(m_title.group(1)) if m_title else ""

        m_comp = re.search(r'company-name[^>]*>(.*?)</', card, re.S)
        company = strip_html(m_comp.group(1)) if m_comp else ""

        # Location: the <p class="... locations"> element (close comment markers are
        # not present on city pages, so anchor on the stable class instead).
        m_loc = re.search(r'class="[^"]*\blocations\b[^"]*">(.*?)</p>', card, re.S)
        loc_inner = m_loc.group(1) if m_loc else ""
        locs = re.findall(r"<a[^>]*>(.*?)</a>", loc_inner, re.S) or \
            re.findall(r"<span[^>]*>(.*?)</span>", loc_inner, re.S)
        location = ", ".join(strip_html(x) for x in locs if strip_html(x)) or "India"

        # Salary: the row item carrying the money icon, prefer the desktop span.
        m_sal = re.search(r'ic-16-money.*?<span class="desktop">(.*?)</span>', card, re.S) or \
            re.search(r'ic-16-money.*?<span[^>]*>(.*?)</span>', card, re.S)
        salary = strip_html(m_sal.group(1)) if m_sal else ""

        # Experience: the row item carrying the briefcase icon.
        m_exp = re.search(r'ic-16-briefcase.*?<span[^>]*>(.*?)</span>', card, re.S)
        experience = strip_html(m_exp.group(1)) if m_exp else ""

        # Deadline: calendar icon or "apply by" / "last date" text.
        m_deadline = (
            re.search(r'ic-16-calendar.*?<span[^>]*>(.*?)</span>', card, re.S)
            or re.search(r'(?:apply\s+by|last\s+date)\s*[:\-]\s*([^<\n]{4,30})', card, re.I)
        )
        last_date = strip_html(m_deadline.group(1)).strip() if m_deadline else ""

        m_about = re.search(r'about_job.*?<div class="text">(.*?)</div>', card, re.S)
        jd = strip_html(m_about.group(1))[:800] if m_about else ""
        jd_parts = [p for p in (jd, f"Salary: {salary}" if salary else "",
                                f"Experience: {experience}" if experience else "") if p]
        jd_full = "  ".join(jd_parts)

        if not title or not company:
            continue
        if not matches_keywords(f"{title} {jd_full}", keyword_terms):
            continue

        seen_ids.add(iid)
        jobs.append(build_job(
            company=company, role=title, location=location, jd=jd_full,
            url=url, source="internshala", exp=experience, last_date=last_date,
        ))
    return jobs


def fetch(keywords="software developer", location="", max_results=40, hours_old=None,
          include_internships=False, focus="india", categories=None):
    """Return up to `max_results` Internshala job dicts across the relevant categories.

    Never raises. When `location` is given, results are scoped to that city via the
    `-in-<city>` URL; otherwise the all-India category page is used.
    """
    keyword_terms = split_terms(keywords)
    employment_filter = {"job"} if not include_internships else {"job", "internship"}
    slugs = categories or category_slugs(keywords)
    city = _city_slug(location)

    out = []
    seen_ids = set()
    per_slug = max(8, max_results // max(1, len(slugs)))
    for slug in slugs:
        paths = ([f"/jobs/{slug}-jobs-in-{city}"] if city else []) + [f"/jobs/{slug}-jobs"]
        got = 0
        for path in paths:
            if got >= per_slug:
                break
            for page in (1, 2):
                url = f"{BASE}{path}" + (f"/page-{page}" if page > 1 else "") + "/"
                resp = http_get(url, timeout=20)
                if not resp:
                    continue
                for job in _parse_cards(resp.text, keyword_terms, employment_filter):
                    if job["job_id"] in seen_ids:
                        continue
                    if not region_ok(job["location"], focus):
                        continue
                    seen_ids.add(job["job_id"])
                    out.append(job)
                    got += 1
                    if len(out) >= max_results:
                        return out
                    if got >= per_slug:
                        break
    return out


if __name__ == "__main__":
    import json
    jobs = fetch("software developer backend", "Bengaluru", max_results=20)
    print(f"internshala: {len(jobs)} jobs", file=sys.stderr)
    print(json.dumps(jobs[:5], indent=2, ensure_ascii=False))
