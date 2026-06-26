"""Layer A scraper — pure Python, NO LLM.

Uses the official apify-client SDK for Apify actors and fetches free sources (Remote OK,
We Work Remotely, HN Who is Hiring). Writes /tmp/jobpilot_raw.json.

Flags:
  --free-only   Skip all Apify actor calls; only fetch Remote OK, WWR, and HN.
                Used by the job-search skill when Apify MCP is handling actor calls directly.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets import get_secret_optional  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
RAW_OUT = "/tmp/jobpilot_raw.json"
STATUS_OUT = "/tmp/jobpilot_scrape_status.json"
FREE_ONLY = "--free-only" in sys.argv
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds between retry attempts


def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
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


def normalize(item: dict, source_board: str) -> dict:
    def pick(*keys, default=""):
        for k in keys:
            v = item.get(k)
            if v:
                return v
        return default

    company = str(pick("company", "companyName", "employer", default="")).strip()
    role = str(pick("title", "role", "jobTitle", "position", default="")).strip()
    location = str(pick("location", "jobLocation", "place", default="")).strip()
    jd_full = str(pick("description", "jobDescription", "descriptionText", "text", default="")).strip()
    application_url = str(
        pick("applyUrl", "applicationUrl", "url", "jobUrl", "link", default="")
    ).strip()
    posted = str(pick("postedAt", "postedDate", "datePosted", "publishedAt", default="")).strip()
    exp = str(pick("experience", "experienceRequired", "seniority", default="")).strip()
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

    all_jobs: list = []
    source_status: dict = {}

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

    return all_jobs


def main() -> int:
    mode = "free-only" if FREE_ONLY else "full"
    print(f"[scraper] mode={mode}", file=sys.stderr)
    jobs = scrape()
    Path(RAW_OUT).write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
    print(f"Scraped {len(jobs)} raw jobs -> {RAW_OUT}")
    return len(jobs)


if __name__ == "__main__":
    main()
