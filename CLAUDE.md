# JobPilot — Claude Code Project Guide

Automated job-hunting pipeline: scrape multiple job sources → Claude scores + filters → tailor resume → notify via Telegram.

## Architecture

Two-layer design:

- **Layer A (pure Python, no LLM):** `apify_scraper.py` → `dedupe.py` → `filter.py`. Runs via bash, writes JSON to `/tmp/jobpilot_*.json`. Must never call the LLM. Handles scraping, deduplication, and location/seen-jobs filtering only.
- **Layer B (Claude):** All intelligence lives here. Claude reads filtered jobs, scores each one inline against `profile.json`, researches salary via WebSearch, writes the CSV report, tailors resumes, and sends the Telegram digest. No scoring or filtering Python scripts.

## Key files

| Path | Role |
|---|---|
| `scripts/apify_scraper.py` | Layer A: scrapes Apify actors + Remote OK + We Work Remotely + HN, writes `/tmp/jobpilot_raw.json` |
| `scripts/dedupe.py` | Layer A: removes duplicates (seen-jobs SQLite + batch hash) → `/tmp/jobpilot_deduped.json` |
| `scripts/filter.py` | Layer A: location + seen-jobs filter only → `/tmp/jobpilot_filtered.json` |
| `scripts/resume_parser.py` | Dumb text extractor: dumps raw PDF/DOCX/TEX text to `/tmp/jobpilot_resume_raw.txt`, updates resume_hash, resets `profile_verified` if hash changed |
| `scripts/resume_tailor.py` | DOCX fallback tailoring only (used when no LaTeX). Claude handles LaTeX tailoring directly. |
| `scripts/telegram_notify.py` | Thin HTTP wrapper: sends `--digest` text + `--csv` file to Telegram. Claude builds the message. |
| `scripts/drive_upload.py` | Writes a manifest file; Claude skill uploads via Drive MCP |
| `scripts/secrets.py` | Secret loader (keyring → `.env` → error). All scripts use this; never read env vars directly. |
| `scripts/setup_wizard.py` | Interactive terminal wizard called by `setup.sh` |
| `config/actors.json` | Apify actor IDs + free source config (`free_sources`, `boards`) |
| `config/preferences.example.json` | Template for user preferences |
| `schema/init.sql` | SQLite schema for jobs_seen + score_cache |
| `setup.sh` | One-time setup: creates `~/.claude/job-hunt-ai/`, installs deps, inits DB |

## Slash commands (skills)

| Command | File | What it does |
|---|---|---|
| `/job-setup` | `skills/job-setup/SKILL.md` | Secrets check, Drive resume pick, **Claude reads + verifies resume**, preferences questionnaire |
| `/job-search` | `skills/job-search/SKILL.md` | Full pipeline (Layer A + Claude Layer B scoring, salary, CSV, tailoring, Telegram, Drive) |
| `/job-tailor <id\|URL\|JD>` | `skills/job-tailor/SKILL.md` | Claude scores + tailors resume to a single job |
| `/jobpilot-clear` | `skills/jobpilot-clear/SKILL.md` | Reset seen-job cache and score cache |

## Data directory (not in repo)

Everything personal lives in `~/.claude/job-hunt-ai/` (created by `setup.sh`):

```
~/.claude/job-hunt-ai/
├── .env                          # APIFY_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
├── options/preferences.json      # job search criteria
├── cache/jobs.sqlite             # seen-jobs + score cache
├── cache/profile.json            # resume profile (Claude-verified, profile_verified: true)
├── resumes/base.pdf              # master resume (cached from Google Drive)
├── resumes/base.tex              # LaTeX source (optional; enables PDF tailoring via tectonic)
├── resumes/tailored/             # generated tailored resumes (PDF or DOCX)
└── reports/                      # dated CSV reports
```

## profile.json and the `profile_verified` flag

`profile.json` is written by Claude during `/job-setup` Step F (or inline in `/job-search`).
`resume_parser.py` only extracts raw text — Claude does all the understanding and writes the
final structured profile.

- `profile_verified: true` → Claude has read and confirmed the profile; safe to use for scoring.
- `profile_verified: false` → resume_parser ran but Claude hasn't verified yet. The next
  `/job-search` or `/job-tailor` run will trigger inline verification before continuing.
- If `resume_hash` changes (new resume uploaded), `resume_parser.py` automatically resets
  `profile_verified` to `false`.

## Layer A invariant

Scripts `apify_scraper.py`, `dedupe.py`, and `filter.py` must never invoke the LLM. They read config, call REST APIs, and read/write the cache and `/tmp` JSON files. Violating this makes the pipeline expensive.

## Scoring (Claude inline — no script)

Claude scores each job in Layer B by reading the full JD + `profile.json` and computing:
- `matched_skills`: profile skills present in JD
- `keyword_score` = `len(matched_skills) / len(profile.skills) * 100`
- `semantic_score` = holistic judgment of fit (0–100)
- `score` = `0.5 * semantic_score + 0.5 * keyword_score`
- `effective_score` = `score * location_weight`

No `ats_scorer.py`, no `sentence-transformers`, no Jaccard fallback.

## Secrets rule

All secrets are loaded through `scripts/secrets.py` (keyring first, then `~/.claude/job-hunt-ai/.env`). No script should read `os.environ` for secrets directly.

## Job sources

**Apify (paid, requires token):** LinkedIn, Indeed, Glassdoor, Google, Naukri via primary actor.
ATS platforms (Greenhouse, Lever, Ashby, Workday) via secondary actor. India-specific actors
(Naukri dedicated, Wellfound, Cutshort) configured as `naukri_scraper`, `wellfound_scraper`,
`cutshort_scraper` in `config/actors.json` — set actor IDs from Apify marketplace when available.

**Free (no token):** Remote OK JSON API, We Work Remotely RSS, HN Who is Hiring — always fetched.

## Resume tailoring

Primary: Claude reads `base.tex`, edits it, compiles via `tectonic`. Falls back to DOCX via
`resume_tailor.py --matched-skills` when no LaTeX source. Self-caps at 5 per pipeline run.
