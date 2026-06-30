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

import json
import os
import re
import sys
import time
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
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds between retry attempts
APIFY_BASE = "https://api.apify.com/v2"

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


def load_run_state() -> dict:
    return load_json(jobpilot_dir() / "cache" / "run_state.json",
                     {"exhausted_slots": [], "next_scheduled_mode": "full", "last_full_run": ""})


def save_run_state(state: dict) -> None:
    path = jobpilot_dir() / "cache" / "run_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def _get_active_token(exhausted_slots: list) -> tuple:
    """Return (token, slot_number) for the first non-exhausted slot that has a token."""
    for slot, key in [(1, "APIFY_TOKEN"), (2, "APIFY_TOKEN_2"), (3, "APIFY_TOKEN_3")]:
        if slot in exhausted_slots:
            continue
        t = get_secret_optional(key)
        if t:
            return t, slot
    return None, 0


# --------------------------------------------------------------------------- #
# Normalization (shared schema with native scrapers)
# --------------------------------------------------------------------------- #
def _synthesize_fallback_url(company: str, role: str, location: str, board: str) -> str:
    """Build a deterministic search URL when the actor returns no apply link."""
    import urllib.parse
    slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    q = urllib.parse.quote_plus(f"{role} {company}".strip())
    loc = urllib.parse.quote_plus(location or "")
    if board == "naukri":
        return f"https://www.naukri.com/job-listings-{slug(role)}-{slug(company)}?q={q}&l={loc}"
    if board == "cutshort":
        return f"https://cutshort.io/jobs?q={q}"
    if board in ("wellfound", "angel"):
        return f"https://wellfound.com/jobs?q={q}"
    if board == "linkedin":
        return f"https://www.linkedin.com/jobs/search/?keywords={q}&location={loc}"
    if board == "indeed":
        return f"https://www.indeed.co.in/jobs?q={q}&l={loc}"
    if board == "glassdoor":
        return f"https://www.glassdoor.co.in/Job/jobs.htm?sc.keyword={q}&locT=C&locId=0"
    return ""


def normalize(item: dict, source_board: str, url_field: str = "") -> dict:
    """Map a raw Apify actor record to the common JobPilot schema.

    url_field: optional actor-specific key that holds the apply URL (from lessons cache).
    When supplied it is tried before the generic pick() list.
    """
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

    # URL pick order: actor-specific override first, then exhaustive fallback list.
    url_keys = []
    if url_field:
        url_keys.append(url_field)
    url_keys += [
        "applyUrl", "applicationUrl", "url", "jobUrl", "link", "jobLink",
        "detailUrl", "positionUrl", "startupUrl", "jobPostUrl", "applyLink",
        "jobDetailUrl", "externalApplyUrl", "applyNowUrl", "jobListingUrl",
        "companyUrl", "redirectUrl", "sourceUrl",
    ]
    application_url = str(pick(*url_keys, default="")).strip()
    posted = str(pick("postedAt", "postedDate", "datePosted", "publishedAt", "posted",
                      default="")).strip()
    exp = str(pick("experience", "experienceRequired", "seniority", "experienceRange",
                   default="")).strip()
    salary = str(pick("salary", "salaryRange", "ctc", "package", default="")).strip()
    if salary and salary.lower() not in jd_full.lower():
        jd_full = (jd_full + f"  Salary: {salary}").strip()
    board = str(pick("board", "site", "source", default=source_board)).strip() or source_board
    last_date = str(pick("applicationDeadline", "lastDate", "applyBy", "deadline",
                         default="")).strip()

    # Synthesise a search URL when the actor returns no direct link.
    if not application_url:
        application_url = _synthesize_fallback_url(company, role, location, board)

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
        "last_date": last_date,
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
    url = f"{APIFY_BASE}/acts/{actor_path}/run-sync-get-dataset-items"
    resp = requests.post(
        url,
        params={"token": token},
        json=run_input,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else data.get("items", [])


# --------------------------------------------------------------------------- #
# Hacker News — Who Is Hiring (free, native)
# --------------------------------------------------------------------------- #
def _hn_strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities (inline, no _common import needed)."""
    import html as _html_mod
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", _html_mod.unescape(text)).strip()


def fetch_hn_whoishiring() -> list:
    """Fetch jobs from the latest monthly 'Ask HN: Who is hiring?' thread.

    Uses search_by_date (not search) so the most recent thread is always first,
    not the most "relevant" one (which previously returned a 2020 thread).
    Tags each job with the thread's year-month so staleness is visible.
    """
    results = []
    try:
        # search_by_date + author_whoishiring tag → always the newest monthly thread
        search = requests.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={
                "query": "Ask HN: Who is hiring",
                "tags": "story,author_whoishiring",
                "hitsPerPage": 1,
            },
            timeout=30,
        ).json()
        hits = search.get("hits", [])
        if not hits:
            print("[hn] No 'who is hiring' thread found", file=sys.stderr)
            return results

        hit = hits[0]
        object_id = hit["objectID"]
        thread_month = (hit.get("created_at") or "")[:7]   # YYYY-MM — staleness tag
        thread_date  = (hit.get("created_at") or "")[:10]  # YYYY-MM-DD — posted_date
        thread_title = hit.get("title", "unknown")
        print(f"[hn] Thread: '{thread_title}' ({thread_month}) id={object_id}",
              file=sys.stderr)

        thread = requests.get(
            f"https://hn.algolia.com/api/v1/items/{object_id}", timeout=60
        ).json()

        for comment in thread.get("children", []) or []:
            text = (comment.get("text") or "").strip()
            if not text or len(text) < 30:
                continue

            # First line only, stripped of HTML
            raw_first = re.split(r"(?i)<p>", text, maxsplit=1)[0]
            first_line = _hn_strip_html(raw_first).strip()
            if not first_line:
                continue

            # Split on pipe — tolerate missing parts
            parts = [p.strip() for p in re.split(r"\s*\|\s*", first_line)]
            company = parts[0][:100] if parts else ""
            role     = parts[1]      if len(parts) > 1 else ""
            location = parts[2]      if len(parts) > 2 else "Unknown"

            # Drop entries without a plausible company name
            if not company or len(company) < 2:
                continue
            # Drop entries where role is absent or is just a meta-label
            _bad_roles = {"remote", "full-time", "full time", "part-time", "contract",
                          "see post", "hiring", ""}
            if not role or role.lower() in _bad_roles:
                if len(parts) == 1:
                    continue  # only one field — not parseable as a job posting
                role = "Various roles"

            # Normalise obvious remote markers in location
            if any(r in location.lower() for r in ("remote", "wfh", "work from home",
                                                    "anywhere", "worldwide")):
                if "remote" not in location.lower():
                    location = f"Remote / {location}"

            full_jd = _hn_strip_html(text)
            results.append(
                normalize(
                    {
                        "company": company,
                        "title": role,
                        "location": location,
                        "description": f"[HN {thread_month}] {full_jd}",
                        "url": f"https://news.ycombinator.com/item?id={comment.get('id')}",
                        "postedAt": thread_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    },
                    "hackernews",
                )
            )
    except Exception as exc:
        print(f"[hn] who-is-hiring fetch failed: {exc}", file=sys.stderr)
    print(f"[hn] {len(results)} jobs fetched", file=sys.stderr)
    return results


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
                   source_board: str, timeout: int = 300,
                   url_field: str = "") -> list:
    """Run an Apify actor; normalize + return its items. On credit/auth failure, prompt
    once (interactive) for a new token and retry, else degrade to native-only.

    token_holder is a 1-key dict {"token": ...} so a refreshed token propagates to
    later actor calls within the same run.
    url_field: actor-specific URL key from the lessons cache (empty = use generic list).
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
    return [normalize(it, source_board, url_field=url_field) for it in items]


def _run_actor(actor_id: str, run_input: dict, token: str, timeout: int):
    """Low-level synchronous actor run. Returns (items, error_kind|None)."""
    actor_path = actor_id.replace("/", "~")
    url = f"{APIFY_BASE}/acts/{actor_path}/run-sync-get-dataset-items"
    try:
        resp = requests.post(url, params={"token": token}, json=run_input, timeout=timeout)
        if resp.status_code in (200, 201):
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
    return keywords.strip()


# --------------------------------------------------------------------------- #
# Native scrapers (free)
# --------------------------------------------------------------------------- #
def run_native_scrapers(focus: str, prefs: dict, actors: dict | None = None) -> list:
    """Run all free native scrapers appropriate for the market focus.

    Sources listed in actors.json `disabled_native_sources` are skipped silently.
    """
    from scrapers import (arbeitnow, internshala, jobicy, remoteok,  # noqa
                          remotive, weworkremotely)

    disabled_native = set((actors or {}).get("disabled_native_sources", []))

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

    # Per-source cap — prevents any single source from flooding the pipeline.
    per_source_cap = int(prefs.get("per_source_cap", 20))

    # India boards (native): Internshala. Run for primary + secondary city.
    if focus in ("india", "both"):
        for loc in [loc for loc in locations[:2] if loc.lower() != "remote"] or [""]:
            results += safe(f"internshala/{loc or 'all'}",
                            lambda loc=loc: internshala.fetch(keywords, loc,
                                                              max_results=per_source_cap,
                                                              focus=focus))

        # India-specific free boards: Hasjob + Instahyre
        if "hasjob" not in disabled_native:
            try:
                from scrapers import hasjob  # noqa
                results += safe("hasjob", lambda: hasjob.fetch(keywords, max_results=25, focus=focus))
            except ImportError:
                pass

        if "instahyre" not in disabled_native:
            try:
                from scrapers import instahyre  # noqa
                results += safe("instahyre",
                                lambda: instahyre.fetch(keywords, max_results=25, focus=focus))
            except ImportError:
                pass

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

        # YC Work at a Startup (global + both) — uses HN Firebase Jobs API
        if "yc_startup" not in disabled_native:
            try:
                from scrapers import yc_startup  # noqa
                results += safe("yc_startup",
                                lambda: yc_startup.fetch(keywords, max_results=cap, focus=focus))
            except ImportError:
                pass

        # Wellfound public listing (disabled: Cloudflare blocks all requests)
        if "wellfound_rss" not in disabled_native:
            try:
                from scrapers import wellfound_rss  # noqa
                results += safe("wellfound_rss",
                                lambda: wellfound_rss.fetch(keywords, max_results=cap, focus=focus))
            except ImportError:
                pass

    # Hacker News — Who Is Hiring. Configurable via hn_max_results (default 100).
    hn_cap = int(prefs.get("hn_max_results", 100))
    hn = safe("hackernews", fetch_hn_whoishiring)
    emitting = min(len(hn), hn_cap)
    if len(hn) > hn_cap:
        print(f"[hn] Fetched {len(hn)} jobs, emitting {emitting} (hn_max_results={hn_cap})",
              file=sys.stderr)
    else:
        print(f"[hn] Fetched {len(hn)} jobs, emitting all", file=sys.stderr)
    results += hn[:hn_cap]

    # LinkedIn guest API — disabled by default (soft-blocked, returns 0; use Apify on full runs)
    if "linkedin_guest" not in disabled_native:
        try:
            from scrapers import linkedin_guest  # noqa
            for loc in [l for l in locations[:2] if l.lower() != "remote"] or [""]:
                results += safe(
                    f"linkedin_guest/{loc or 'all'}",
                    lambda loc=loc: linkedin_guest.fetch(keywords, loc, max_results=25, focus=focus),
                )
        except ImportError:
            pass  # scraper not installed yet — skip silently

    # Telegram job channels — only if session file exists (opt-in after --auth).
    session_path = jobpilot_dir() / "cache" / "telegram.session"
    if session_path.exists():
        try:
            from scrapers import telegram_channels  # noqa
            results += safe(
                "telegram_channels",
                lambda: telegram_channels.fetch(keywords, max_results=60, focus=focus),
            )
        except ImportError:
            pass  # telethon not installed yet — skip silently

    return results


# --------------------------------------------------------------------------- #
# Apify actor calls (paid)
# --------------------------------------------------------------------------- #
def _actor_url_field(actor_id: str, lessons: dict) -> str:
    """Return the actor-specific URL field name from the lessons cache, or empty string."""
    return (lessons.get("actors") or {}).get(actor_id, {}).get("url_field", "")


def run_apify_layer(focus: str, prefs: dict, actors: dict, token_holder: dict,
                    lessons: dict | None = None) -> list:
    if lessons is None:
        lessons = {}
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
        purl = _actor_url_field(primary, lessons)
        results += run_actor_safe(primary, primary_input, token_holder, "linkedin", url_field=purl)
        for sec in secondary_locations:
            results += run_actor_safe(
                primary, {**primary_input, "location": sec, "maxResults": max_results // 2},
                token_holder, "linkedin", url_field=purl)

    # Indeed India (dedicated actor) — india/both only
    if focus in ("india", "both"):
        indeed = actors.get("indeed_india_scraper")
        if indeed:
            results += run_actor_safe(indeed, {
                "keywords": keywords, "country": "IN", "location": primary_location,
                "maxResults": max_results, "includeDescription": True,
                "proxyConfiguration": proxy_in,
            }, token_holder, "indeed", url_field=_actor_url_field(indeed, lessons))

        # Naukri (bot-protected natively -> Apify)
        naukri = actors.get("naukri_scraper")
        if naukri:
            queries = [f"{keywords} {loc}".strip() for loc in locations[:2]
                       if loc.lower() != "remote"] or [keywords]
            results += run_actor_safe(naukri, {
                "queries": queries[:2], "maxResultsPerQuery": 20, "scrapeMode": "full",
                "proxyConfiguration": proxy_in,
            }, token_holder, "naukri", url_field=_actor_url_field(naukri, lessons))

        # Cutshort (client-side API -> Apify) — skills-based
        cutshort = actors.get("cutshort_scraper")
        if cutshort:
            skills = (prefs.get("preferred_stack") or [])[:6] or [keywords]
            results += run_actor_safe(cutshort, {
                "skills": skills, "maxResults": 30, "proxyConfiguration": proxy_in,
            }, token_holder, "cutshort", url_field=_actor_url_field(cutshort, lessons))

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
        results += run_actor_safe(wellfound, wf_input, token_holder, "wellfound",
                                  url_field=_actor_url_field(wellfound, lessons))

    # Supplementary job-board scraper (orgupdate schema: requires countryName,
    # locationName, pagesToFetch; keywords via includeKeyword). India/both only — it
    # needs a concrete country.
    ats = actors.get("ats_scraper")
    if ats and focus in ("india", "both"):
        results += run_actor_safe(ats, {
            "countryName": "India",
            "locationName": primary_location,
            "includeKeyword": keywords,
            "pagesToFetch": 2,
            "datePosted": "week",
        }, token_holder, "jobboard", url_field=_actor_url_field(ats, lessons))

    return results


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def scrape(native_only: bool = False) -> list:
    actors = load_actors()
    prefs = load_preferences()
    lessons = load_lessons()
    focus = (prefs.get("job_market_focus") or "india").lower()
    if focus not in ("india", "global", "both"):
        focus = "india"

    all_jobs: list = []

    # 1) Native first — always free, always runs.
    all_jobs += run_native_scrapers(focus, prefs, actors)

    # 2) Apify layer — multi-slot key rotation; degrade to native-only if all exhausted.
    if not native_only:
        run_state = load_run_state()
        exhausted = list(run_state.get("exhausted_slots", []))
        apify_ran = False

        while True:
            token, slot = _get_active_token(exhausted)
            if not token:
                break
            if not apify_available(token):
                print(f"[apify] slot {slot} token invalid — trying next.", file=sys.stderr)
                exhausted.append(slot)
                continue

            global _apify_blocked
            _apify_blocked = False  # reset for this slot's attempt
            apify_jobs = run_apify_layer(focus, prefs, actors, {"token": token},
                                         lessons=lessons)

            if _apify_blocked:
                # Credit exhausted during this slot's run
                print(f"[apify] slot {slot} credits exhausted — trying next slot.",
                      file=sys.stderr)
                exhausted.append(slot)
                continue

            all_jobs += apify_jobs
            apify_ran = True
            # Persist any newly discovered exhausted slots (e.g. secondary slots that failed)
            run_state["exhausted_slots"] = [s for s in exhausted if s != slot]
            save_run_state(run_state)
            break

        if not apify_ran:
            run_state["exhausted_slots"] = exhausted
            save_run_state(run_state)
            if exhausted:
                print(f"[apify] all slots exhausted {exhausted} — sending alert.",
                      file=sys.stderr)
                try:
                    sys.path.insert(0, str(Path(__file__).resolve().parent))
                    from telegram_notify import send_credit_alert  # noqa
                    send_credit_alert(exhausted)
                except Exception as exc:
                    print(f"[apify] credit alert failed: {exc}", file=sys.stderr)
            else:
                print("[apify] no APIFY_TOKEN set — native sources only.", file=sys.stderr)
    else:
        print("[scraper] --native-only: skipping Apify layer.", file=sys.stderr)

    return all_jobs


def main() -> int:
    native_only = any(a in sys.argv[1:] for a in ("--native-only", "--free-only"))
    jobs = scrape(native_only=native_only)
    Path(RAW_OUT).write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
    by_board: dict[str, int] = {}
    for j in jobs:
        by_board[j["source_board"]] = by_board.get(j["source_board"], 0) + 1
    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(by_board.items()))
    print(f"Scraped {len(jobs)} raw jobs ({breakdown}) -> {RAW_OUT}")
    return len(jobs)


if __name__ == "__main__":
    main()
