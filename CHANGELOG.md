# Changelog

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
