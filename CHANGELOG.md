# Changelog

## v1.6.1 — 2026-07-08

### Release title: "PyPI Rename" (patch)

The first PyPI publish attempt for v1.6.0 failed: `claude-jobpilot`'s trusted-publisher
project name didn't match the pending publisher registered on PyPI, so the OIDC-based
create-new-project upload was rejected.

### Fixes
- **PyPI package renamed `claude-jobpilot` → `jobpilot-ai`** to match the registered trusted
  publisher. Updated `pyproject.toml`, `jobpilot/__init__.py`, `.github/workflows/release.yml`,
  and every packaging wrapper (`aur/PKGBUILD`, `homebrew/jobpilot.rb`, `scoop/jobpilot.json`) and
  doc (`README.md`, `GETTING_STARTED.md`, `packaging/README.md`) that referenced the old name.
  The installed command is unchanged: `jobpilot`.

---

## v1.6.0 — 2026-07-06

### Release title: "Install Anywhere — Plugin, pipx & Cross-Platform Setup"

Makes JobPilot genuinely installable across Linux/macOS/**Windows**, three ways, without the
old bash-only `setup.sh` limitation.

### What's new

**Real Claude Code plugin** (`/plugin install`)
- Added `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` (validated with
  `claude plugin validate`). Users register the skills cross-platform with
  `/plugin marketplace add ashlesh-t/jobpilot` → `/plugin install jobpilot@jobpilot`.
- Skills now resolve repo paths via `${CLAUDE_PLUGIN_ROOT}` when installed as a plugin, and
  fall back to the working directory from a git clone — so `scripts/…` and `config/…` work in
  both modes.

**pipx / PyPI package** (`pipx install "jobpilot-ai[server]"`)
- New `pyproject.toml` (dist name `jobpilot-ai`, command `jobpilot`) with a `[server]`
  extra for the web UI. The runtime tree is bundled inside the package so an installed copy has
  everything on disk in the layout the code expects (`jobpilot/paths.py` resolves it) — no
  import refactor.
- New `jobpilot` CLI: `jobpilot setup` / `serve` / `doctor` / `--version`. Verified end-to-end
  from a clean wheel install (setup builds the data dir + SQLite; serve boots the FastAPI UI).

**Cross-platform setup (Windows parity)**
- New `scripts/jobpilot_setup.py` — a stdlib-only port of `setup.sh` that creates the SQLite
  cache with Python's `sqlite3` module (no external `sqlite3` CLI). `setup.sh` is now a thin
  shim to it; Windows users run `python scripts/jobpilot_setup.py`.

**Native package wrappers** (thin, over the one PyPI package)
- `packaging/aur/PKGBUILD` (`yay -S jobpilot-ai`), `packaging/homebrew/jobpilot.rb`
  (`brew install ashlesh-t/tap/jobpilot`), `packaging/scoop/jobpilot.json`
  (`scoop install jobpilot`) — see `packaging/README.md`. Publish + verify per-OS after the
  first PyPI release.

**Release automation**
- `.github/workflows/release.yml` publishes the sdist + wheel to PyPI on a `v*` tag via Trusted
  Publishing (no stored token).

### Notes
- The old README `claude plugin install github:…` one-liner (which never worked — no manifest
  existed) is replaced by the marketplace flow above.
- PyPI name: the package is `jobpilot-ai` (the bare `jobpilot` name was taken; `claude-jobpilot`
  was also renamed away from before first publish); the installed command is still `jobpilot`.

---

## v1.5.1 — 2026-07-06

### Release title: "Ship It, Wired Up" (patch)

Post-release audit fixes for the v1.5.0 shipping layer. No breaking changes.

### Fixes
- **Discord now works on real runs.** The delivery path (`scripts/telegram_notify.py`,
  called by `/job-search` step B7) previously only sent to Telegram — the `notify_channels`
  Discord toggle in the UI had no effect on an actual run. It now fans the same digest +
  XLSX report + tailored resumes out to every non-Telegram channel in `notify_channels`,
  guarded so an extra-channel failure never affects Telegram delivery.
- **`setup.sh` no longer risks breaking on optional service deps.** The FastAPI/uvicorn/
  APScheduler/`claude-agent-sdk` dependencies were moved out of `requirements.txt` into a
  new **`requirements-server.txt`**, so the core chat-driven install can't fail because an
  optional service dependency won't resolve. Install the service with
  `pip install -r requirements-server.txt`.
- **Anthropic API engine no longer hardcodes a model.** `claude_api` defaulted to a fixed
  model id and passed it unconditionally; an invalid id would have broken every metered run.
  It now uses the Agent SDK's default and only pins a model if `preferences.engine.model`
  is set explicitly.
- **`.env.example` refreshed** — removed the stale Google-Drive-upload service-account entry
  (Drive upload was removed in v1.4-era issue #12) and added the new optional secrets:
  `ANTHROPIC_API_KEY`, `DISCORD_WEBHOOK_URL`, `TELEGRAM_API_ID` / `TELEGRAM_API_HASH`,
  `GEMINI_API_KEY`.
- **`plugin.toml` version** bumped `0.1.0` → `1.5.1` (it had never tracked the releases).
- Docs updated to install the service from `requirements-server.txt`.

### Testing
Adds `tests/test_delivery.py` (fan-out excludes Telegram, forwards the digest, no-ops when
only Telegram is configured, and never raises on missing prefs). Full suite now 20 tests, all
green with no LLM or network.

---

## v1.5.0 — 2026-07-06

### Release title: "Ship It — Local Automation Service, Web UI & Multi-Engine"

JobPilot can now run **headless on a schedule** and be driven from a **polished local web
UI**, without a human in a chat. The pipeline logic is unchanged — a new shipping layer wraps
it and adds a provider abstraction so the same `/job-search` program runs under a Claude
subscription, the Anthropic API, or (later) Gemini/Antigravity.

### Breaking changes
- **`scripts/secrets.py` renamed to `scripts/jp_secrets.py`.** The old module name shadowed
  Python's stdlib `secrets` (which FastAPI/Starlette import), breaking the service. All repo
  imports, docs, and the permission allowlist were updated. If you have external scripts doing
  `from secrets import get_secret`, change them to `from jp_secrets import get_secret`. The
  documented CLI is now `python3 scripts/jp_secrets.py`.
- `preferences.json` gains an `engine` block (`{provider, model, permission_mode}`) and
  `notify_channels` (default `["telegram"]`). Both have safe defaults — no migration required.

### What's new

**Local control service (`server/`) + web UI**
- `python -m server` starts a FastAPI service at `http://127.0.0.1:8787` with a single-file
  SPA (`server/ui/index.html`).
- **Live Run view** mirrors the Claude Code harness: a stage timeline (scrape → dedupe →
  filter → score → salary → report → tailor → notify) lights up in real time over SSE, with
  per-source job counts, activity log, and the final top-matches table + digest.
- **Setup / Schedule / Connections** tabs: pick an engine, store secrets (via the keyring/.env
  through `jp_secrets`), edit search preferences, manage IST schedule slots, and connect
  Telegram/Discord.
- APScheduler fires `/job-search` at each `schedule_slots_ist` slot (previously an unused
  preference). `python -m server install-service` writes a systemd/launchd unit.
- Optional tray launcher: `python -m server.tray`.

**Multi-engine execution (`engines/`)**
- **Claude Code** (`claude_code`) — runs `/job-search` headless under a Pro/Max subscription
  (`claude -p … --output-format stream-json`); no per-token cost, reuses `SKILL.md` verbatim.
- **Anthropic API** (`claude_api`) — runs it metered via the Claude Agent SDK, loading the
  `SKILL.md` body as the system prompt so pipeline logic is never duplicated.
- **Gemini/Antigravity** (`gemini`) — interface-ready stub for a future release.
- Engines are chosen in Setup; unusable ones are greyed out with the reason. `/job-search`
  now honours an `OVERRIDE: force RUN_MODE=<full|native>` prompt so the UI's mode buttons work.

**Pluggable notifications (`scripts/notify/`)**
- Delivery is now channel-agnostic (`telegram`, `discord`) selected by
  `preferences.notify_channels`. Discord is a simple webhook (paste URL + test in the UI).

**Live run events (`scripts/run_events.py`)**
- Layer A emits structured stage/count events to a per-run `events.jsonl` (a no-op unless a run
  is active, so plain CLI use is unchanged). This is what makes the UI mirror the backend
  precisely.

**Health check ("doctor")**
- `GET /doctor` (and the Connections tab) returns a ✅/⚠️/❌ table for engines, notifiers,
  Apify token, Telegram session, and — in live mode — each native source, so you can tell a
  dead source from an over-eager filter.

**`skills/job-search/SKILL.md` rewritten**
- Removed merge scars: a duplicated "Step 0b", scraping steps jammed into profile verification,
  and **two conflicting Layer B specs**. It is now one linear, unambiguous flow with the
  canonical scoring formula (`keyword_score` against `jd_hard_skills`, XLSX report, Telegram/
  Discord delivery). This matters more now that both engines load it as the single source of
  truth. All stale Google-Drive-upload references purged (Drive is only the resume *source*).

### Testing
- New `tests/` suite (17 tests): event emission/no-op, tool→stage mapping, stream-json parsing,
  notifier availability + Discord chunking, RunManager fan-out/busy-rejection/persistence, and a
  full HTTP+SSE run via a fake engine. `pytest -q` runs green with no LLM or network.

### Upgrading
Run `pip install -r requirements.txt` (adds `fastapi`, `uvicorn`, `apscheduler`,
`sse-starlette`, `claude-agent-sdk`). Update any `from secrets import …` in your own scripts to
`from jp_secrets import …`. The chat-driven `/job-search` and `/job-setup` flows are unchanged.

---

## v1.4.0 — 2026-06-28

### Release title: "Telegram Jobs & Scoring Hardening"

- **Telegram channel scraper `--discover` mode** — validates the seed channel list against the
  live network, searches for additional active India job channels, and rewrites
  `config/telegram_channels.json` with only reachable channels. Private channels supported via
  numeric `id`. Referral detection tags posts that offer a referral.
- **Secure Telegram API credential setup** with OS-specific copy-paste commands (nothing pasted
  into chat).
- **Scoring & reliability fixes**: apply-URL preservation map (links never dropped during
  scored-JSON reconstruction), location aliasing via `locations.json`, a firmer autonomy
  contract for unattended runs, and additional native scrapers (YC WaaS, Hasjob, Instahyre,
  Wellfound public). `instahyre` / `wellfound_rss` / `linkedin_guest` disabled where endpoints
  are blocked. Soft CTC filter for early-career candidates (`experience_years ≤ 2`).

---

## v1.3.0 — 2026-06-27

### Release title: "Free-First Scraping & Credit Resilience"

- **Six free native scrapers** run before Apify is ever called: Internshala (India freshers),
  RemoteOK, WeWorkRemotely, Remotive, Arbeitnow, Jobicy — public JSON/RSS, no token.
- **Apify credit resilience**: tiered scheduling (alternating native/full days), 3-slot key
  rotation (`APIFY_TOKEN` → `_2` → `_3`), and a Telegram alert with recovery steps on full
  exhaustion. Update tokens via `python3 scripts/apify_token_update.py --slot 2`.
- **Telegram job-channel scraper** (Telethon MTProto) reading curated public India channels,
  with every URL screened by a new **URL security pipeline** (allowlist → local checks →
  redirect/WHOIS/URLHaus → optional Safe Browsing/VirusTotal; results cached in SQLite).
- **Styled XLSX report** (colour-coded by score, hyperlinked apply URLs, frozen header),
  **career-page crawl** for target companies, and an **application-deadline filter** (IST).
- Upgrading: `pip install -r requirements.txt` for `telethon`, `tldextract`, `httpx`,
  `python-whois`, `confusable-homoglyphs`.

---

## v1.2.0 — 2026-06-27

### Release title: "Reliability & Scoring Quality"

Fixes 7 real-pipeline bugs discovered on first production run: wrong Apify input schema
causing 0-job scrapes, LinkedIn jobs with no JD silently getting vibes-based scores,
experience mismatches boosting clearly-wrong roles, the 372→30 hidden job cut, a
tailoring threshold too high for freshers, shallow salary research, and no feedback loop.
Introduces the lessons cache so Claude never rediscovers the same actor schema bugs.

---

### Breaking changes
- `preferences.json` has two new fields: `top_n_report` (default 50) and the existing
  `score_threshold` now drives a fresher-aware effective threshold (auto-lowered to 60
  when `experience_years == 0`). If you have a custom `preferences.json`, add `"top_n_report": 50`.

### What's new

**Apify lessons cache (`~/.claude/job-hunt-ai/cache/apify_lessons.json`)**
- Persistent JSON file that stores the correct input schema for each Apify actor
- `setup.sh` seeds it from `config/apify_lessons_seed.json` on first run
- Ships pre-populated with the confirmed fix for `openclawai/job-board-scraper`:
  `searchTerms` array (not `keywords` string) — the root cause of 0-job scrapes on 3 of 4 runs
- `/job-search` reads the file before calling actors, WebSearches any post-run failures,
  writes diagnosis back to the cache so the mistake is never repeated

**Retry logic with 0-result detection**
- `run_apify_actor()` retries up to 3 times with 2s backoff
- 0 items returned counts as a soft failure and triggers retry (previously silent)
- `/tmp/jobpilot_scrape_status.json` written after each run with per-source counts,
  status (`ok` / `failed` / `empty`), and attempt count

**`has_jd` flag on every job**
- `normalize()` sets `has_jd: bool` — true if JD text is > 100 chars
- LinkedIn jobs (which routinely return title+company only) are flagged
- In Layer B: no-JD jobs get `semantic_score = 30` (neutral) instead of a fake semantic score,
  are excluded from resume tailoring, and appear with `⚠️ No JD available` in the CSV

**Experience gate in scoring**
- B1 now hard-drops jobs where the JD explicitly requires more years than
  `profile.experience_years + 2` (patterns: "X+ years", "minimum X years", "X-Y years required")
- Hard-dropped jobs get `score = 0`, `why = "Hard drop: requires Xyr, profile has Yyr"`,
  appear at the bottom of the CSV — no salary research, no tailoring

**Full CSV output (no hidden job cap)**
- Previously only top 30 jobs went into the CSV — jobs ranked 31–262 were silently dropped
- Now ALL scored jobs are written to the CSV, sorted by `effective_score`
- Telegram digest shows top 5 (was top 3)
- Three new CSV columns: `has_jd`, `experience_gate_drop`, `required_years`

**Fresher-aware tailoring threshold**
- When `experience_years == 0`, effective tailoring threshold = `min(score_threshold, 60)`
- At default `score_threshold = 75`, freshers tailor any job scoring 60+ (was 75+)
- Prevents the "only 1 job qualified for tailoring" outcome for entry-level profiles

**Improved salary research**
- 3 targeted queries per job instead of 1 generic query
- Company-specific: `"<company> India salary software engineer 2025 site:glassdoor.co.in OR ambitionbox.com"`
- Role-specific: `"<role> fresher salary <city> LPA 2025"`
- Placement-specific: `"<company> CTC package freshers campus placement 2025"`
- Explicit `"No data found"` when all 3 queries return nothing — no more invented ranges
- Market-average results labeled as such rather than presented as company-specific data

**Feedback loop**
- New `user_feedback` SQLite table: `job_id`, `status`, `notes`, `feedback_date`
- New `scripts/feedback.py`: `python3 scripts/feedback.py <job_id> <status> [--notes "text"]`
- New `/job-feedback` skill: lists recently applied/tailored jobs, prompts for outcomes
  (applied / rejected / interview / offer / ghosted), writes to DB
- `/job-search` reads feedback at B2 and surfaces patterns (e.g. high-scoring company
  type consistently rejects) — does not auto-adjust scores, just reports the signal

---

### Bug fixes
- **0 jobs from openclawai/job-board-scraper** — wrong input field name (`keywords` vs
  `searchTerms` array). Fixed via lessons cache with field_overrides + value_transforms.
- **LinkedIn jobs scored on vibes** — no JD text but semantic scoring ran anyway. Fixed
  with `has_jd` flag and neutral baseline.
- **Mercedes-Benz scored 92.5 for an 8-year role** — no experience gate existed. Fixed
  with explicit required_years extraction and hard-drop logic.
- **372 → 30 silent cut** — only top 30 in CSV. Fixed: CSV now has all jobs.
- **Only 1 resume tailored** — threshold 75 too high for fresher scores of 60–70. Fixed
  with fresher-aware effective threshold.
- **Salary ranges were guesses** — generic market averages presented as company data. Fixed
  with 3-query approach and explicit "No data found" label.

---

### Added files
- `config/apify_lessons_seed.json` — seed lessons cache with known actor schemas
- `scripts/feedback.py` — CLI wrapper for recording job outcomes
- `skills/job-feedback/SKILL.md` — `/job-feedback` command

---

## v1.1.0 — 2026-06-26

### Release title: "Claude-Native Intelligence"

Architecture overhaul: all scoring, filtering judgment, salary research, and report generation move from Python scripts into Claude skills. Python now only handles what it must — Apify API calls, SQLite deduplication, and Telegram/Drive HTTP wrappers. Fixes the 0-job and max-score-17 bugs, adds free job sources, and introduces Claude-verified resume profiles.

---

### Breaking changes
- `scripts/ats_scorer.py`, `scripts/salary_research.py`, `scripts/report_generator.py` have been **deleted**. If you called these directly in custom scripts, switch to the `/job-search` skill instead.
- `telegram_notify.py` now requires `--digest "text"` to be passed by the caller. Running it with no arguments no longer sends a message.
- `resume_tailor.py` no longer accepts `--docx` flag; DOCX mode is now the only mode (LaTeX tailoring is handled by Claude directly). It now accepts `--matched-skills skill1,skill2` instead.

### What's new

**Apify MCP integration**
- `/job-search` now tries to call Apify actors directly via the Apify MCP server (`mcp.apify.com`) when it is connected in Claude Desktop — no Python HTTP code involved, no token in config files
- Auth is OAuth-based; users add the MCP once via Claude Desktop → Settings → Connections → `https://mcp.apify.com/sse`
- Falls back automatically to the Python SDK if MCP is unavailable (e.g. scheduled tasks without MCP connection)
- `scripts/apify_scraper.py` accepts `--free-only` flag for use when MCP handles the Apify calls and only free sources (Remote OK, WWR, HN) need to run

**apify-client Python SDK (replaces raw `requests` calls)**
- `scripts/apify_scraper.py` now uses the official `apify-client` Python SDK instead of hand-rolled `requests` calls
- Benefits: proper retries, pagination via `iterate_items()`, clean auth, official support
- Raw requests fallback still included if `apify-client` is not installed
- `apify-client>=1.8` added back to `requirements.txt` (previously listed but never imported — now actually used)

**Claude-native scoring (replaces `ats_scorer.py`)**
- ATS scoring is now done by Claude inline in Layer B — no `sentence-transformers`, no Jaccard fallback, no "max score 17" ceiling
- Score formula: `0.5 × semantic_score + 0.5 × keyword_score` where both components are Claude's judgment against the full JD and `profile.json`
- `matched_skills`, `missing_keywords`, `why`, and `jd_summary` all produced by Claude with real language understanding

**Claude-native salary research (replaces `salary_research.py`)**
- Salary lookup now uses Claude's `WebSearch` against AmbitionBox, Glassdoor, and Levels.fyi
- More current, more accurate, and no DuckDuckGo HTML scraping fragility

**Claude-native report generation (replaces `report_generator.py`)**
- Claude writes the dated CSV directly using the Write tool after scoring all jobs in memory
- Eliminates the awkward `import ats_scorer` chain that caused errors when the scorer failed

**Profile verification — `profile_verified` flag**
- `resume_parser.py` is now a dumb text extractor only: dumps raw PDF/DOCX/TEX text to `/tmp/jobpilot_resume_raw.txt`, computes file hash, and resets `profile_verified: false` if the hash changed
- `/job-setup` now includes Step F: Claude reads the raw resume text, asks targeted clarifying questions (missing company names, empty projects, unclear skills), and writes a complete, accurate `profile.json`
- `profile_verified: true` is set only after Claude has interactively confirmed the profile
- `/job-search` checks this flag at startup and runs inline verification if `false` — no separate `/job-setup` call needed

**Smarter Layer B filtering (replaces keyword pre-filter)**
- `filter.py` now does **location + seen-jobs only** — the broken keyword/CTC hard-filter that caused 0 results for freshers is removed
- Claude does a two-pass relevance check in Layer B: quick title/snippet scan to drop clearly irrelevant jobs, then full ATS scoring on survivors
- CTC no longer hard-filtered (most fresher JDs don't state salary, so the old filter was dropping all of them)

**New free job sources (no Apify token cost)**
- Remote OK public JSON API — 100+ remote jobs, always fetched
- We Work Remotely RSS feeds (programming, backend, full-stack categories) — always fetched
- Both are fetched in `apify_scraper.py` alongside paid actors

**India-specific Apify actor slots**
- `config/actors.json` now has `naukri_scraper`, `wellfound_scraper`, `cutshort_scraper` fields
- Actor IDs are empty by default — fill them from the Apify marketplace to enable each source
- Existing `primary_scraper` and `ats_scraper` actors unchanged

**Telegram notifier simplified**
- Claude builds the digest text in the skill and passes it via `--digest "text"` arg
- Script is now a thin HTTP wrapper with no message-building logic
- `--test` flag unchanged

---

### Bug fixes
- **0 jobs after filter** — caused by keyword pre-filter requiring a profile skill to appear in the JD verbatim, and CTC filter dropping all jobs where salary was unknown (i.e. most freshers). Both filters removed.
- **ATS max score ~17** — caused by dividing matched skills by total JD token count (hundreds) instead of profile skill count. Fixed by moving scoring to Claude.
- **profile.json bad data** — `education.degree` was being set to city names; `projects` was always empty. Fixed by making `resume_parser.py` a text-only extractor and having Claude write the profile interactively.

---

### Removed
- `scripts/ats_scorer.py`
- `scripts/salary_research.py`
- `scripts/report_generator.py`
- `sentence-transformers` and `numpy` from `requirements.txt` (no longer needed)
- `apify-client` from `requirements.txt` (scraper uses `requests` directly, not the Apify SDK)
- `build_digest()` function from `telegram_notify.py`
- CTC/company/keyword hard-filters from `filter.py`
- All field-extraction intelligence from `resume_parser.py`

---

### Known limitations / roadmap
- India-specific Apify actor IDs (Naukri, Wellfound, Cutshort) need to be found in the Apify marketplace and filled in manually — actor discovery is not automated
- `.mcpb` one-click installer — not yet available
- pip-installable helper package — planned
- Only tested on Linux and macOS; Windows support is best-effort

---

## v1.0.0 — 2026-06-25

### Release title: "Pipeline Complete"

First stable release. The full two-layer job-hunt pipeline is live end-to-end: scrape, score, tailor, and notify — fully automated on a schedule.

---

### What's new

**Core pipeline (Layer A — pure Python)**
- `apify_scraper.py` — scrapes ~10 job sources (LinkedIn, Indeed, Glassdoor, Google Jobs, Naukri, Greenhouse, Lever, Ashby, Workday, HN "Who is hiring") via Apify actors
- `dedupe.py` — deduplicates raw results against a local SQLite seen-jobs cache
- `filter.py` — hard-filters by location, CTC floor, role type, and freshness; writes finalists to `/tmp/jobpilot_filtered.json`

**Core pipeline (Layer B — LLM)**
- `ats_scorer.py` — semantic (60%) + keyword (40%) ATS scoring against your parsed resume profile
- `salary_research.py` — market salary lookup per company/role/location
- `resume_tailor.py` — edits LaTeX or DOCX resume to match JD keywords and compiles PDF via tectonic; self-caps at 5 tailored resumes per run
- `report_generator.py` — writes a dated CSV report with all scored jobs
- `telegram_notify.py` — sends a formatted digest, the CSV, and tailored PDF attachments to your Telegram chat
- `drive_upload.py` — pushes the CSV and tailored resumes to a "JobPilot Reports" folder in Google Drive via MCP

**Setup & config**
- `setup.sh` — one-shot bootstrap: creates `~/.claude/job-hunt-ai/`, installs Python deps, inits SQLite schema, and runs the secrets wizard
- `scripts/secrets.py` — unified secret loader (OS keyring → `.env` → error); all scripts use this
- `config/actors.json` — Apify actor IDs for each job source
- `schema/init.sql` — SQLite schema for jobs + score cache

**Slash commands (Claude Code skills)**
- `/job-setup` — pre-flight checks, resume picker from Google Drive, preferences wizard
- `/job-search` — full pipeline run (Layer A + B), designed to run autonomously in a scheduled task
- `/job-tailor <job_id|URL|JD>` — tailor resume to a single job and compare ATS score before vs after
- `/jobpilot-clear` — wipe seen-job cache, score cache, and reports while keeping preferences and resume

**Fresher / experience-aware search**
- Claude infers seniority keywords from `experience_years` and `graduation` before Layer A runs, so the Apify query is automatically enriched without hardcoding terms in Python

**Location priority**
- `filter.py` applies a ranked location match so preferred cities score higher than generic "India" matches

**Google Drive MCP integration**
- `/job-search` uploads reports and tailored resumes to Drive automatically when the MCP connector is active; skips gracefully if Drive is unavailable

**Telegram PDF attachments**
- `telegram_notify.py` now sends tailored resume PDFs as direct attachments alongside the CSV digest

---

### Repo hygiene (this release)
- `.claude/` and `.claude-plugin/` excluded from version control; both added to `.gitignore`
- `venv/` added to `.gitignore`
- Hardcoded author GitHub URLs replaced with `ashlesh-t` throughout docs
- `CLAUDE.md` added — project architecture reference for Claude Code
- `GETTING_STARTED.md` — full beginner walkthrough (Apify setup, Telegram bot, secrets, Drive, scheduling)

---

### Known limitations / roadmap
- `.mcpb` one-click installer — not yet available
- pip-installable helper package — planned
- Only tested on Linux and macOS; Windows support is best-effort
