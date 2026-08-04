# JobPilot — Claude Code Project Guide

Automated job-hunting pipeline: scrape multiple job sources → Claude scores + filters → tailor resume → notify via Telegram.

## Architecture

Two-layer design:

- **Layer A (pure Python, no LLM):** `apify_scraper.py` → `dedupe.py` → `filter.py`, plus
  `record_scored.py`, `report_generator.py` and `notify_run.py`. Must never call the LLM.
  Writes run-scoped artifacts (see Artifact paths below).
- **Layer B (the agent):** all the judgement — relevance, scoring, company intelligence,
  salary research, resume tailoring. Split into per-phase skills (see Per-phase skills).

**v2 architecture (`core/` + `orchestrator/` + `server/` + `ui/`):** The pipeline is no
longer one opaque LLM call. It is a sequence of phases the orchestrator drives, which is
what makes stop / resume / per-phase rerun possible.

- **`core/`** — the domain layer. `db.py` (PostgreSQL in Docker, SQLite fallback, one
  SQLAlchemy code path), `models.py`, `migrations/` (Alembic, applied at every start),
  `repo/*` (every query lives here — none in server/ or orchestrator/), `secrets.py`
  (keyring-first; secrets never enter the database), `pricing.py`, `backends.py`
  (agent detection + `install_claude_code` / `install_tectonic`), `tailoring.py`,
  `export.py`, `migrate_v1.py`, `changelog.py` (CHANGELOG.md → structured releases, shared
  by `jobpilot upgrade` and the About page), `version.py`.
- **`orchestrator/`** — `phases.py` is the registry: 11 phases, each declaring who runs it
  (`python` = a Layer A script, `llm` = a per-phase skill), its inputs and its output
  artifact. `artifacts.py` gives every run its own directory. `runner.py` executes the
  sequence, holds the child-process handle so a stop actually reaches it, retries transient
  failures, and records cost per phase.
- **`server/`** — FastAPI. `app.py` plus routers (`routes_jobs`, `routes_settings`,
  `routes_schedule`, `routes_resumes`, `routes_tailor`, `routes_chat`, `routes_about`),
  `scheduler.py` (catch-up + network retry), `run_manager.py` (a thin adapter over the
  orchestrator).
- **`ui/`** — React + Vite, built to `ui/dist` and shipped inside the wheel.

- **`engines/` — RunEngine provider adapters.** `claude_code` (Pro/Max subscription, no
  per-token cost), `claude_api` (Agent SDK, metered), `gemini` (experimental), and
  `generic_cli` (any headless agent, by command template). Every adapter reports token
  `Usage` and implements `stop()`, which is what makes cancellation reach the child.
- **`server/` — the service.** `app.py` (FastAPI + SSE), `run_manager.py` (a thin adapter
  over the orchestrator), `scheduler.py`, `telegram_auth.py`, `doctor.py` (health
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
| `scripts/apify_scraper.py` | Layer A: hybrid orchestrator (native + Apify), writes the `raw` artifact |
| `scripts/scrapers/_common.py` | Shared native-scraper helpers (canonical schema, geo filter, http) |
| `scripts/scrapers/{internshala,remoteok,weworkremotely,remotive,arbeitnow,jobicy}.py` | Native scrapers (no Apify, no LLM) |
| `scripts/dedupe.py` | Layer A: removes duplicates → the `deduped` artifact |
| `scripts/filter.py` | Layer A: hard filters (location+city-alias, exp cap, CTC, seen-jobs) → the `filtered` artifact |
| `scripts/resume_tailor.py` | Layer B: edits LaTeX/DOCX resume to match JD, compiles PDF |
| `scripts/record_scored.py` | Layer-B-invoked, pure Python: persists scored jobs into `jobs_seen` + `score_cache` (cross-run memory) |
| `scripts/feedback.py` | Records `/job-feedback` outcomes into `user_feedback` |
| `scripts/report_generator.py` | Layer A: styled **XLSX** (top 20) into `~/.claude/job-hunt-ai/reports/` from the `scored` artifact |
| `scripts/telegram_notify.py` | Layer B: sends digest + report (xlsx/csv) + tailored resumes to Telegram |
| `scripts/jp_secrets.py` | Secret loader/saver (keyring → `.env`). All scripts use this; never read env vars directly. |
| `scripts/setup_wizard.py` | Interactive wizard called by `setup.sh` |
| `config/actors.json` | Apify actor IDs (native sources listed under `_native_sources`) |
| `config/preferences.example.json` | Template for user preferences |
| `scripts/jp_paths.py` | Run-scoped artifact paths shared by every Layer A script |
| `scripts/notify_run.py` | Layer A: builds the digest and delivers it; writes a receipt |
| `templates/resume/ats_safe.tex` | The ATS-safe LaTeX template tailoring fills in |
| `schema/init.sql` | **v1 only** — the v2 schema is `core/models.py` + Alembic |
| `jobpilot/tui/` | The `jobpilot setup` wizard. `wizard.py` migrates the DB before step 1 — step 1 reads settings, step 2 creates the schema |
| `jobpilot/cli.py` | Every subcommand, including `upgrade` (PyPI only; a source install gets the rebuild command, never a published release over the top) |
| `setup.sh` | **v1 only** — superseded by `jobpilot setup` |

**Version**: `jobpilot/__init__.py` is the source of truth; `pyproject.toml` mirrors it and
`tests/test_about_api.py` asserts they agree. `core/version.py` resolves it from anywhere.

## Slash commands (skills)

| Command | File | What it does |
|---|---|---|
| `/job-setup` | `skills/job-setup/SKILL.md` | **Superseded** by `jobpilot setup` + the in-app wizard. Kept for chat-driven users; the Drive steps no longer apply. |
| `/job-search` | `skills/job-search/SKILL.md` | Full pipeline (Layer A + WebSearch discovery + Claude Layer B scoring, company intel, salary, XLSX, tailoring, Telegram) |
| `/job-tailor <id\|URL\|JD>` | `skills/job-tailor/SKILL.md` | Claude scores + tailors resume to a single job |
| `/job-feedback` | `skills/job-feedback/SKILL.md` | Record applied/rejected/interview/offer/ghosted outcomes; updates `learning.json` |
| `/jobpilot-clear` | `skills/jobpilot-clear/SKILL.md` | Reset seen-job cache, score cache, feedback, and learned weights |

## Data directory (not in repo)

Everything personal lives in `~/.claude/job-hunt-ai/` (created by `jobpilot setup`).
Credentials are **not** there — they go to the OS keyring via `core/secrets.py`:

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
- `profile_verified: false` → extracted but not confirmed by a human. Scoring still uses
  it; the UI says so, because a wrong profile silently degrades every score.
- A new `resume_hash` (different resume uploaded) resets `profile_verified` to `false`
  automatically — see `core/repo/profiles.py`.

The database row is authoritative; `cache/profile.json` is written on every save because
the Layer B skills read that file. Same for `options/preferences.json`.

## Layer A invariant

Scripts `apify_scraper.py`, `dedupe.py`, `filter.py`, and everything in `scripts/scrapers/`
must never invoke the LLM. They read config, call REST/HTML/RSS APIs, and read/write the
cache and artifact JSON files. Violating this makes the pipeline expensive.

## Artifact paths

Artifacts are **run-scoped**. `scripts/jp_paths.py` resolves every name:
`$JOBPILOT_RUN_DIR/<name>.json` inside an orchestrated run, `/tmp/jobpilot_<name>.json`
otherwise. Never hardcode either — two concurrent runs sharing `/tmp` was a real v1 bug.
Names in order: `raw`, `scrape_status`, `deduped`, `filtered`, `discovered`, `relevant`,
`scored`, `notify_receipt`.

## Per-phase skills

The five reasoning phases each own a skill file, carved verbatim out of the old monolithic
`/job-search`: `skills/job-phase-{discover,relevance,score,intel,salary}/SKILL.md`.
`skills/job-search/SKILL.md` is now a thin index that walks them in order for chat users.
**When behaviour changes, edit the phase file** — the index defers to it.

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