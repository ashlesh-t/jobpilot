---
name: jobpilot
description: Top-level overview of the JobPilot automated job-hunt pipeline. Scrapes ~10 job sources via Apify, scores postings against your resume, writes a CSV report, tailors resumes for top matches, and pushes a Telegram digest on a schedule.
---

# JobPilot

JobPilot is a personal, automated job-hunting pipeline for Claude Code. It scrapes job
boards via Apify, scores each posting against your resume, generates a CSV report, tailors
resumes for the strongest matches, and pushes a Telegram notification on a scheduled cadence.

## Two-layer architecture (token strategy)

JobPilot is built so the expensive LLM only ever sees a handful of finalists.

**Layer A — pure Python, ZERO LLM.** All scraping, deduplication, and hard filtering run as
plain `python3` scripts via bash. These scripts MUST NEVER call the LLM. They read config and
the SQLite cache, hit REST APIs, and write JSON to `/tmp`. A run that scrapes hundreds of jobs
narrows to ~5–15 survivors here at no token cost.

**Layer B — LLM reasoning.** Only the Layer-A survivors reach the LLM: semantic ATS scoring,
salary research, resume tailoring, and the final notification. This keeps a daily run cheap
enough to live inside a Pro subscription.

## Slash commands

| Command | What it does |
|---|---|
| `/job-setup` | One-time wizard. Collects preferences + parses your resume into a profile. |
| `/job-search` | The main pipeline. Scrape -> dedupe -> filter (Layer A) -> score -> research -> report -> tailor -> notify (Layer B). |
| `/job-tailor <job_id\|URL\|JD text>` | Tailor your resume to a single job and ATS-score before/after. |
| `/jobpilot-clear` | Wipe cached job IDs, score cache, and reports. Keeps preferences + resume. |
| `resume-validate` | Internal skill used by `/job-search` to score one JD against your profile. Not called directly. |

## Where things live

- Repo (this plugin): `~/projects/jobpilot`
- User data (created by `setup.sh`, NOT in the repo): `~/.claude/job-hunt-ai/`
  - `options/preferences.json` — your search criteria
  - `cache/jobs.sqlite` — seen-jobs + score cache
  - `cache/profile.json` — parsed resume
  - `resumes/` — `base.tex` / `base.docx` and `tailored/` outputs
  - `reports/` — generated CSVs
  - `.env` — secrets

## Rule for every Layer-A script

Scripts under `scripts/` named `apify_scraper.py`, `dedupe.py`, and `filter.py` run via bash
and must never invoke the LLM. They only read config, call REST APIs, and read/write the cache
and `/tmp` JSON files. Secrets are always loaded through `scripts/secrets.py`, never read from
env vars directly.
