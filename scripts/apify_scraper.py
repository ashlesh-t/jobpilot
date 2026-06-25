"""Layer A scraper — pure Python, NO LLM.

Calls the Apify REST API directly (not via MCP) plus the free Hacker News "Who is hiring"
Algolia API, normalises everything to a common schema, and writes /tmp/jobpilot_raw.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets import get_secret, get_secret_optional  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
RAW_OUT = "/tmp/jobpilot_raw.json"
APIFY_BASE = "https://api.apify.com/v2"


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


def make_job_id(company: str, role: str, location: str, source: str) -> str:
    raw = f"{source}|{company}|{role}|{location}".lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def run_apify_actor(actor_id: str, run_input: dict, token: str, timeout: int = 300) -> list:
    """Run an actor synchronously and return its dataset items. Returns [] on any failure."""
    actor_path = actor_id.replace("/", "~")
    url = f"{APIFY_BASE}/acts/{actor_path}/run-sync-get-dataset-items"
    try:
        resp = requests.post(
            url,
            params={"token": token},
            json=run_input,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return data.get("items", []) if isinstance(data, dict) else []
    except Exception as exc:  # noqa: BLE001
        print(f"[apify] actor {actor_id} failed: {exc}", file=sys.stderr)
        return []


def normalize(item: dict, source_board: str) -> dict:
    """Map a raw actor record to the common JobPilot schema (best-effort field guessing)."""
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
        "application_url": application_url,
        "source_board": board,
        "posted_date": posted or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def fetch_hn_whoishiring() -> list:
    """Free HN 'Who is hiring' thread via Algolia — no key needed."""
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
            # First line is usually "Company | Role | Location | ..."
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
    except Exception as exc:  # noqa: BLE001
        print(f"[hn] who-is-hiring fetch failed: {exc}", file=sys.stderr)
    return results


def scrape() -> list:
    actors = load_actors()
    prefs = load_preferences()
    token = get_secret_optional("APIFY_TOKEN")

    role_types = prefs.get("role_types", []) or ["Software Engineer"]
    keywords = " ".join(role_types)
    extra = (prefs.get("search_keywords_extra") or "").strip()
    if extra:
        keywords = keywords + " " + extra
    locations = prefs.get("locations", []) or ["Bengaluru"]
    location_priority = prefs.get("location_priority") or locations
    primary_location = location_priority[0]
    secondary_locations = location_priority[1:]
    boards = actors.get("boards", ["linkedin", "indeed", "glassdoor", "google", "naukri"])
    max_results = actors.get("max_results_per_board", 50)
    hours_old = actors.get("hours_old", 24)

    all_jobs: list = []

    if token:
        # Actor 1: general job-board scraper — primary location at full results
        primary = actors.get("primary_scraper", "openclawai/job-board-scraper")
        primary_input = {
            "keywords": keywords,
            "location": primary_location,
            "hoursOld": hours_old,
            "maxResults": max_results,
            "boards": boards,
        }
        for item in run_apify_actor(primary, primary_input, token):
            all_jobs.append(normalize(item, "job-board"))

        # Secondary locations at half results (lower priority = fewer suggestions)
        for sec_loc in secondary_locations:
            sec_input = {**primary_input, "location": sec_loc, "maxResults": max_results // 2}
            for item in run_apify_actor(primary, sec_input, token):
                all_jobs.append(normalize(item, "job-board"))

        # Actor 2: ATS-targeted scraper (Greenhouse/Lever/Ashby/Workday) for real apply URLs
        ats = actors.get("ats_scraper", "orgupdate/job-posting-scraper")
        ats_input = {
            "keywords": keywords,
            "location": primary_location,
            "hoursOld": hours_old,
            "maxResults": max_results,
            "targets": ["greenhouse", "lever", "ashby", "workday"],
        }
        for item in run_apify_actor(ats, ats_input, token):
            all_jobs.append(normalize(item, "ats"))
    else:
        print("[apify] APIFY_TOKEN missing — skipping paid scrapers, using HN only.",
              file=sys.stderr)

    # Always include free HN Who-is-hiring
    all_jobs.extend(fetch_hn_whoishiring())
    return all_jobs


def main() -> int:
    jobs = scrape()
    Path(RAW_OUT).write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
    print(f"Scraped {len(jobs)} raw jobs -> {RAW_OUT}")
    return len(jobs)


if __name__ == "__main__":
    main()
