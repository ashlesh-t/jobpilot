# JobPilot — Claude Code Project Guide

Automated job-hunting pipeline: scrape multiple job sources → Claude scores + filters → tailor resume → notify via Telegram.

## Architecture

Two-layer design:

- **Layer A (pure Python, no LLM):** `apify_scraper.py` → `dedupe.py` → `filter.py`. Runs via bash, writes JSON to `/tmp/jobpilot_*.json`. Must never call the LLM. Handles scraping, deduplication, and location/seen-jobs filtering only.
- **Layer B (Claude):** All intelligence lives here. Claude reads filtered jobs, scores each one inline against `profile.json`, researches salary via WebSearch, writes the CSV report, tailors resumes, and sends the Telegram digest. No scoring or filtering Python scripts.

**Shipping layer (optional, `engines/` + `server/`):** A local FastAPI service wraps the
whole `/job-search` pipeline so it can run on a schedule and be driven from a web UI —
without a human in a chat. It never contains pipeline logic; it only *invokes* the pipeline
through a provider **engine** and streams progress.

- **`engines/` — RunEngine provider adapters.** `claude_code` runs `/job-search` headless
  under a Pro/Max subscription (`claude -p … --output-format stream-json`, no per-token
  cost, reuses `SKILL.md` verbatim); `claude_api` runs it via the Claude Agent SDK (metered,
  loads the `SKILL.md` body as the system prompt so logic isn't duplicated); `gemini` is an
  interface-ready stub. Both provider streams normalize to one `RunEvent` shape.
- **`server/` — the service.** `app.py` (FastAPI + SSE), `run_manager.py` (orchestrates one
  run, tails Layer A's `events.jsonl`, fans events to the UI), `scheduler.py` (APScheduler
  over `schedule_slots_ist`), `telegram_auth.py` (browser OTP flow), `doctor.py` (health
  checks), `ui/index.html` (single-file SPA with a harness-style live run view). Run it with
  `python -m server` → http://127.0.0.1:8787.
- **`scripts/run_events.py`** — Layer A emits stage/count events here (no-op unless a run is
  active); this is what makes the live UI mirror the backend precisely.
- **`scripts/notify/`** — pluggable delivery (`telegram`, `discord`); `preferences.notify_channels`
  selects channels. The single-run digest still goes through `telegram_notify.py`.

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
| `scripts/resume_tailor.py` | Layer B: edits LaTeX/DOCX resume to match JD, compiles PDF |
| `scripts/record_scored.py` | Layer-B-invoked, pure Python: persists scored jobs into `jobs_seen` + `score_cache` (cross-run memory) |
| `scripts/feedback.py` | Records `/job-feedback` outcomes into `user_feedback` |
| `scripts/report_generator.py` | Layer B: styled **XLSX** (top 20) into `~/.claude/job-hunt-ai/reports/` from `/tmp/jobpilot_scored.json` |
| `scripts/telegram_notify.py` | Layer B: sends digest + report (xlsx/csv) + tailored resumes to Telegram |
| `scripts/jp_secrets.py` | Secret loader/saver (keyring → `.env`). All scripts use this; never read env vars directly. |
| `scripts/setup_wizard.py` | Interactive wizard called by `setup.sh` |
| `config/actors.json` | Apify actor IDs (native sources listed under `_native_sources`) |
| `config/preferences.example.json` | Template for user preferences |
| `schema/init.sql` | SQLite schema for jobs_seen + score_cache |
| `setup.sh` | One-time setup: creates `~/.claude/job-hunt-ai/`, installs deps, inits DB |

## Slash commands (skills)

| Command | File | What it does |
|---|---|---|
| `/job-setup` | `skills/job-setup/SKILL.md` | Secrets check, Drive resume pick, **Claude reads + verifies resume**, preferences questionnaire |
| `/job-search` | `skills/job-search/SKILL.md` | Full pipeline (Layer A + WebSearch discovery + Claude Layer B scoring, company intel, salary, XLSX, tailoring, Telegram) |
| `/job-tailor <id\|URL\|JD>` | `skills/job-tailor/SKILL.md` | Claude scores + tailors resume to a single job |
| `/job-feedback` | `skills/job-feedback/SKILL.md` | Record applied/rejected/interview/offer/ghosted outcomes; updates `learning.json` |
| `/jobpilot-clear` | `skills/jobpilot-clear/SKILL.md` | Reset seen-job cache, score cache, feedback, and learned weights |

## Data directory (not in repo)

Everything personal lives in `~/.claude/job-hunt-ai/` (created by `setup.sh`):

```
~/.claude/job-hunt-ai/
├── .env                          # APIFY_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
├── options/preferences.json      # job search criteria
├── cache/jobs.sqlite             # seen-jobs + score cache + user feedback
├── cache/profile.json            # resume profile (Claude-verified, profile_verified: true)
├── cache/company_intel.json      # per-company interview intel (archetype, prep focus; TTL 45d)
├── cache/learning.json           # outcome-learned ranking weights (see Learning loop below)
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
- `effective_score` = `score * location_weight + bar_fit + learning_adj` — used **only for
  sort order**, never for gates (see the two sections below for the added terms).

**Worked example (Swiss Re Golang):** JD asks for Go, Docker, Kubernetes, CI/CD, microservices
(5 skills). Profile has Go, Docker, K8s, GitHub Actions, gRPC → 4 matched / 5 JD skills = 80.
With semantic_score=75 → score = round(0.5×75 + 0.5×80) = 78. Crosses tailoring threshold.

No `ats_scorer.py`, no `sentence-transformers`, no Jaccard fallback. Scored jobs are persisted
by `scripts/record_scored.py` (jobs_seen + score_cache) so runs are deduped and cached scores
are reused for an unchanged resume.

## Interview-bar intelligence (Layer B, /job-search Step B3b)

Pure JD-text matching can't see the *hiring bar*: Navi gates freshers on medium DSA
(GFG interview experiences), Signzy tests API/system-design depth, Swiss Re deep-dives resume
projects, Accenture screens communication + cognitive, GenAI startups want one production RAG
project (see `PLAN_INTELLIGENCE.md` Research Findings for citations).

- `cache/company_intel.json`: per-company entry with `archetype`
  (`dsa-gate-product | api-depth-startup | genai-portfolio-startup | gcc-enterprise |
  mass-recruiter | unknown`), rounds, `prep_focus`, `sources`, `fetched_at`, `ttl_days: 45`.
  Populated by ≤5 WebSearch lookups per run (top jobs only, misses cached as `unknown`).
- `profile.interview_readiness` (additive, from `/job-setup`): `dsa_level`, `leetcode_url`,
  `system_design`, `spoken_english`. Missing block = all-`unknown`; never ask during a run.
- `bar_fit ∈ [-8, +8]` from archetype × readiness (e.g. dsa-gate + weak/unknown DSA → −8…−4;
  genai-portfolio + shipped RAG project → +4…+8; mass-recruiter/unknown → 0). Applied to
  `effective_score` only. Report gets `Prep Focus` + `Gap Signals` columns.

## Learning loop (Layer B only — recursive, capped)

`/job-feedback` outcomes re-weight *ranking* over time via `cache/learning.json`
(`skill_weights` / `archetype_weights` / `source_weights`, all defaulting to 1.0):

- **Write** (job-feedback Step 3b), per outcome with value
  `v ∈ {offer +1.0, interview +0.6, applied 0, ghosted −0.3, rejected −0.6}`, for each signal
  `s` in the job's `matched_skills ∪ {archetype, source_board}` (from `score_cache`):
  `w[s] = clip(w[s] + 0.05 * v, 0.7, 1.3)`. One outcome moves a weight ≤ 0.05.
- **Read** (job-search B3b), only when `outcome_count >= 5`:
  `learning_adj = clip(10 * (mean(w[s] for relevant s) − 1.0), −10, +10)` added to
  `effective_score`. Never touches `score` or any threshold gate. `/jobpilot-clear` deletes
  `learning.json` along with the feedback rows it was learned from.
- **Layer A never learns**: no scoring or learning logic in `apify_scraper.py` / `dedupe.py` /
  `filter.py` / `scripts/scrapers/` (Layer A invariant).

## Secrets rule

All secrets are loaded through `scripts/jp_secrets.py` (keyring first, then `~/.claude/job-hunt-ai/.env`). No script should read `os.environ` for secrets directly.

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