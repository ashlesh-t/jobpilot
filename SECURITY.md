# Security Policy

## Supported versions

Only the latest release on `main` receives security fixes.

| Version | Supported |
|---------|-----------|
| 1.3.x   | ✅ Yes    |
| < 1.3   | ❌ No     |

---

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email: ashleshat5@gmail.com  
Subject line: `[JobPilot Security] <short description>`

Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce
- Any suggested fix (optional but appreciated)

You will receive a response within 48 hours. If the issue is confirmed, a fix will be released within 7 days for critical issues.

---

## Security model

JobPilot runs locally on your machine. There is no server, no cloud backend, and no data
leaves your system except through the integrations you explicitly configure (Apify, Telegram,
Google Drive). The sections below describe how each sensitive area is handled.

### Secret storage

All API tokens and credentials are stored through `scripts/secrets.py`, which tries:
1. **OS keyring** (preferred) — tokens stored in the system keychain (GNOME Keyring, macOS Keychain, Windows Credential Manager)
2. **`~/.claude/job-hunt-ai/.env`** fallback — plain-text file in your home directory, mode 600

**Secrets that JobPilot stores:**

| Secret key | What it is | Used by |
|---|---|---|
| `APIFY_TOKEN` / `_2` / `_3` | Apify API tokens (up to 3 slots) | `apify_scraper.py` |
| `TELEGRAM_BOT_TOKEN` | Bot API token for sending digests | `telegram_notify.py` |
| `TELEGRAM_CHAT_ID` | Your Telegram chat/channel ID | `telegram_notify.py` |
| `TELEGRAM_API_ID` | MTProto app ID (from my.telegram.org) | `telegram_channels.py` |
| `TELEGRAM_API_HASH` | MTProto app hash (from my.telegram.org) | `telegram_channels.py` |
| `GOOGLE_SAFE_BROWSING_KEY` | Google Safe Browsing API key (optional) | `url_security.py` |
| `VIRUSTOTAL_KEY` | VirusTotal API key (optional) | `url_security.py` |

**Rules enforced in code:**
- No script reads secrets from `os.environ` directly — all access goes through `get_secret()` / `get_secret_optional()` in `secrets.py`
- Secrets are never written to log files, `/tmp` files, or the CSV/XLSX report
- Apify tokens are never sent to Telegram. Token updates always happen in the terminal via `scripts/apify_token_update.py`, which uses `getpass.getpass()` so the token is never echoed

### Telegram channel scraping

The Telegram channel scraper uses the Telethon MTProto user client (not the bot API) to read
public job channels. Security properties:

- **Read-only**: the client only calls `iter_messages()` on public channels — it never posts, edits, or deletes messages on your behalf
- **Session file**: stored at `~/.claude/job-hunt-ai/cache/telegram.session` — treat this file like a password; if compromised, an attacker could read your Telegram messages. Do not commit it to version control (it is in `.gitignore`)
- **Public channels only**: `config/telegram_channels.json` lists only public channels. The scraper does not join private groups or access your private messages
- **First-time auth**: phone number + OTP entered in the terminal only; never sent to Claude or any external service beyond Telegram's own API

### URL security pipeline

Every URL extracted from Telegram job channel messages is run through a 4-tier risk check
before the job is accepted into the pipeline:

1. **Allowlist** — 20+ trusted job board and company domains pass instantly (linkedin.com, naukri.com, greenhouse.io, etc.)
2. **Local checks** — HTTPS enforcement, URL shortener detection, punycode / IDN homoglyph detection
3. **Network checks** — redirect chain following (max 5 hops), domain age via WHOIS, URLHaus free blocklist
4. **Threat intelligence** — Google Safe Browsing API, VirusTotal (only if score ≥ 50)

Risk scores: 0–19 = safe, 20–49 = suspicious (job flagged), 50+ = dangerous (job dropped).
Results are cached in SQLite to avoid redundant network calls.

**What this protects against:**
- Phishing links disguised as job apply URLs
- Homoglyph attacks (e.g. `lіnkedin.com` with Cyrillic `і`)
- Newly registered domains (< 30 days old) used in job scams
- URL shorteners that hide the final destination
- Known malware / drive-by download domains (URLHaus, Safe Browsing)

**What it does NOT protect against:**
- Malicious content on pages that pass all URL checks (JavaScript-based attacks)
- Legitimate-looking domains used for spearphishing that are not yet in any blocklist
- Scraper itself is unauthenticated — it cannot access private channels even if listed

### Data stored locally

JobPilot stores the following data in `~/.claude/job-hunt-ai/`:

| Path | Contents | Sensitivity |
|---|---|---|
| `.env` | API tokens | High — treat like a password file |
| `cache/jobs.sqlite` | Job IDs seen, scores, feedback, URL security cache | Medium |
| `cache/profile.json` | Your resume data (skills, experience, projects) | Medium |
| `resumes/` | Base resume PDF + tailored variants | Medium |
| `reports/` | Dated XLSX/CSV job reports | Low |
| `cache/telegram.session` | Telethon session (equivalent to Telegram login) | High |
| `cache/run_state.json` | Scheduling state, exhausted Apify slots | Low |

None of this data is sent anywhere except:
- Job scores and resume details → Apify actors (when running Apify scraping)
- Digest text + report file → your own Telegram bot
- Report + resumes → your own Google Drive

### Layer A invariant

The scraper layer (`apify_scraper.py`, `filter.py`, `dedupe.py`, all files in `scripts/scrapers/`)
never calls the LLM. This is a deliberate security and cost boundary: if a malicious job
description attempted a prompt injection attack, it would reach Claude only after location/
dedup/deadline filtering has already run, and Claude is explicitly instructed to score — not
to execute any instructions found in job descriptions.

---

## Responsible use

JobPilot scrapes job boards using public APIs and unauthenticated endpoints. Please:
- Do not configure it to run more than once per day — most native sources have implicit rate limits
- Do not use it to spam apply to jobs without reviewing the scored output
- Do not use the Telegram channel scraper to harvest contact information from job posters
