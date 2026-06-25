# JobPilot — Claude Code Project Guide

Automated job-hunting pipeline: scrape ~10 job sources → score against resume → tailor → notify via Telegram.

## Architecture

Two-layer design to minimise LLM token spend:

- **Layer A (pure Python, no LLM):** `apify_scraper.py` → `dedupe.py` → `filter.py`. Runs via bash, writes JSON to `/tmp/jobpilot_*.json`. Must never call the LLM.
- **Layer B (LLM):** ATS scoring, salary research, report generation, resume tailoring, Telegram + Drive push. Only touches the ~5–15 Layer-A survivors.

## Key files

| Path | Role |
|---|---|
| `scripts/apify_scraper.py` | Layer A: scrapes Apify actors, writes `/tmp/jobpilot_raw.json` |
| `scripts/dedupe.py` | Layer A: removes duplicates → `/tmp/jobpilot_deduped.json` |
| `scripts/filter.py` | Layer A: hard filters (location, CTC, seen-jobs) → `/tmp/jobpilot_filtered.json` |
| `scripts/ats_scorer.py` | Layer B: semantic + keyword ATS score for one job ID |
| `scripts/salary_research.py` | Layer B: market salary lookup |
| `scripts/resume_tailor.py` | Layer B: edits LaTeX/DOCX resume to match JD, compiles PDF |
| `scripts/report_generator.py` | Layer B: writes dated CSV into `~/.claude/job-hunt-ai/reports/` |
| `scripts/telegram_notify.py` | Layer B: sends digest + attachments to Telegram |
| `scripts/drive_upload.py` | Layer B: pushes CSV + tailored resumes to Google Drive |
| `scripts/secrets.py` | Secret loader (keyring → `.env` → error). All scripts use this; never read env vars directly. |
| `scripts/setup_wizard.py` | Interactive wizard called by `setup.sh` |
| `config/actors.json` | Apify actor IDs for each job source |
| `config/preferences.example.json` | Template for user preferences |
| `schema/init.sql` | SQLite schema for the jobs + score cache |
| `setup.sh` | One-time setup: creates `~/.claude/job-hunt-ai/`, installs deps, inits DB |

## Slash commands (skills)

| Command | File | What it does |
|---|---|---|
| `/job-setup` | `skills/job-setup/SKILL.md` | One-time wizard: secrets check, resume pick from Drive, preferences |
| `/job-search` | `skills/job-search/SKILL.md` | Full pipeline (Layer A + B) |
| `/job-tailor <id\|URL\|JD>` | `skills/job-tailor/SKILL.md` | Tailor resume to a single job |
| `/jobpilot-clear` | `skills/jobpilot-clear/SKILL.md` | Reset seen-job cache and score cache |

## Data directory (not in repo)

Everything personal lives in `~/.claude/job-hunt-ai/` (created by `setup.sh`):

```
~/.claude/job-hunt-ai/
├── .env                          # APIFY_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
├── options/preferences.json      # job search criteria
├── cache/jobs.sqlite             # seen-jobs + score cache
├── cache/profile.json            # parsed resume profile
├── resumes/base.pdf              # master resume (cached from Google Drive)
├── resumes/tailored/             # generated tailored resumes
└── reports/                      # dated CSV reports
```

## Layer A invariant

Scripts `apify_scraper.py`, `dedupe.py`, and `filter.py` must never invoke the LLM. They read config, call REST APIs, and read/write the cache and `/tmp` JSON files. Violating this makes the pipeline expensive.

## Secrets rule

All secrets are loaded through `scripts/secrets.py` (keyring first, then `~/.claude/job-hunt-ai/.env`). No script should read `os.environ` for secrets directly.

## Resume tailoring

`resume_tailor.py` reads `~/.claude/job-hunt-ai/resumes/base.tex` (LaTeX) or `base.docx`, edits it to match the JD keywords, then compiles to PDF via `tectonic`. Falls back to DOCX if tectonic is not installed. Self-caps at 5 tailored resumes per pipeline run.
