"""Telegram job channel scraper — pure Python, NO LLM, NO Apify.

Reads recent messages from curated public Telegram job channels via the public
`t.me/s/<channel>` web preview — plain server-rendered HTML, no login, no API
key, no phone number. This works for any public channel (which job channels
always are); private channels aren't supported by this approach and never were
a target here. Every URL extracted from messages is run through the URL
security pipeline before the job is added to the output.

Managing the channel list:
  from scripts.scrapers import telegram_channels
  telegram_channels.validate_channel("getjobss")   # live check, no side effect
  # add/remove/list channels live in core/repo/telegram_channels.py, which calls
  # validate_channel() before ever accepting one — see that module, not this CLI.

Normal use (called by run_native_scrapers):
  from scrapers import telegram_channels
  jobs = telegram_channels.fetch(keywords, max_results=60, focus="india")

Requires: scripts/url_security.py. No API keys, no session file, no telethon.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_job, http_get, matches_keywords, split_terms  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent.parent


def _jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def _config_path() -> Path:
    return REPO_DIR / "config" / "telegram_channels.json"


def _load_config() -> dict:
    try:
        return json.loads(_config_path().read_text())
    except Exception:
        return {"enabled": False, "channels": [], "max_messages_per_channel": 50,
                "max_age_hours": 24, "max_results_total": 60}


def _save_config(cfg: dict) -> None:
    _config_path().write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Channel-list management — core/repo/telegram_channels.py is a thin wrapper over
# these, the same way core/secrets.py wraps scripts/jp_secrets.py.
# --------------------------------------------------------------------------- #

def list_channels() -> list[dict]:
    return _load_config().get("channels", [])


def add_channel(username: str) -> dict:
    """Validate live, then persist. Raises ValueError if the channel isn't real —
    never silently stores a guess."""
    username = username.lstrip("@").strip()
    if not username:
        raise ValueError("channel username can't be empty")
    check = validate_channel(username)
    if not check["valid"]:
        raise ValueError(f"@{username}: {check['reason']}")

    cfg = _load_config()
    channels = cfg.setdefault("channels", [])
    if any(c.get("username", "").lower() == username.lower() for c in channels):
        raise ValueError(f"@{username} is already in your channel list")
    channels.append({"username": username, "name": username, "members": 0})
    _save_config(cfg)
    return check


def remove_channel(username: str) -> bool:
    username = username.lstrip("@").strip().lower()
    cfg = _load_config()
    channels = cfg.get("channels", [])
    kept = [c for c in channels if c.get("username", "").lower() != username]
    if len(kept) == len(channels):
        return False
    cfg["channels"] = kept
    _save_config(cfg)
    return True


def revalidate_all() -> list[dict]:
    """Re-check every configured channel live; drop any that are now dead."""
    cfg = _load_config()
    channels = cfg.get("channels", [])
    results = []
    kept = []
    for ch in channels:
        username = ch.get("username", "")
        check = validate_channel(username) if username else {"username": username, "valid": False,
                                                               "reason": "no username"}
        results.append(check)
        if check["valid"]:
            kept.append(ch)
    if len(kept) != len(channels):
        cfg["channels"] = kept
        _save_config(cfg)
    return results


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
# Public web-preview fetch (no auth, no session)
# --------------------------------------------------------------------------- #

_POST_RE = re.compile(r'data-post="([^/"]+)/(\d+)"')
_MSG_TEXT_RE = re.compile(r'class="tgme_widget_message_text[^"]*"\s+dir="auto">(.*?)</div>', re.S)
_MSG_TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"')


def _fetch_preview_page(channel: str, before: int | None = None) -> str | None:
    """One page of `https://t.me/s/<channel>` — plain HTML, no auth required."""
    params = {"before": before} if before else None
    resp = http_get(f"https://t.me/s/{channel}", params=params, timeout=15, retries=1)
    return resp.text if resp else None


def _parse_preview_html(html_text: str) -> list[tuple[int, str, str]]:
    """Every message in a preview page: (message_id, inner_html, iso_datetime).

    Returned in DOM order — oldest first within the page, matching how Telegram
    renders it (like a chat scroll), not newest-first.
    """
    posts = list(_POST_RE.finditer(html_text))
    out = []
    for i, m in enumerate(posts):
        msg_id = int(m.group(2))
        start = m.end()
        end = posts[i + 1].start() if i + 1 < len(posts) else len(html_text)
        block = html_text[start:end]
        text_m = _MSG_TEXT_RE.search(block)
        if not text_m:
            continue
        time_m = _MSG_TIME_RE.search(block)
        out.append((msg_id, text_m.group(1), time_m.group(1) if time_m else ""))
    return out


def validate_channel(channel: str) -> dict:
    """Live check: is this a real, public, readable Telegram channel?

    Doubles as both the add-channel validator (reject synchronously, never
    silently store a guess) and the self-heal check during normal fetch() (a
    channel returning 0 messages gets re-validated and dropped if dead).
    """
    channel = channel.lstrip("@").strip()
    if not channel:
        return {"username": channel, "valid": False, "reason": "empty channel name"}
    html_text = _fetch_preview_page(channel)
    if html_text is None:
        return {"username": channel, "valid": False, "reason": "unreachable or 404"}
    messages = _parse_preview_html(html_text)
    if not messages:
        return {"username": channel, "valid": False,
                "reason": "no messages found — private, empty, or nonexistent"}
    member_m = re.search(r'tgme_channel_info_counter[^>]*>\s*<span[^>]*>([\d.,\sKMk]+)</span>', html_text)
    return {
        "username": channel,
        "valid": True,
        "member_count_label": (member_m.group(1).strip() if member_m else ""),
        "sample": _clean_text(messages[-1][1])[:120],
    }


def _fetch_channel_sync(
    channel: str,
    keyword_terms: list[str],
    max_messages: int,
    cutoff: datetime,
    security_db,
) -> list[dict]:
    """Fetch and process recent messages from one public channel, paginating
    backward via ?before=<id> until max_messages, the cutoff, or an empty page."""
    try:
        from url_security import check_url  # noqa
    except ImportError:
        def check_url(url, conn):
            return {"safe": True, "risk_label": "safe", "risk_score": 0}

    channel_slug = channel.lower().replace("_", "-")
    jobs: list[dict] = []
    before: int | None = None
    seen_ids: set[int] = set()

    for _page in range(6):  # hard cap — a handful of pages is enough recent history
        html_text = _fetch_preview_page(channel, before=before)
        if not html_text:
            if before is None:
                print(f"[telegram] channel {channel} inaccessible", file=sys.stderr)
            break
        messages = _parse_preview_html(html_text)
        if not messages:
            break

        oldest_id = messages[0][0]
        stop = False
        for msg_id, text_html, iso_date in reversed(messages):  # newest first within page
            if msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)

            msg_date = None
            if iso_date:
                try:
                    msg_date = datetime.fromisoformat(iso_date)
                except ValueError:
                    msg_date = None
            if msg_date and msg_date < cutoff:
                stop = True
                break

            text = _clean_text(text_html)
            if not text or len(text) < 20:
                continue
            if not matches_keywords(text, keyword_terms):
                continue

            raw_urls = _extract_urls(text)
            safe_urls: list[str] = []
            for url in raw_urls[:5]:
                result = check_url(url, security_db)
                if result["risk_label"] == "dangerous":
                    print(f"[telegram] DANGEROUS URL blocked: {url} "
                          f"(score={result['risk_score']})", file=sys.stderr)
                    continue
                safe_urls.append(result.get("final_url", url))
            if raw_urls and not safe_urls:
                continue

            job = _parse_message(text, channel_slug, safe_urls)
            if not job:
                continue
            suspicious = [u for u in raw_urls if u in safe_urls and
                          check_url(u, security_db).get("risk_label") == "suspicious"]
            if suspicious:
                job["url_suspicious"] = True
            jobs.append(job)

            if len(jobs) >= max_messages:
                stop = True
                break

        if stop or len(jobs) >= max_messages:
            break
        before = oldest_id  # walk further back next page

    return jobs


# --------------------------------------------------------------------------- #
# Public sync interface (matches other native scrapers)
# --------------------------------------------------------------------------- #

def fetch(keywords: str = "", location: str = "", max_results: int = 60,
          hours_old: int = 24, focus: str = "india") -> list[dict]:
    """Read recent Telegram job channel messages and return canonical job dicts.

    Returns [] if config is disabled or has no channels. Never raises.
    """
    cfg = _load_config()
    if not cfg.get("enabled", False):
        return []
    channels = cfg.get("channels", [])
    if not channels:
        return []

    try:
        from url_security import open_db  # noqa
        security_db = open_db()
    except Exception:
        security_db = None

    keyword_terms = split_terms(keywords)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    max_per_channel = cfg.get("max_messages_per_channel", 50)

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()
    dead: list[str] = []

    for ch in channels:
        username = ch.get("username", "")
        if not username:
            continue
        try:
            jobs = _fetch_channel_sync(username, keyword_terms, max_per_channel,
                                       cutoff, security_db)
        except Exception as exc:  # noqa: BLE001
            print(f"[telegram] @{username} failed: {exc}", file=sys.stderr)
            jobs = []
        print(f"[telegram] @{username}: {len(jobs)} matching jobs", file=sys.stderr)

        if not jobs:
            # Opportunistic self-heal: a channel returning nothing might be dead,
            # not just quiet today — check, and only flag it if truly gone.
            check = validate_channel(username)
            if not check["valid"]:
                dead.append(username)

        for j in jobs:
            if j["job_id"] not in seen_ids:
                seen_ids.add(j["job_id"])
                all_jobs.append(j)
                if len(all_jobs) >= max_results:
                    break
        if len(all_jobs) >= max_results:
            break

    for username in dead:
        try:
            remove_channel(username)
            print(f"[telegram] {username} dead — removed", file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass

    return all_jobs


# --------------------------------------------------------------------------- #
# CLI — self-test only. Channel management is validate_channel/add_channel/
# remove_channel above (exposed via core/repo/telegram_channels.py + the UI);
# there's no automated *discovery* here — t.me/s/ has no public search endpoint,
# so finding new channels is a manual, user-driven "add and validate" flow.
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    results = fetch("software engineer backend", max_results=10)
    print(f"telegram_channels: {len(results)} jobs", file=sys.stderr)
    print(json.dumps(results[:3], indent=2, ensure_ascii=False))
