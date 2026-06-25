# Changelog

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
