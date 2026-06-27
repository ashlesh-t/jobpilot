"""URL security pipeline — pure Python, NO LLM.

Tiered risk scoring for URLs extracted from Telegram job channels.
Results are cached in the url_security_cache SQLite table.

Usage:
  from url_security import check_url, open_db
  conn = open_db()
  result = check_url("https://linkedin.com/jobs/view/123", conn)
  # result = {"url": ..., "final_url": ..., "risk_score": int,
  #           "risk_label": str, "safe": bool, "threats": list, "from_cache": bool}

CLI:
  python3 scripts/url_security.py check <url>
  python3 scripts/url_security.py flush   # clear expired cache entries
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from secrets import get_secret_optional  # noqa: E402

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

ALLOWLIST: set[str] = {
    # Job boards
    "linkedin.com", "naukri.com", "internshala.com", "greenhouse.io",
    "lever.co", "workday.com", "myworkdayjobs.com", "ashbyhq.com",
    "wellfound.com", "cutshort.io", "glassdoor.com", "indeed.com",
    "amazon.jobs", "metacareers.com", "careers.google.com",
    "jobs.netflix.com", "careers.salesforce.com", "careers.microsoft.com",
    "careers.adobe.com", "stripe.com", "atlassian.com",
    "flipkartcareers.com", "razorpay.com", "freshworks.com", "zoho.com",
    # Trusted general
    "github.com", "stackoverflow.com", "telegram.org", "t.me",
}

URL_SHORTENERS: set[str] = {
    "bit.ly", "tinyurl.com", "rb.gy", "t.co", "ow.ly", "goo.gl",
    "buff.ly", "is.gd", "short.io", "cutt.ly", "tiny.cc",
}

RISK_WEIGHTS: dict[str, int] = {
    "no_https": 15,
    "url_shortener": 20,
    "redirect_chain_gt3": 20,
    "domain_age_lt30d": 30,
    "punycode": 25,
    "homoglyph_detected": 40,
    "urlhaus_hit": 100,
    "google_safe_browsing_hit": 100,
    "virustotal_malicious": 100,
}

CACHE_TTL_SAFE_H = 72
CACHE_TTL_SUSPICIOUS_H = 24
CACHE_TTL_DANGEROUS_H = 6

MAX_REDIRECTS = 5
REDIRECT_TIMEOUT = 8    # seconds per hop
WHOIS_TIMEOUT = 10


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #

def _jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))


def open_db() -> sqlite3.Connection:
    db = _jobpilot_dir() / "cache" / "jobs.sqlite"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    # Ensure table exists (safe to run repeatedly)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS url_security_cache (
          url_hash TEXT PRIMARY KEY,
          url TEXT NOT NULL,
          risk_score INTEGER DEFAULT 0,
          risk_label TEXT DEFAULT 'unknown',
          is_allowlist INTEGER DEFAULT 0,
          final_url TEXT,
          redirect_hops TEXT,
          threats TEXT,
          checked_at TEXT,
          expires_at TEXT
        )
    """)
    conn.commit()
    return conn


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_iso(label: str) -> str:
    hours = {
        "safe": CACHE_TTL_SAFE_H,
        "suspicious": CACHE_TTL_SUSPICIOUS_H,
        "dangerous": CACHE_TTL_DANGEROUS_H,
    }.get(label, CACHE_TTL_SUSPICIOUS_H)
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _cache_get(url: str, conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM url_security_cache WHERE url_hash = ?", (_url_hash(url),)
    ).fetchone()
    if not row:
        return None
    expires = row["expires_at"]
    if expires and datetime.fromisoformat(expires) < datetime.now(timezone.utc):
        return None  # expired
    return dict(row)


def _cache_set(result: dict, conn: sqlite3.Connection) -> None:
    url = result["url"]
    conn.execute(
        """
        INSERT OR REPLACE INTO url_security_cache
          (url_hash, url, risk_score, risk_label, is_allowlist, final_url,
           redirect_hops, threats, checked_at, expires_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            _url_hash(url),
            url,
            result["risk_score"],
            result["risk_label"],
            1 if result.get("allowlisted") else 0,
            result.get("final_url", url),
            json.dumps(result.get("redirect_hops", [])),
            json.dumps(result.get("threats", [])),
            _now_iso(),
            _expires_iso(result["risk_label"]),
        ),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Tier 0 — Fast checks (no network)
# --------------------------------------------------------------------------- #

def _extract_domain(url: str) -> str:
    """Return the registered domain (e.g. 'linkedin.com' from 'jobs.linkedin.com')."""
    try:
        import tldextract
        ext = tldextract.extract(url)
        return f"{ext.domain}.{ext.suffix}".lower() if ext.domain else ""
    except ImportError:
        # Fallback: parse netloc, drop subdomains (simple heuristic)
        netloc = urlparse(url).netloc.lower().lstrip("www.")
        parts = netloc.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else netloc


def _is_allowlisted(url: str) -> bool:
    domain = _extract_domain(url)
    return domain in ALLOWLIST or any(url.startswith(f"https://{a}") for a in ALLOWLIST)


def _has_https(url: str) -> bool:
    return url.lower().startswith("https://")


def _is_url_shortener(url: str) -> bool:
    return _extract_domain(url) in URL_SHORTENERS


def _has_punycode(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return "xn--" in netloc


def _check_homoglyphs(url: str) -> bool:
    """True if the domain looks like a homoglyph attack against allowlisted domains."""
    try:
        from confusable_homoglyphs import confusables
    except ImportError:
        return False
    domain = _extract_domain(url)
    for trusted in ALLOWLIST:
        if domain == trusted:
            continue
        # Levenshtein distance ≤ 2 with homoglyph substitution potential
        if abs(len(domain) - len(trusted)) <= 2:
            if confusables.is_confusable(domain, preferred_aliases=["latin"]):
                return True
    return False


# --------------------------------------------------------------------------- #
# Tier 2 — Network checks (fast, free)
# --------------------------------------------------------------------------- #

def _follow_redirects(url: str) -> tuple[str, list[str]]:
    """Follow redirect chain via HEAD (no JS). Returns (final_url, hops)."""
    hops: list[str] = []
    current = url
    try:
        import httpx
        with httpx.Client(follow_redirects=False, timeout=REDIRECT_TIMEOUT) as client:
            for _ in range(MAX_REDIRECTS):
                resp = client.head(current)
                if resp.status_code in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location", "")
                    if not loc:
                        break
                    hops.append(current)
                    current = loc if loc.startswith("http") else (
                        urlparse(current)._replace(path=loc).geturl()
                    )
                else:
                    break
    except Exception:
        # Network error or httpx not installed — return original URL
        pass
    return current, hops


def _check_domain_age(url: str) -> int | None:
    """Return domain age in days, or None if unknown."""
    domain = _extract_domain(url)
    if not domain:
        return None
    try:
        import whois
        info = whois.whois(domain)
        creation = info.creation_date
        if isinstance(creation, list):
            creation = creation[0]
        if creation:
            if not hasattr(creation, 'tzinfo') or creation.tzinfo is None:
                from datetime import timezone as _tz
                creation = creation.replace(tzinfo=_tz.utc)
            age = (datetime.now(timezone.utc) - creation).days
            return max(0, age)
    except Exception:
        pass
    return None


def _check_urlhaus(url: str) -> bool:
    """Query URLHaus (free, no key). Returns True if URL is in their blocklist."""
    try:
        resp = requests.post(
            "https://urlhaus-api.abuse.ch/v1/url/",
            data={"url": url},
            timeout=8,
        )
        data = resp.json()
        return data.get("query_status") == "is_blacklisted"
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Tier 3 — Threat intelligence APIs (key required)
# --------------------------------------------------------------------------- #

def _check_google_safe_browsing(url: str) -> bool:
    """Returns True if Google Safe Browsing flags the URL."""
    key = get_secret_optional("GOOGLE_SAFE_BROWSING_KEY")
    if not key:
        return False
    try:
        resp = requests.post(
            f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={key}",
            json={
                "client": {"clientId": "jobpilot", "clientVersion": "1.0"},
                "threatInfo": {
                    "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                                    "POTENTIALLY_HARMFUL_APPLICATION"],
                    "platformTypes": ["ANY_PLATFORM"],
                    "threatEntryTypes": ["URL"],
                    "threatEntries": [{"url": url}],
                },
            },
            timeout=8,
        )
        data = resp.json()
        return bool(data.get("matches"))
    except Exception:
        return False


def _check_virustotal(url: str) -> bool:
    """Returns True if VirusTotal marks the URL as malicious. Only called for score ≥ 50."""
    key = get_secret_optional("VIRUSTOTAL_KEY")
    if not key:
        return False
    try:
        import base64
        url_id = base64.urlsafe_b64encode(url.encode()).rstrip(b"=").decode()
        resp = requests.get(
            f"https://www.virustotal.com/api/v3/urls/{url_id}",
            headers={"x-apikey": key},
            timeout=10,
        )
        if resp.status_code != 200:
            return False
        stats = resp.json().get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
        return int(stats.get("malicious", 0)) >= 2
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Main pipeline
# --------------------------------------------------------------------------- #

def _label(score: int) -> str:
    if score >= 50:
        return "dangerous"
    if score >= 20:
        return "suspicious"
    return "safe"


def check_url(url: str, conn: sqlite3.Connection) -> dict:
    """Run the full security pipeline for a URL. Returns risk assessment dict."""
    url = url.strip()

    # Tier 0a: cache
    cached = _cache_get(url, conn)
    if cached:
        return {
            "url": url,
            "final_url": cached["final_url"] or url,
            "risk_score": cached["risk_score"],
            "risk_label": cached["risk_label"],
            "safe": cached["risk_label"] != "dangerous",
            "threats": json.loads(cached["threats"] or "[]"),
            "from_cache": True,
            "allowlisted": bool(cached["is_allowlist"]),
        }

    # Tier 0b: allowlist fast-pass
    if _is_allowlisted(url):
        result = {
            "url": url, "final_url": url, "risk_score": 0,
            "risk_label": "safe", "safe": True, "threats": [],
            "from_cache": False, "allowlisted": True,
            "redirect_hops": [],
        }
        _cache_set(result, conn)
        return result

    # Build up score
    score = 0
    threats: list[str] = []

    # Tier 1: fast local checks
    if not _has_https(url):
        score += RISK_WEIGHTS["no_https"]
        threats.append("no_https")
    if _is_url_shortener(url):
        score += RISK_WEIGHTS["url_shortener"]
        threats.append("url_shortener")
    if _has_punycode(url):
        score += RISK_WEIGHTS["punycode"]
        threats.append("punycode")
    if _check_homoglyphs(url):
        score += RISK_WEIGHTS["homoglyph_detected"]
        threats.append("homoglyph_detected")

    # Tier 2: network checks
    final_url, hops = _follow_redirects(url)
    if len(hops) > 3:
        score += RISK_WEIGHTS["redirect_chain_gt3"]
        threats.append(f"redirect_chain_{len(hops)}_hops")

    age_days = _check_domain_age(final_url)
    if age_days is not None and age_days < 30:
        score += RISK_WEIGHTS["domain_age_lt30d"]
        threats.append(f"domain_age_{age_days}d")

    if _check_urlhaus(final_url):
        score += RISK_WEIGHTS["urlhaus_hit"]
        threats.append("urlhaus_hit")

    # Tier 3: threat intelligence (only for non-trivially-safe URLs)
    if score >= 10 or _check_google_safe_browsing(final_url):
        if _check_google_safe_browsing(final_url):
            score += RISK_WEIGHTS["google_safe_browsing_hit"]
            threats.append("google_safe_browsing_hit")

    if score >= 50 and _check_virustotal(final_url):
        score += RISK_WEIGHTS["virustotal_malicious"]
        threats.append("virustotal_malicious")

    label = _label(score)
    result = {
        "url": url,
        "final_url": final_url,
        "risk_score": score,
        "risk_label": label,
        "safe": label != "dangerous",
        "threats": threats,
        "from_cache": False,
        "allowlisted": False,
        "redirect_hops": hops,
    }
    _cache_set(result, conn)
    return result


def flush_expired(conn: sqlite3.Connection) -> int:
    """Remove expired cache entries. Returns count deleted."""
    cur = conn.execute(
        "DELETE FROM url_security_cache WHERE expires_at < ?", (_now_iso(),)
    )
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: python3 url_security.py check <url>")
        print("       python3 url_security.py flush")
        sys.exit(1)

    conn = open_db()

    if args[0] == "flush":
        n = flush_expired(conn)
        print(f"Flushed {n} expired cache entries.")
        return

    if args[0] == "check" and len(args) >= 2:
        url = args[1]
        result = check_url(url, conn)
        print(json.dumps(result, indent=2))
        return

    print(f"Unknown command: {args[0]}")
    sys.exit(1)


if __name__ == "__main__":
    main()
