"""Layer A scraper — pure Python, NO LLM.

Hybrid scraping:
  • NATIVE scrapers (scripts/scrapers/*) — free, no Apify. Cover Internshala (India
    freshers) and the remote JSON boards (RemoteOK, WeWorkRemotely, Remotive,
    Arbeitnow, Jobicy). Always run first.
  • APIFY actors — only for sources that genuinely need proxy/anti-bot infrastructure
    (LinkedIn, Glassdoor, Indeed-India, Naukri, Cutshort, Wellfound, ATS boards).
    Wrapped in run_actor_safe(): on credit/auth failure the pipeline degrades to
    native-only and (in an interactive TTY) prompts once for a fresh APIFY_TOKEN.

Source selection is driven by preferences.json `job_market_focus` ("india" | "global"
| "both"). Writes the merged, normalized result list to /tmp/jobpilot_raw.json.

NEVER calls the LLM. NEVER reads os.environ for secrets directly (uses secrets.py).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "scrapers"))
from secrets import get_secret_optional, set_secret  # noqa: E402
from scrapers._common import make_job_id  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
RAW_OUT = "/tmp/jobpilot_raw.json"
STATUS_OUT = "/tmp/jobpilot_scrape_status.json"
FREE_ONLY = "--free-only" in sys.argv
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds between retry attempts

# Set once if Apify becomes unusable mid-run, so we prompt/skip only once.
_apify_blocked = False


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def load_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def load_actors() -> dict:
    return load_json(REPO_DIR / "config" / "actors.json", {})


def load_preferences() -> dict:
    return load_json(jobpilot_dir() / "options" / "preferences.json", {})


def load_lessons() -> dict:
    """Load the lessons cache from data dir, falling back to repo seed."""
    lessons_path = jobpilot_dir() / "cache" / "apify_lessons.json"
    if lessons_path.exists():
        return load_json(lessons_path, {})
    seed_path = REPO_DIR / "config" / "apify_lessons_seed.json"
    return load_json(seed_path, {})


def make_job_id(company: str, role: str, location: str, source: str) -> str:
    raw = f"{source}|{company}|{role}|{location}".lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Normalization (shared schema with native scrapers)
# --------------------------------------------------------------------------- #
def normalize(item: dict, source_board: str) -> dict:
    """Map a raw Apify actor record to the common JobPilot schema."""
    def pick(*keys, default=""):
        for k in keys:
            v = item.get(k)
            if v:
                return v
        return default

    company = str(pick("company", "companyName", "employer", "company_name", default="")).strip()
    role = str(pick("title", "role", "jobTitle", "position", "designation", default="")).strip()
    location = str(pick("location", "jobLocation", "place", "city", default="")).strip()
    jd_full = str(pick("description", "jobDescription", "descriptionText", "jd", "text",
                       default="")).strip()
    application_url = str(
        pick("applyUrl", "applicationUrl", "url", "jobUrl", "link", "jobLink", default="")
    ).strip()
    posted = str(pick("postedAt", "postedDate", "datePosted", "publishedAt", "posted",
                      default="")).strip()
    exp = str(pick("experience", "experienceRequired", "seniority", "experienceRange",
                   default="")).strip()
    salary = str(pick("salary", "salaryRange", "ctc", "package", default="")).strip()
    if salary and salary.lower() not in jd_full.lower():
        jd_full = (jd_full + f"  Salary: {salary}").strip()
    board = str(pick("board", "site", "source", default=source_board)).strip() or source_board

    return {
        "job_id": make_job_id(company, role, location, board),
        "company": company,
        "role": role,
        "location": location,
        "experience_req": exp,
        "jd_full": jd_full,
        "has_jd": len(jd_full.strip()) > 100,
        "application_url": application_url,
        "source_board": board,
        "posted_date": posted or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def build_run_input(base_input: dict, actor_id: str, lessons: dict) -> dict:
    """Apply field-name overrides and value transforms from the lessons cache.

    Allows the scraper to use the correct input schema for each actor without
    hardcoding it — the lessons file stores what field names actually work.
    """
    actor_lessons = (lessons.get("actors") or {}).get(actor_id, {})
    field_overrides = actor_lessons.get("field_overrides") or {}
    value_transforms = actor_lessons.get("value_transforms") or {}

    if not field_overrides and not value_transforms:
        return base_input

    result = {}
    for k, v in base_input.items():
        transform = value_transforms.get(k)
        if transform == "split_array" and isinstance(v, str):
            v = [t.strip() for t in v.split() if t.strip()]
        new_key = field_overrides.get(k, k)
        result[new_key] = v
    return result


# ── Apify actor call + retry ──────────────────────────────────────────────────

def run_apify_actor(
    actor_id: str, run_input: dict, token: str, timeout: int = 300
) -> tuple[list, bool, int]:
    """Call an Apify actor with up to MAX_RETRIES attempts.

    0 items counts as a soft failure and triggers a retry.
    Returns (items, success, attempts_used).
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            items = _call_apify_actor(actor_id, run_input, token, timeout)
            if items:
                print(f"[apify] {actor_id}: {len(items)} items (attempt {attempt})", file=sys.stderr)
                return items, True, attempt
            print(f"[apify] {actor_id}: 0 items on attempt {attempt}", file=sys.stderr)
        except Exception as exc:
            print(f"[apify] {actor_id} attempt {attempt} error: {exc}", file=sys.stderr)

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    print(f"[apify] {actor_id}: all {MAX_RETRIES} attempts returned 0 or failed", file=sys.stderr)
    return [], False, MAX_RETRIES


def _call_apify_actor(actor_id: str, run_input: dict, token: str, timeout: int) -> list:
    """Single attempt — SDK preferred, raw requests fallback."""
    try:
        from apify_client import ApifyClient
        client = ApifyClient(token)
        run = client.actor(actor_id).call(run_input=run_input, wait_secs=timeout)
        if not run:
            return []
        dataset_id = run.get("defaultDatasetId")
        if not dataset_id:
            return []
        return list(client.dataset(dataset_id).iterate_items())
    except ImportError:
        print("[apify] apify-client not installed, falling back to requests", file=sys.stderr)
        return _run_apify_actor_raw(actor_id, run_input, token, timeout)


def _run_apify_actor_raw(actor_id: str, run_input: dict, token: str, timeout: int) -> list:
    """Raw requests fallback if apify-client is unavailable."""
    actor_path = actor_id.replace("/", "~")
    url = f"https://api.apify.com/v2/acts/{actor_path}/run-sync-get-dataset-items"
    resp = requests.post(
        url,
        params={"token": token},
        json=run_input,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("items", [])


# ── Free sources ─────────────────────────────────────────────────────────────

def fetch_remoteok() -> list:
    """Remote OK public JSON API — no auth needed."""
    results = []
    try:
        resp = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "JobPilot/1.0"},
            timeout=30,
        )
        resp.raise_for_status()
        for item in resp.json():
            if not isinstance(item, dict) or not item.get("position"):
                continue
            tags = item.get("tags") or []
            results.append(normalize(
                {
                    "company": item.get("company", ""),
                    "title": item.get("position", ""),
                    "location": "Remote",
                    "description": item.get("description", "") + " " + " ".join(tags),
                    "url": item.get("url", ""),
                    "postedAt": item.get("date", ""),
                },
                "remoteok",
            ))
    except Exception as exc:
        print(f"[remoteok] fetch failed: {exc}", file=sys.stderr)
    print(f"[remoteok] {len(results)} jobs fetched", file=sys.stderr)
    return results


def fetch_weworkremotely() -> list:
    """We Work Remotely RSS feeds — no auth needed."""
    feeds = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    ]
    results = []
    seen_ids: set = set()
    for feed_url in feeds:
        try:
            resp = requests.get(feed_url, timeout=30, headers={"User-Agent": "JobPilot/1.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.iter("item"):
                def tag(name: str) -> str:
                    el = item.find(name)
                    return (el.text or "").strip() if el is not None else ""

                title_raw = tag("title")
                if ":" in title_raw:
                    company, _, role = title_raw.partition(":")
                else:
                    company, role = "", title_raw
                company = company.strip()
                role = role.strip()
                link = tag("link")
                jid = make_job_id(company, role, "Remote", "weworkremotely")
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)
                jd_text = tag("description")
                results.append({
                    "job_id": jid,
                    "company": company,
                    "role": role,
                    "location": "Remote",
                    "experience_req": "",
                    "jd_full": jd_text,
                    "has_jd": len(jd_text.strip()) > 100,
                    "application_url": link,
                    "source_board": "weworkremotely",
                    "posted_date": tag("pubDate") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                })
        except Exception as exc:
            print(f"[weworkremotely] feed {feed_url} failed: {exc}", file=sys.stderr)
    print(f"[weworkremotely] {len(results)} jobs fetched", file=sys.stderr)
    return results


def fetch_hn_whoishiring() -> list:
    results = []
    try:
        search = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": "who is hiring", "tags": "story", "hitsPerPage": 1},
            timeout=30,
        ).json()
        hits = search.get("hits", [])
        if not hits:
            return results
        object_id = hits[0]["objectID"]
        thread = requests.get(
            f"https://hn.algolia.com/api/v1/items/{object_id}", timeout=60
        ).json()
        for comment in thread.get("children", []) or []:
            text = (comment.get("text") or "").strip()
            if not text:
                continue
            first_line = text.split("<p>")[0]
            parts = [p.strip() for p in first_line.split("|")]
            company = parts[0][:80] if parts else "HN"
            role = parts[1] if len(parts) > 1 else "See post"
            location = parts[2] if len(parts) > 2 else "Unknown"
            results.append(
                normalize(
                    {
                        "company": company,
                        "title": role,
                        "location": location,
                        "description": text,
                        "url": f"https://news.ycombinator.com/item?id={comment.get('id')}",
                        "postedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    },
                    "hackernews",
                )
            )
    except Exception as exc:
        print(f"[hn] who-is-hiring fetch failed: {exc}", file=sys.stderr)
    print(f"[hn] {len(results)} jobs fetched", file=sys.stderr)
    return results


# ── Main scrape ──────────────────────────────────────────────────────────────

def scrape_apify(
    actors: dict, prefs: dict, token: str, lessons: dict
) -> tuple[list, dict]:
    """Run all configured Apify actors. Returns (normalized jobs, source_status)."""
# --------------------------------------------------------------------------- #
# Apify health + error handling
# --------------------------------------------------------------------------- #
def apify_token() -> str | None:
    return get_secret_optional("APIFY_TOKEN")


def apify_available(token: str | None) -> bool:
    """True only if a token is present AND valid (200 from /users/me).

    We do NOT try to compute remaining credit here — that JSON schema is fragile.
    Actual credit exhaustion is caught reactively in run_actor_safe (HTTP 402/429).
    """
    if not token:
        return False
    try:
        r = requests.get(f"{APIFY_BASE}/users/me", params={"token": token}, timeout=8)
        return r.status_code == 200
    except Exception:
        return False


def _validate_token(token: str) -> bool:
    return apify_available(token)


def prompt_for_new_token(reason: str) -> str | None:
    """Interactive-only inline prompt for a fresh APIFY_TOKEN. Returns it (validated)
    and persists via secrets.py, or None if skipped / non-interactive."""
    global _apify_blocked
    msg = (
        "\n  ⚠️  Apify unavailable: {reason}.\n"
        "      Paid sources (LinkedIn / Glassdoor / Indeed / Naukri / Cutshort / Wellfound)\n"
        "      will be skipped this run; native sources still work.\n\n"
        "      To re-enable Apify:\n"
        "        1. Add credit:  https://console.apify.com/billing\n"
        "           or new token: https://console.apify.com/account/integrations\n"
        "        2. Paste the new APIFY_TOKEN below (or press Enter to skip):\n"
        "      > "
    ).format(reason=reason)
    if not sys.stdin.isatty():
        print(
            f"[apify] {reason} — non-interactive run, continuing with native sources only.",
            file=sys.stderr,
        )
        _apify_blocked = True
        return None
    try:
        sys.stderr.write(msg)
        sys.stderr.flush()
        entered = sys.stdin.readline().strip()
    except Exception:
        entered = ""
    if not entered:
        print("[apify] skipped — continuing with native sources only.", file=sys.stderr)
        _apify_blocked = True
        return None
    if not _validate_token(entered):
        print("[apify] entered token is invalid — continuing native-only.", file=sys.stderr)
        _apify_blocked = True
        return None
    backend = set_secret("APIFY_TOKEN", entered)
    print(f"[apify] new token validated and saved ({backend}).", file=sys.stderr)
    return entered


def _classify_error(status: int, body: str) -> str | None:
    b = (body or "").lower()
    if status in (401, 403) or "unauthorized" in b or "invalid token" in b:
        return "auth"
    if status in (402, 429) or any(s in b for s in ("insufficient", "credit", "payment", "quota",
                                                    "exceeded", "limit reached")):
        return "credit"
    return None


def run_actor_safe(actor_id: str, run_input: dict, token_holder: dict,
                   source_board: str, timeout: int = 300) -> list:
    """Run an Apify actor; normalize + return its items. On credit/auth failure, prompt
    once (interactive) for a new token and retry, else degrade to native-only.

    token_holder is a 1-key dict {"token": ...} so a refreshed token propagates to
    later actor calls within the same run.
    """
    global _apify_blocked
    if _apify_blocked or not actor_id:
        return []
    token = token_holder.get("token")
    if not token:
        return []

    items, err = _run_actor(actor_id, run_input, token, timeout)
    if err in ("credit", "auth"):
        reason = "credits exhausted" if err == "credit" else "token invalid"
        new_token = prompt_for_new_token(reason)
        if new_token:
            token_holder["token"] = new_token
            items, err2 = _run_actor(actor_id, run_input, new_token, timeout)
            if err2:
                _apify_blocked = True
                return []
        else:
            return []
    return [normalize(it, source_board) for it in items]


def _run_actor(actor_id: str, run_input: dict, token: str, timeout: int):
    """Low-level synchronous actor run. Returns (items, error_kind|None)."""
    actor_path = actor_id.replace("/", "~")
    url = f"{APIFY_BASE}/acts/{actor_path}/run-sync-get-dataset-items"
    try:
        resp = requests.post(url, params={"token": token}, json=run_input, timeout=timeout)
        if resp.status_code == 201 or resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data, None
            return (data.get("items", []) if isinstance(data, dict) else []), None
        err = _classify_error(resp.status_code, resp.text)
        if not err:
            # Surface the body snippet so an input-schema mismatch (HTTP 400) is
            # distinguishable from a genuinely empty result, not just a status code.
            snippet = (resp.text or "")[:300].replace("\n", " ")
            print(f"[apify] actor {actor_id} HTTP {resp.status_code} — skipping. Body: {snippet}",
                  file=sys.stderr)
        return [], err
    except Exception as exc:  # noqa: BLE001
        print(f"[apify] actor {actor_id} failed: {exc}", file=sys.stderr)
        return [], None


# --------------------------------------------------------------------------- #
# Keyword / query helpers
# --------------------------------------------------------------------------- #
def build_keywords(prefs: dict) -> str:
    role_types = prefs.get("role_types", []) or ["Software Engineer"]
    keywords = " ".join(role_types)
    extra = (prefs.get("search_keywords_extra") or "").strip()
    if extra:
        keywords = keywords + " " + extra

    location_priority = prefs.get("location_priority") or prefs.get("locations", ["Bengaluru"])
    primary_location = location_priority[0]
    secondary_locations = location_priority[1:]
    boards = actors.get("boards", ["linkedin", "indeed", "glassdoor", "google", "naukri"])
    max_results = actors.get("max_results_per_board", 50)
    hours_old = actors.get("hours_old", 24)
    return keywords.strip()


# --------------------------------------------------------------------------- #
# Native scrapers (free)
# --------------------------------------------------------------------------- #
def run_native_scrapers(focus: str, prefs: dict) -> list:
    """Run all free native scrapers appropriate for the market focus."""
    from scrapers import (arbeitnow, internshala, jobicy, remoteok,  # noqa
                          remotive, weworkremotely)

    keywords = build_keywords(prefs)
    locations = prefs.get("location_priority") or prefs.get("locations") or ["Bengaluru"]
    results: list = []

    def safe(label, fn):
        try:
            jobs = fn()
            print(f"[native] {label}: {len(jobs)} jobs", file=sys.stderr)
            return jobs
        except Exception as exc:  # noqa: BLE001
            print(f"[native] {label} failed: {exc}", file=sys.stderr)
            return []

    # India boards (native): Internshala. Run for primary + secondary city.
    if focus in ("india", "both"):
        for loc in [loc for loc in locations[:2] if loc.lower() != "remote"] or [""]:
            results += safe(f"internshala/{loc or 'all'}",
                            lambda loc=loc: internshala.fetch(keywords, loc, max_results=40,
                                                              focus=focus))

    # Remote JSON boards — relevant whenever remote is acceptable or focus isn't India-only.
    remote_ok = prefs.get("remote_ok", True)
    if focus in ("global", "both") or remote_ok:
        cap = 30 if focus == "global" else (18 if focus == "both" else 12)
        results += safe("remoteok", lambda: remoteok.fetch(keywords, max_results=cap, focus=focus))
        results += safe("remotive", lambda: remotive.fetch(keywords, max_results=cap, focus=focus))
        results += safe("weworkremotely",
                        lambda: weworkremotely.fetch(keywords, max_results=cap, focus=focus))
        results += safe("jobicy", lambda: jobicy.fetch(keywords, max_results=cap, focus=focus))
        results += safe("arbeitnow",
                        lambda: arbeitnow.fetch(keywords, max_results=cap, focus=focus))

    return results


# --------------------------------------------------------------------------- #
# Apify actor calls (paid)
# --------------------------------------------------------------------------- #
def run_apify_layer(focus: str, prefs: dict, actors: dict, token_holder: dict) -> list:
    keywords = build_keywords(prefs)
    locations = prefs.get("location_priority") or prefs.get("locations") or ["Bengaluru"]
    primary_location = locations[0]
    secondary_locations = [loc for loc in locations[1:] if loc.lower() != "remote"]
    boards = actors.get("boards", ["linkedin", "glassdoor", "indeed"])
    max_results = int(actors.get("max_results_per_board", 50))
    hours_old = int(actors.get("hours_old", 48))
    results: list = []

    proxy_in = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}

    # LinkedIn / Glassdoor / Google via the general board scraper (openclawai schema:
    # searchTerm + sites, NOT keywords/boards). indeed + naukri are handled by their
    # dedicated actors below, so they're excluded from `sites` to avoid double cost.
    primary = actors.get("primary_scraper")
    if primary:
        sites = [b for b in boards if b not in ("indeed", "naukri")] or ["linkedin", "glassdoor"]
        country_indeed = "india" if focus in ("india", "both") else "usa"
        primary_input = {
            "searchTerm": keywords,
            "location": primary_location,
            "sites": sites,
            "maxResults": max_results,
            "hoursOld": hours_old,
            "countryIndeed": country_indeed,
            "linkedinFetchDescription": True,
            "proxyConfiguration": proxy_in,
        }
        results += run_actor_safe(primary, primary_input, token_holder, "linkedin")
        for sec in secondary_locations:
            results += run_actor_safe(
                primary, {**primary_input, "location": sec, "maxResults": max_results // 2},
                token_holder, "linkedin")

    # Indeed India (dedicated actor) — india/both only
    if focus in ("india", "both"):
        indeed = actors.get("indeed_india_scraper")
        if indeed:
            results += run_actor_safe(indeed, {
                "keywords": keywords, "country": "IN", "location": primary_location,
                "maxResults": max_results, "includeDescription": True,
                "proxyConfiguration": proxy_in,
            }, token_holder, "indeed")

        # Naukri (bot-protected natively -> Apify)
        naukri = actors.get("naukri_scraper")
        if naukri:
            queries = [f"{keywords} {loc}".strip() for loc in locations[:2]
                       if loc.lower() != "remote"] or [keywords]
            results += run_actor_safe(naukri, {
                "queries": queries[:2], "maxResultsPerQuery": 20, "scrapeMode": "full",
                "proxyConfiguration": proxy_in,
            }, token_holder, "naukri")

        # Cutshort (client-side API -> Apify) — skills-based
        cutshort = actors.get("cutshort_scraper")
        if cutshort:
            skills = (prefs.get("preferred_stack") or [])[:6] or [keywords]
            results += run_actor_safe(cutshort, {
                "skills": skills, "maxResults": 30, "proxyConfiguration": proxy_in,
            }, token_holder, "cutshort")

    # Wellfound (Cloudflare -> Apify) — startups, india + global.
    # Only include optional keys when non-empty (the actor treats empty arrays/strings
    # as real filters on some versions).
    wellfound = actors.get("wellfound_scraper")
    if wellfound:
        wf_input = {"query": keywords, "remote": bool(prefs.get("remote_ok", True))}
        if focus != "global":
            wf_input["location"] = [primary_location]
        if int(prefs.get("experience_years", 0) or 0) <= 1:
            wf_input["experienceLevel"] = "entry"
        results += run_actor_safe(wellfound, wf_input, token_holder, "wellfound")

    # Supplementary job-board scraper (orgupdate schema: requires countryName,
    # locationName, pagesToFetch; keywords via includeKeyword). India/both only — it
    # needs a concrete country. NOTE: this actor is a generic board scraper, not an
    # ATS/greenhouse-specific one.
    ats = actors.get("ats_scraper")
    if ats and focus in ("india", "both"):
        results += run_actor_safe(ats, {
            "countryName": "India",
            "locationName": primary_location,
            "includeKeyword": keywords,
            "pagesToFetch": 2,
            "datePosted": "week",
        }, token_holder, "jobboard")

    return results


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def scrape(native_only: bool = False) -> list:
    actors = load_actors()
    prefs = load_preferences()
    focus = (prefs.get("job_market_focus") or "india").lower()
    if focus not in ("india", "global", "both"):
        focus = "india"

    all_jobs: list = []
    source_status: dict = {}

<<<<<<< HEAD
    # Actor 1: general job-board scraper
    primary = actors.get("primary_scraper", "openclawai/job-board-scraper")
    base_primary_input = {
        "keywords": keywords,
        "location": primary_location,
        "hoursOld": hours_old,
        "maxResults": max_results,
        "boards": boards,
    }
    primary_input = build_run_input(base_primary_input, primary, lessons)
    items, ok, attempts = run_apify_actor(primary, primary_input, token)
    source_status[primary] = {
        "count": len(items), "status": "ok" if ok else "failed", "attempts": attempts
    }
    for item in items:
        all_jobs.append(normalize(item, "job-board"))

    for sec_loc in secondary_locations:
        sec_input = {**primary_input, "location": sec_loc, "maxResults": max_results // 2}
        items, ok, _ = run_apify_actor(primary, sec_input, token)
        for item in items:
            all_jobs.append(normalize(item, "job-board"))

    # Actor 2: ATS-targeted scraper (Greenhouse/Lever/Ashby/Workday)
    ats = actors.get("ats_scraper", "orgupdate/job-posting-scraper")
    base_ats_input = {
        "keywords": keywords,
        "location": primary_location,
        "hoursOld": hours_old,
        "maxResults": max_results,
        "targets": ["greenhouse", "lever", "ashby", "workday"],
    }
    ats_input = build_run_input(base_ats_input, ats, lessons)
    items, ok, attempts = run_apify_actor(ats, ats_input, token)
    source_status[ats] = {
        "count": len(items), "status": "ok" if ok else "failed", "attempts": attempts
    }
    for item in items:
        all_jobs.append(normalize(item, "ats"))

    # Optional India-specific actors
    india_actors = [
        ("naukri_scraper", "naukri"),
        ("wellfound_scraper", "wellfound"),
        ("cutshort_scraper", "cutshort"),
    ]
    for actor_key, source_label in india_actors:
        actor_id = actors.get(actor_key, "").strip()
        if not actor_id:
            continue
        base_india_input = {
            "keywords": keywords,
            "location": primary_location,
            "maxResults": max_results,
        }
        india_input = build_run_input(base_india_input, actor_id, lessons)
        items, ok, attempts = run_apify_actor(actor_id, india_input, token)
        source_status[actor_id] = {
            "count": len(items), "status": "ok" if ok else "failed", "attempts": attempts
        }
        for item in items:
            all_jobs.append(normalize(item, source_label))

    return all_jobs, source_status


def scrape() -> list:
    actors = load_actors()
    prefs = load_preferences()
    lessons = load_lessons()
    free_sources = actors.get("free_sources", ["remoteok", "weworkremotely"])

    all_jobs: list = []
    source_status: dict = {}

    if not FREE_ONLY:
        token = get_secret_optional("APIFY_TOKEN")
        if token:
            apify_jobs, apify_status = scrape_apify(actors, prefs, token, lessons)
            all_jobs.extend(apify_jobs)
            source_status.update(apify_status)
        else:
            print("[apify] APIFY_TOKEN missing — skipping paid scrapers.", file=sys.stderr)

    # Free sources — always fetched
    if "remoteok" in free_sources:
        jobs = fetch_remoteok()
        all_jobs.extend(jobs)
        source_status["remoteok"] = {
            "count": len(jobs), "status": "ok" if jobs else "empty", "attempts": 1
        }
    if "weworkremotely" in free_sources:
        jobs = fetch_weworkremotely()
        all_jobs.extend(jobs)
        source_status["weworkremotely"] = {
            "count": len(jobs), "status": "ok" if jobs else "empty", "attempts": 1
        }
    hn_jobs = fetch_hn_whoishiring()
    all_jobs.extend(hn_jobs)
    source_status["hackernews"] = {
        "count": len(hn_jobs), "status": "ok" if hn_jobs else "empty", "attempts": 1
    }

    # Write per-source status for the job-search skill to read and diagnose
    Path(STATUS_OUT).write_text(json.dumps(source_status, indent=2))
    print(f"[scraper] status written to {STATUS_OUT}", file=sys.stderr)
=======
    # 1) Native first — always free, always runs.
    all_jobs += run_native_scrapers(focus, prefs)

    # 2) Apify layer — only if a valid token exists and not explicitly skipped.
    if not native_only:
        token = apify_token()
        if apify_available(token):
            token_holder = {"token": token}
            all_jobs += run_apify_layer(focus, prefs, actors, token_holder)
        elif token:
            # token present but invalid — prompt once
            new_token = prompt_for_new_token("token invalid")
            if new_token:
                all_jobs += run_apify_layer(focus, prefs, actors, {"token": new_token})
        else:
            print("[apify] no APIFY_TOKEN set — native sources only.", file=sys.stderr)
    else:
        print("[scraper] --native-only: skipping Apify layer.", file=sys.stderr)
>>>>>>> 5a15f6c (feat: hybrid native+Apify scraping, styled XLSX report, India-market focus)

    return all_jobs


def main() -> int:
<<<<<<< HEAD
    mode = "free-only" if FREE_ONLY else "full"
    print(f"[scraper] mode={mode}", file=sys.stderr)
    jobs = scrape()
=======
    native_only = any(a in sys.argv[1:] for a in ("--native-only", "--free-only"))
    jobs = scrape(native_only=native_only)
>>>>>>> 5a15f6c (feat: hybrid native+Apify scraping, styled XLSX report, India-market focus)
    Path(RAW_OUT).write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
    by_board: dict[str, int] = {}
    for j in jobs:
        by_board[j["source_board"]] = by_board.get(j["source_board"], 0) + 1
    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(by_board.items()))
    print(f"Scraped {len(jobs)} raw jobs ({breakdown}) -> {RAW_OUT}")
    return len(jobs)


if __name__ == "__main__":
    main()
