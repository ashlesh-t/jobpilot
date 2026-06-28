# JobPilot — Claude Code Project Guide

Automated job-hunting pipeline: scrape multiple job sources → Claude scores + filters → tailor resume → notify via Telegram.

## Architecture

Two-layer design:

- **Layer A (pure Python, no LLM):** `apify_scraper.py` → `dedupe.py` → `filter.py`. Runs via bash, writes JSON to `/tmp/jobpilot_*.json`. Must never call the LLM. Handles scraping, deduplication, and location/seen-jobs filtering only.
- **Layer B (Claude):** All intelligence lives here. Claude reads filtered jobs, scores each one inline against `profile.json`, researches salary via WebSearch, writes the CSV report, tailors resumes, and sends the Telegram digest. No scoring or filtering Python scripts.

**Hybrid scraping (Layer A):** `apify_scraper.py` runs **native scrapers first** (free, in `scripts/scrapers/`) and then the **Apify layer** only for sources that block native access. Source mix is driven by `preferences.json` `job_market_focus` (`india` | `global` | `both`).

| Source | Native? | Why |
|---|---|---|
| Internshala | ✅ native | server-rendered HTML (India freshers) |
| RemoteOK, WeWorkRemotely, Remotive, Arbeitnow, Jobicy | ✅ native | clean public JSON/RSS APIs |
| LinkedIn, Glassdoor, Indeed-IN | Apify | proxy/anti-bot required |
| Naukri | Apify | recaptcha blocks native |
| Cutshort | Apify | client-side hidden API |
| Wellfound | Apify | Cloudflare challenge |

If Apify credit is exhausted/token invalid, the pipeline degrades to native-only and (in an interactive run) prompts once for a fresh `APIFY_TOKEN` via `secrets.set_secret`.

## Key files

| Path | Role |
|---|---|
| `scripts/apify_scraper.py` | Layer A: hybrid orchestrator (native + Apify), writes `/tmp/jobpilot_raw.json` |
| `scripts/scrapers/_common.py` | Shared native-scraper helpers (canonical schema, geo filter, http) |
| `scripts/scrapers/{internshala,remoteok,weworkremotely,remotive,arbeitnow,jobicy}.py` | Native scrapers (no Apify, no LLM) |
| `scripts/dedupe.py` | Layer A: removes duplicates → `/tmp/jobpilot_deduped.json` |
| `scripts/filter.py` | Layer A: hard filters (location+city-alias, exp cap, CTC, seen-jobs) → `/tmp/jobpilot_filtered.json` |
| `scripts/ats_scorer.py` | Layer B: semantic + keyword ATS score for one job ID |
| `scripts/salary_research.py` | Layer B: market salary lookup (web fallback; AmbitionBox actor preferred) |
| `scripts/resume_tailor.py` | Layer B: edits LaTeX/DOCX resume to match JD, compiles PDF |
| `scripts/report_generator.py` | Layer B: styled **XLSX** (top 20) into `~/.claude/job-hunt-ai/reports/` from `/tmp/jobpilot_scored.json` |
| `scripts/telegram_notify.py` | Layer B: sends digest + report (xlsx/csv) + tailored resumes to Telegram |
| `scripts/drive_upload.py` | Layer B: manifest of report + tailored resumes for Google Drive |
| `scripts/secrets.py` | Secret loader/saver (keyring → `.env`). All scripts use this; never read env vars directly. |
| `scripts/setup_wizard.py` | Interactive wizard called by `setup.sh` |
| `config/actors.json` | Apify actor IDs (native sources listed under `_native_sources`) |
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
├── resumes/tailored/             # generated tailored resumes
└── reports/                      # dated XLSX reports
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

Scripts `apify_scraper.py`, `dedupe.py`, `filter.py`, and everything in `scripts/scrapers/` must never invoke the LLM. They read config, call REST/HTML/RSS APIs, and read/write the cache and `/tmp` JSON files. Violating this makes the pipeline expensive.

## Scoring (Claude inline — no script)

Claude scores each job in Layer B by reading the full JD + `profile.json` and computing:
- `jd_hard_skills`: concrete tech skills the JD actually asks for — union of `must_have_skills`
  and `nice_to_have` extracted from the JD (not the full profile skills list).
- `matched_skills`: profile skills present in JD (case-insensitive intersection of profile.skills
  with jd_hard_skills).
- `keyword_score` = `len(matched_skills) / max(len(jd_hard_skills), 1) * 100` (capped at 100).
  Scoring against JD-relevant skills, not all profile skills, so a Golang-only JD where the
  candidate has Go+Docker+K8s+CI/CD+microservices scores keyword_score ≥ 70, not ~20.
- `semantic_score` = holistic judgment of fit (0–100).
- `score` = `round(0.5 * semantic_score + 0.5 * keyword_score, 1)` — pure fit, 0–100.
  Used for threshold gates (tailoring, salary research). **Never multiply by location_weight.**
- `effective_score` = `score * location_weight` — used **only for sort order**, never for gates.

**Worked example (Swiss Re Golang):** JD asks for Go, Docker, Kubernetes, CI/CD, microservices
(5 skills). Profile has Go, Docker, K8s, GitHub Actions, gRPC → 4 matched / 5 JD skills = 80.
With semantic_score=75 → score = round(0.5×75 + 0.5×80) = 78. Crosses tailoring threshold.

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

## Very important rule — never skip this

1. Whenever you write to a file (for example `preferences.json`), first check whether the file
   exists. If it does, **read it before writing** — otherwise the write will fail with an error.