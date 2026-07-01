"""Telegram job channel scraper — pure Python, NO LLM, NO Apify.

Reads recent messages from curated public Telegram job channels using the
Telethon MTProto user client. Every URL extracted from messages is run through
the URL security pipeline before the job is added to the output.

First-time setup (one-time interactive):
  python3 scripts/scrapers/telegram_channels.py --auth

Normal use (called by run_native_scrapers):
  from scrapers import telegram_channels
  jobs = telegram_channels.fetch(keywords, max_results=60, focus="india")

Requires:
  - ~/.claude/job-hunt-ai/cache/telegram.session   (created by --auth)
  - TELEGRAM_API_ID + TELEGRAM_API_HASH secrets    (from my.telegram.org)
  - telethon installed (pip install telethon)
  - scripts/url_security.py
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, matches_keywords, split_terms  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent.parent


def _jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def _session_path() -> Path:
    return _jobpilot_dir() / "cache" / "telegram"


def _load_config() -> dict:
    cfg_path = REPO_DIR / "config" / "telegram_channels.json"
    try:
        return json.loads(cfg_path.read_text())
    except Exception:
        return {"enabled": False, "channels": [], "max_messages_per_channel": 50,
                "max_age_hours": 24, "max_results_total": 60}


def _load_secrets() -> tuple[int | None, str | None]:
    """Return (api_id, api_hash) from secrets store."""
    try:
        from secrets import get_secret_optional  # noqa
        api_id_raw = get_secret_optional("TELEGRAM_API_ID")
        api_hash = get_secret_optional("TELEGRAM_API_HASH")
        api_id = int(api_id_raw) if api_id_raw else None
        return api_id, api_hash
    except Exception:
        return None, None


# --------------------------------------------------------------------------- #
# URL extraction from message text
# --------------------------------------------------------------------------- #

_URL_RE = re.compile(
    r"https?://[^\s\)\]>\"\']+",
    re.IGNORECASE,
)


def _extract_urls(text: str) -> list[str]:
    """Extract all HTTP/HTTPS URLs from message text."""
    return [u.rstrip(".,;:)") for u in _URL_RE.findall(text or "")]


def _clean_text(text: str) -> str:
    """Strip Telegram HTML entities and tags."""
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s{3,}", "\n\n", text).strip()


# --------------------------------------------------------------------------- #
# Message → job dict parsing
# --------------------------------------------------------------------------- #

_PIPE_PATTERN = re.compile(
    r"^(?P<company>[^|\n]{2,60})\s*\|\s*(?P<role>[^|\n]{2,80})"
    r"(?:\s*\|\s*(?P<location>[^|\n]{2,50}))?",
    re.MULTILINE,
)

# Patterns that signal a referral is available in the post
_REFERRAL_PATTERNS = [
    re.compile(r"\bdm\s+(?:me\s+)?for\s+(?:a\s+)?referral\b", re.I),
    re.compile(r"\breferral\s+(?:available|open|slot|link|code|opportunity)\b", re.I),
    re.compile(r"\bcan\s+refer\s+you\b", re.I),
    re.compile(r"\brefer\s+you\b", re.I),
    re.compile(r"\bhave\s+(?:a\s+)?referral\b", re.I),
    re.compile(r"\bproviding\s+referrals?\b", re.I),
    re.compile(r"\breferral\s+(?:is\s+)?available\b", re.I),
    re.compile(r"\bwill\s+refer\b", re.I),
    re.compile(r"\bsharing\s+referrals?\b", re.I),
]


def _detect_referral(text: str) -> tuple[bool, str]:
    """Detect referral offers in a message and extract the contact handle.

    Returns (has_referral, referral_contact).
    referral_contact is a "@handle" string when found, else "".
    """
    has_ref = any(p.search(text) for p in _REFERRAL_PATTERNS)
    contact = ""
    if has_ref:
        # Extract first @handle from the message (the referrer's Telegram username)
        m = re.search(r"@([A-Za-z0-9_]{3,32})", text)
        if m:
            contact = "@" + m.group(1)
    return has_ref, contact


def _parse_message(text: str, channel_slug: str, safe_urls: list[str]) -> dict | None:
    """Attempt to extract a job dict from a Telegram message.

    Returns None if the message doesn't look like a job post.
    Adds has_referral / referral_contact when referral patterns detected.
    """
    clean = _clean_text(text)
    lines = [l.strip() for l in clean.splitlines() if l.strip()]
    if not lines:
        return None

    # Try structured pipe-delimited format: Company | Role | Location
    m = _PIPE_PATTERN.search(clean)
    if m:
        company = m.group("company").strip()
        role = m.group("role").strip()
        location = (m.group("location") or "").strip() or "India"
    else:
        # Fallback: first line = role, second line = company
        role = lines[0][:100]
        company = lines[1][:80] if len(lines) > 1 else "Unknown"
        location = "India"

    apply_url = safe_urls[0] if safe_urls else ""
    jd = clean[:600]  # first 600 chars of message text as JD

    if not role or len(role) < 3:
        return None

    job = build_job(
        company=company,
        role=role,
        location=location,
        jd=jd,
        url=apply_url,
        source=f"telegram-{channel_slug}",
    )

    # Referral detection — check original text (before cleaning) for patterns
    has_referral, referral_contact = _detect_referral(text)
    if has_referral:
        job["has_referral"] = True
        if referral_contact:
            job["referral_contact"] = referral_contact
    else:
        job["has_referral"] = False

    return job


# --------------------------------------------------------------------------- #
# Async Telethon fetch
# --------------------------------------------------------------------------- #

async def _fetch_channel_async(
    client,
    channel_identifier,
    keyword_terms: list[str],
    max_messages: int,
    cutoff: datetime,
    security_db,
) -> list[dict]:
    """Fetch and process messages from one Telegram channel.

    channel_identifier may be a @username string or a numeric chat ID (int).
    """
    try:
        from url_security import check_url  # noqa
    except ImportError:
        def check_url(url, conn):
            return {"safe": True, "risk_label": "safe", "risk_score": 0}

    jobs: list[dict] = []
    label = str(channel_identifier)
    channel_slug = label.lstrip("@").lower().replace("_", "-").replace("-100", "")

    try:
        entity = await client.get_entity(channel_identifier)
    except Exception as exc:
        print(f"[telegram] channel {label} inaccessible: {exc}", file=sys.stderr)
        return []

    async for msg in client.iter_messages(entity, limit=max_messages):
        if not msg.date:
            continue
        # Ensure timezone-aware comparison
        msg_date = msg.date
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
        if msg_date < cutoff:
            break  # messages are ordered newest-first; stop when too old

        text = msg.text or ""
        if not text or len(text) < 20:
            continue
        if not matches_keywords(text, keyword_terms):
            continue

        # Extract and security-check all URLs
        raw_urls = _extract_urls(text)
        safe_urls: list[str] = []
        for url in raw_urls[:5]:  # cap URLs per message
            result = check_url(url, security_db)
            if result["risk_label"] == "dangerous":
                print(f"[telegram] DANGEROUS URL blocked: {url} "
                      f"(score={result['risk_score']})", file=sys.stderr)
                continue
            safe_urls.append(result.get("final_url", url))

        # Only proceed if we have at least one safe URL OR no URLs at all
        # (some messages are text-only job descriptions)
        if raw_urls and not safe_urls:
            continue  # all URLs were dangerous — skip this post

        job = _parse_message(text, channel_slug, safe_urls)
        if not job:
            continue

        # Flag suspicious links in the job dict for Claude to see
        suspicious = [u for u in raw_urls if u in safe_urls and
                      check_url(u, security_db).get("risk_label") == "suspicious"]
        if suspicious:
            job["url_suspicious"] = True

        jobs.append(job)

    return jobs


async def _fetch_async(
    keywords: str,
    max_results: int,
    hours_old: int,
    focus: str,
) -> list[dict]:
    """Main async orchestrator — iterates all configured channels."""
    try:
        from telethon import TelegramClient  # noqa
    except ImportError:
        print("[telegram] telethon not installed — skipping. Run: pip install telethon",
              file=sys.stderr)
        return []

    try:
        from url_security import open_db  # noqa
        security_db = open_db()
    except Exception:
        security_db = None  # security checks degraded but don't fail

    api_id, api_hash = _load_secrets()
    if not api_id or not api_hash:
        print("[telegram] TELEGRAM_API_ID / TELEGRAM_API_HASH not set — skipping.",
              file=sys.stderr)
        return []

    cfg = _load_config()
    if not cfg.get("enabled", False):
        return []

    keyword_terms = split_terms(keywords)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    max_per_channel = cfg.get("max_messages_per_channel", 50)

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    async with TelegramClient(str(_session_path()), api_id, api_hash) as client:
        for ch in cfg.get("channels", []):
            # Support both @username and numeric chat ID for private channels.
            chat_id = ch.get("id")
            username = ch.get("username", "")
            identifier = chat_id if chat_id else (username if username else None)
            if not identifier:
                continue
            label = str(chat_id) if chat_id else f"@{username}"
            jobs = await _fetch_channel_async(
                client, identifier, keyword_terms, max_per_channel,
                cutoff, security_db,
            )
            print(f"[telegram] {label}: {len(jobs)} matching jobs", file=sys.stderr)
            for j in jobs:
                if j["job_id"] not in seen_ids:
                    seen_ids.add(j["job_id"])
                    all_jobs.append(j)
                    if len(all_jobs) >= max_results:
                        return all_jobs

    return all_jobs


# --------------------------------------------------------------------------- #
# Public sync interface (matches other native scrapers)
# --------------------------------------------------------------------------- #

def fetch(keywords: str = "", location: str = "", max_results: int = 60,
          hours_old: int = 24, focus: str = "india") -> list[dict]:
    """Read recent Telegram job channel messages and return canonical job dicts.

    Returns [] if session file is missing, Telethon not installed, or config disabled.
    Never raises.
    """
    if not _session_path().with_suffix(".session").exists():
        print("[telegram] no session file — run: python3 scripts/scrapers/telegram_channels.py --auth",
              file=sys.stderr)
        return []
    try:
        return asyncio.run(_fetch_async(keywords, max_results, hours_old, focus))
    except Exception as exc:
        print(f"[telegram] fetch failed: {exc}", file=sys.stderr)
        return []


# --------------------------------------------------------------------------- #
# Channel discovery + validation (Plan D hybrid approach)
# --------------------------------------------------------------------------- #

SEED_CHANNELS = [
    # India tech job channels (broad candidates — validated via --discover)
    "JobsForSoftwareEngineers", "IndiaJobsIT", "TechJobsIndia", "BangaloreJobs",
    "StartupJobsIndia", "RemoteJobsIndia", "FresherJobsIndia", "IndiaStartupJobs",
    "SoftwareJobsIndia", "HiringIndia", "JobsforindiA", "devjobsindia",
    "pythonJobsIndia", "mlJobsIndia", "backendJobsIndia", "freshersjobs_in",
    "naukrijobsofficial", "hiringfreshers", "campusJobsIndia", "jobsinbengaluru",
    # Additional broad candidates
    "techjobsindia", "bengalurujobs", "startupjobsindia", "remotejobsindia",
    "softwarejobsindia", "freshersjobsindia", "linkedinjobalerts", "indiastartupjobs",
    "techJobsIndia2", "sde_jobs_india", "india_tech_jobs", "bangalore_tech_jobs",
    "job_openings_india", "hiring_india_tech", "swe_jobs_india", "fresher_jobs_2025",
    "softwarejobs_india", "india_startup_hiring", "techrecruiting_india",
]

_DISCOVERY_QUERIES = [
    "jobs india",
    "freshers jobs india",
    "bangalore jobs hiring",
    "startup jobs india",
    "tech hiring india",
]

# Keywords that must appear (case-insensitive) in a discovered channel's title or username
# for it to be considered a job channel. Seed channels bypass this filter.
_JOB_KEYWORDS = {
    "job", "jobs", "hiring", "career", "careers", "recruit", "vacancy",
    "vacancies", "fresher", "freshers", "placement", "intern", "internship",
    "work", "employ", "opportunity", "opportunities",
}

_MIN_MEMBERS_DISCOVERED = 500  # ignore low-traffic channels found via global search


async def _discover_async() -> None:
    """Validate seed channels + discover new ones via Telegram global search."""
    try:
        from telethon import TelegramClient  # noqa
        from telethon.tl.functions.contacts import SearchRequest  # noqa
        from telethon.tl.types import Channel  # noqa
    except ImportError:
        print("telethon not installed. Run: pip install telethon")
        sys.exit(1)

    api_id, api_hash = _load_secrets()
    if not api_id or not api_hash:
        print("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set first.")
        sys.exit(1)

    cfg = _load_config()
    cfg_path = REPO_DIR / "config" / "telegram_channels.json"

    # Collect candidates: seed + existing config channels
    existing_usernames = {ch["username"] for ch in cfg.get("channels", [])}
    candidates: set[str] = set(SEED_CHANNELS) | existing_usernames

    async with TelegramClient(str(_session_path()), api_id, api_hash) as client:
        # Discover via global search
        print(f"[discover] Running {len(_DISCOVERY_QUERIES)} global search queries...")
        discovered_usernames: set[str] = set()
        for query in _DISCOVERY_QUERIES:
            try:
                result = await client(SearchRequest(q=query, limit=25))
                for chat in getattr(result, "chats", []):
                    username = getattr(chat, "username", None)
                    title = getattr(chat, "title", "") or ""
                    if not username:
                        continue
                    # Filter: title or username must contain a job-related keyword
                    combined = (title + " " + username).lower()
                    if any(kw in combined for kw in _JOB_KEYWORDS):
                        discovered_usernames.add(username)
            except Exception as exc:
                print(f"[discover] search '{query}' failed: {exc}", file=sys.stderr)

        candidates |= discovered_usernames

        print(f"[discover] Validating {len(candidates)} candidate channels...")
        live: list[dict] = []
        dead: list[str] = []
        original_usernames = {ch["username"] for ch in cfg.get("channels", [])}
        seed_set = set(SEED_CHANNELS)

        for username in candidates:
            is_seed = username in seed_set or username in original_usernames
            try:
                entity = await client.get_entity(username)
                members = getattr(entity, "participants_count", 0) or 0
                # Apply minimum member threshold only to newly discovered channels
                if not is_seed and members < _MIN_MEMBERS_DISCOVERED:
                    continue
                live.append({"username": username, "members": members})
            except Exception:
                dead.append(username)

    # Sort by member count descending
    live.sort(key=lambda c: c["members"], reverse=True)

    newly_discovered = [
        c["username"] for c in live
        if c["username"] not in original_usernames and c["username"] not in seed_set
    ]

    # Write updated config
    cfg["channels"] = live
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))

    print(
        f"[discover] Live: {len(live)} | Dead/inaccessible: {len(dead)} | "
        f"Newly discovered: {len(newly_discovered)}"
    )
    if len(live) == 0:
        print(
            "\n⚠️  WARNING: 0 live channels found after validation.\n"
            "   All seed channels appear dead or inaccessible.\n"
            "   Telegram scraping will return 0 jobs until live channels are added.\n"
            "   Options:\n"
            "     1. Add known-good channel usernames to config/telegram_channels.json\n"
            "     2. Add private channel numeric IDs (from Telegram app) as {\"id\": -100...}\n"
            f"     3. Edit manually: {cfg_path}",
            file=sys.stderr,
        )
    if dead:
        print(
            f"[discover] Dead channels: {', '.join(dead)}\n"
            f"[discover] Edit manually: {cfg_path}",
            file=sys.stderr,
        )
    if newly_discovered:
        print(f"[discover] New channels: {', '.join(newly_discovered)}")


def discover_channels() -> None:
    """Validate seed + existing channels and discover new ones. Rewrites config."""
    if not _session_path().with_suffix(".session").exists():
        print("No session file found. Run --auth first.")
        sys.exit(1)
    asyncio.run(_discover_async())


# --------------------------------------------------------------------------- #
# First-time auth
# --------------------------------------------------------------------------- #

def auth_interactive() -> None:
    """Authenticate with Telegram (run once). Saves session file."""
    try:
        from telethon import TelegramClient  # noqa
        from telethon.errors import SessionPasswordNeededError  # noqa
    except ImportError:
        print("telethon not installed. Run: pip install telethon")
        sys.exit(1)

    api_id, api_hash = _load_secrets()
    if not api_id or not api_hash:
        print("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set first.")
        print("  1. Visit https://my.telegram.org → Log in → API Development Tools")
        print("  2. Create an app and copy the API ID and API Hash")
        print("  3. Run:")
        print("       python3 -c \"from scripts.secrets import set_secret; "
              "set_secret('TELEGRAM_API_ID', 'YOUR_ID'); "
              "set_secret('TELEGRAM_API_HASH', 'YOUR_HASH')\"")
        sys.exit(1)

    print(f"Session will be saved to: {_session_path()}.session")
    print("You will receive an OTP on your Telegram app.\n")

    async def _do_auth():
        async with TelegramClient(str(_session_path()), api_id, api_hash) as client:
            if not await client.is_user_authorized():
                phone = input("Enter your phone number (with country code, e.g. +91...): ").strip()
                await client.send_code_request(phone)
                code = input("Enter the OTP from Telegram: ").strip()
                try:
                    await client.sign_in(phone, code)
                except SessionPasswordNeededError:
                    password = input("2FA password: ").strip()
                    await client.sign_in(password=password)
            me = await client.get_me()
            print(f"\nAuthenticated as: {me.first_name} (@{me.username})")
            print("Session saved. Telegram channel scraper is ready.")

    asyncio.run(_do_auth())


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    if "--auth" in sys.argv:
        auth_interactive()
    elif "--discover" in sys.argv:
        discover_channels()
    else:
        import json as _json
        results = fetch("software engineer backend", max_results=10)
        print(f"telegram_channels: {len(results)} jobs", file=sys.stderr)
        print(_json.dumps(results[:3], indent=2, ensure_ascii=False))
