# Changelog

## v3.0.0 — 2026-08-05

### Release title: "Everyone Gets Their Own" (major)

JobPilot moves from a single-user tool to a shared instance with real accounts. Every
job search, resume, API key, and pipeline run now belongs to whoever's logged in — plus
everything else that landed since 2.1.0: direct ATS scrapers, an Adzuna source, a rebuilt
Telegram scraper, US market support, and draft-only referral messages.

### Multi-user accounts

The headline change, and a breaking one: `jobpilot setup` no longer configures a single
person's job search. It bootstraps the database and creates (or, on an existing install,
lets you claim) the first account; everyone else signs up in the browser.

- **Everything is per-account**: preferences, resume, profile, scored jobs, applications,
  tailored resumes, contacts, referrals, chat history, schedule, and cost tracking. Job
  listings themselves stay shared and deduped once across every account — re-scraping
  the same posting per person would be wasteful — but the *score* against your resume is
  always yours alone.
- **API keys and tokens are per-account too**, encrypted in the database — not the OS
  keyring, which is machine-wide and doesn't map to individual logins on a shared
  instance. Two accounts can hold completely different Apify, Telegram, or Anthropic
  credentials.
- **Sessions**: server-side, HttpOnly cookie — no token sits in browser storage where a
  script could read it.
- **Pipeline runs are isolated per account**: each person gets their own run lock, so two
  accounts can run `/job-search` at the same time without blocking each other, with
  separate artifact, resume, and report directories.
- **Upgrading an existing single-user install loses nothing.** The migration backfills a
  locked account holding every pre-existing job, run, and preference; the next
  `jobpilot setup` (run in a terminal) prompts you to claim it with a real username and
  password.
- **The AI backend choice stays instance-wide** — one agent CLI per install, shared by
  every account — since a Claude Code subscription login is inherently machine-level.
  Only the metered API-key backends (`claude_api`, `gemini`) are genuinely per-account.

### The web setup wizard grew up

`jobpilot setup`'s old terminal-only steps for picking a backend, adding Apify/Adzuna,
and connecting Telegram/Discord are now in the browser, where they belong on a
multi-account instance — same guided copy, same QR codes, same live verification:

- **AI backend** — detects what's installed, lets you choose, and walks you through
  adding a key for the metered backends. Installing the Claude Code CLI itself still
  happens via `jobpilot setup` in a terminal, not a web button.
- **Job sources** — Apify and Adzuna, with the same step-by-step instructions and QR
  codes the terminal wizard had, each verified live before it's saved.
- **Delivery** — Telegram gets the auto-link flow: scan a QR, hit Start in the app, and
  your chat ID is captured automatically, no copy-pasting a numeric ID out of an API
  response. Discord's webhook is validated and saved the same way as before.

### Fixed

- **The health check was lying.** It reported Apify, Adzuna, Telegram and Discord as
  configured for every account — even a brand-new one — because several checks still
  read the old machine-wide credential store instead of the logged-in account's own. A
  fresh account now correctly shows nothing as set until that account sets it.
- The Keys & Tokens page still said credentials were "stored in your operating system
  keyring" — true before this release, not after. Updated the copy everywhere it appeared.

### Direct ATS scrapers, Adzuna, and a rebuilt Telegram source

- **Native scrapers for Greenhouse, Lever, Ashby, and Workable** hit target companies'
  ATS APIs directly, skipping the slower LLM-driven career-page discovery for the
  companies where a direct API is available.
- **Adzuna** joins as an optional free native source, credentials verified live.
- **The Telegram channel scraper was rebuilt** onto public `t.me/s/<channel>` preview
  pages — no more Telethon session login, just add a channel and it's validated live.
- **US job-market focus**, alongside the existing India and global modes.
- **Four more free job boards**: SimplifyJobs, Himalayas, WorkingNomads, and Jobspresso.

### Draft-only referrals

Import an HR/recruiter contacts spreadsheet, and JobPilot drafts a referral-request
message matched to a job and contact by company name. It only ever drafts — nothing in
this codebase sends a referral message anywhere; you copy, edit, and send it yourself.

### Visual polish

A richer look across the whole app — gradient accents, deeper shadows, spring-eased
hover and press animations, frosted glass on sticky chrome — built on the same
accessible color system and dark mode as before, not a replacement of it.

---

## v2.1.0 — 2026-08-02

### Release title: "Rough Edges" (minor)

Everything in this release came from running 2.0 end to end and writing down what got in
the way: setup failing on the first step, a resume library you couldn't find, a PDF
compiler you had to install yourself, and no way to move to a new version.

### Setup actually completes

- **Fixed the first-run crash.** `jobpilot setup` failed on step 1 with
  `no such table: settings` on every fresh install — step 1 reads settings, but the
  storage step that creates the schema is step 2. The wizard now brings the database up to
  head before any step runs, and falls back to SQLite if a saved Postgres DSN is
  unreachable.
- **Telegram tells you what a bot token looks like.** BotFather's reply is easy to
  misread; setup and the credential vault now say to paste the whole `123456789:AAH…`
  string, colon included.
- **Setup offers to install the PDF compiler.** If tectonic is missing, step 6 offers to
  drop the official static binary into `~/.local/bin` — no root, no package manager, no
  LaTeX distribution. It warns you if the directory isn't on your `PATH` instead of
  claiming success.

### Resumes are where you'd look for them

- **A Resumes tab in My Info.** The resume library was only reachable from a collapsed
  disclosure on Job Hunt.
- **Always visible on Job Hunt.** Which resume a run will use is not something to hide.
- **One radio group picks the active resume,** spanning every folder, so a folder holding
  several resumes no longer makes you guess which one JobPilot reads.
- **Folders get a real dialog** instead of a browser prompt, with the same name validation
  the server applies, plus folder rename and per-resume labels.

### Resume reading

- The server now uses the Layer A extractor, which has a pdfplumber fallback for PDFs
  PyPDF2 returns nothing for, and strips LaTeX markup out of `.tex` sources.
- The extraction prompt asks for every field in the profile skeleton — including
  `interview_readiness`, which feeds the interview-bar adjustment in scoring and was
  simply never being filled.
- Resume text is no longer truncated at 20k characters, which used to silently drop the
  education and projects tail of longer CVs.
- A heuristic (no-agent) read is now reported as a warning rather than a success, because
  a regex-guessed profile quietly weakens every later score.

### `jobpilot upgrade`

- Updates a pipx or pip install from PyPI, then always applies pending migrations,
  re-exports `preferences.json` and `profile.json` so the Layer B skills see new keys, and
  re-checks your tools.
- `--check` reports what a new release would bring and changes nothing.
- On a copy installed from a source checkout it prints the rebuild command instead of
  pulling a published release over your work.

### A page that explains itself

- **New `/whoami`** — what JobPilot is, who it's for, an animated pipeline diagram, and
  your own numbers: score distribution, sources, application funnel, jobs per run, spend.
- **In-app changelog**, parsed from this file, with the version you're on badged.
- **Raise an issue** with a one-click diagnostics copy (version, OS, database, tools).

### Fixed

- The "No PDF compiler installed" card now tells you how to fix it instead of just naming
  tectonic.
- `/health` reports the running version; `CHANGELOG.md` ships inside the wheel.

---

## v2.0.0 — 2026-08-02

### Release title: "Everything Around the Pipeline" (major)

A rewrite of everything around the pipeline. The scoring logic and the free scrapers are
unchanged; how you set JobPilot up, run it, and see the results is entirely new.

### The run is now steps you can control

The pipeline was one opaque `claude -p "/job-search"` call — no cancel, no resume, no way
to redo part of it. It is now eleven phases the orchestrator drives:

- **Stop** reaches the child process instead of orphaning it. Everything already done is kept.
- **Resume** restarts at the first unfinished phase — it never re-scrapes work that succeeded.
- **Re-run one phase** redoes that phase and invalidates only what depends on it.
- Every event is persisted, so a finished run's timeline survives a service restart.
- Artifacts are run-scoped under `runs/<run_id>/`; two runs can no longer clobber each
  other's `/tmp` files.
- Scrape, dedupe and filter now run as plain Python with no LLM in the loop — cheaper, and
  instantly cancellable.

### A real web app

React + Vite, shipped inside the wheel, works offline, light and dark:

- **Home** — KPIs, charts, and the full job table: search, sort by match or package, filter
  by source, score and salary, CSV/XLSX export of exactly what's on screen. Closed and
  expired postings are hidden by default.
- **Job Hunt** — start a run and watch each step, with logs, artifacts and per-phase re-run.
- **Applications** — board and table, dated status history from applied through to offer.
- **Tailored Resumes** — PDF preview, Overleaf source, ATS score before and after.
- **Scheduler** — add, edit and delete run times (v1 had no delete), install the background
  service, configure catch-up.
- **My Info** — profile, preferences, a masked credential vault with per-credential tests,
  and the full health table.
- **Assistant** — ask about your own jobs, scores and runs.

### Setup without Claude Desktop

- `pipx install jobpilot-ai && jobpilot setup` — a guided terminal wizard.
- **Google Drive is gone.** Resumes are uploaded in the web app, organised in folders, with
  one active resume.
- Telegram setup is a QR code and a `/start` — the chat ID is captured automatically instead
  of being fished out of a raw JSON response.
- The AI backend is detected and its login **actually verified**; v1 reported a logged-out
  CLI as ready and then failed at run time.
- New backends: Anthropic API, Gemini/Antigravity, and a generic CLI adapter.

### Storage

- PostgreSQL in a Docker container JobPilot manages, with a SQLite fallback when Docker
  isn't available. One SQLAlchemy code path; the same test suite passes on both.
- Alembic migrations applied at every start.
- `jobpilot migrate` imports v1 state — preferences, profile, job history, score cache,
  feedback, run history — idempotently, without touching your v1 files.

### Cost

- A per-phase cost ledger. Subscription runs report real tokens with no dollar amount,
  because there is no per-token charge — rather than implying you were billed.
- Tailoring and assistant answers are billed too.

### Scheduling

- Slots are database rows with their own timezone, mode and enabled flag.
- A run missed while the machine was off happens **once** on return, within a configurable
  grace window — not once per missed slot.
- No network at fire time triggers a retry ladder rather than a recorded failure.
- Auto-start service for systemd, launchd and Task Scheduler, installed from the UI.

### Resume tailoring

- Now a per-job action rather than something every run did to five jobs nobody sent.
- Ships an ATS-safe LaTeX template; generated documents are validated against it (no tables,
  images, multi-column layouts or exotic packages) before compiling.
- Output: `resumes/tailored/<JOBID>-<COMPANY>/FirstName_LastName_Resume.{pdf,tex}` plus
  `meta.json` with the ATS score before and after.

### Fixed

- Run artifacts resolved to the newest file on disk regardless of which run asked, so
  historical runs showed another run's results.
- A finished run's event stream 404'd after a service restart.
- The scheduler's job store was in-memory, so slots vanished on restart.
- The setup wizard wrote to `.env` while every reader preferred the keyring, so a saved
  secret could be silently shadowed.
- Concurrent runs shared one tailoring budget counter in `/tmp`.

### Breaking

- `/job-setup` is superseded by `jobpilot setup` and the in-app wizard. Google Drive is no
  longer used.
- `scripts/drive_upload.py` removed (deprecated since v1.6).
- `/schedule` moved to `/api/schedule` and takes slot objects rather than time strings.
- `/api/profile` is database-backed and returns `{profile, exists, verified}`.


---

## v1.7.0 — 2026-08-01

### Release title: "Company Intel & Onboarding Polish" (minor)

Four features from `PLAN_INTELLIGENCE.md` land together: cross-run memory that actually
persists, interview-bar-aware ranking, a recursive learning loop off `/job-feedback`
outcomes, and a smoother `/job-setup` + `jobpilot` CLI onboarding flow.

### Added
- **Company intel + interview-bar ranking.** `/job-search` researches each top job's
  interview bar into `cache/company_intel.json` (≤5 WebSearch/run, 45d TTL) and applies
  `bar_fit ∈ [-8, +8]` to `effective_score` based on company archetype × the new
  `profile.interview_readiness` block (collected once in `/job-setup`). Report and
  digest gain Prep Focus / Gap Signals columns.
- **Recursive learning loop.** `/job-feedback` outcomes now update
  `cache/learning.json` skill/archetype/source weights (`w = clip(w + 0.05*v, 0.7, 1.3)`),
  applied to ranking only after ≥5 outcomes, capped ±10, never touching `score` or
  threshold gates.
- **WebSearch as a third job source** (≤3 searches, ≤10 jobs/run) alongside native
  scrapers and Apify.
- **Browser-based profile review** in `/job-setup` — after Claude drafts `profile.json`,
  a review page (`server/ui/profile_review.html`) lets you see and edit every section
  before `profile_verified` is set. Reuses the existing FastAPI/UI stack; spins up a
  throwaway server instance if `jobpilot serve` isn't already running.
- **`jobpilot start`**: bootstraps setup if not configured, prompts for schedule slots,
  launches `serve`, opens the browser. `--reconfigure` forces the wizard.
- **`jobpilot view <item>`**: prints a single doctor check's status by name/substring,
  with `--live`.

### Fixed
- **Cross-run memory was silently broken.** Only tailored jobs were ever recorded into
  `jobs_seen`/`score_cache` (with blank company/role), so seen-job dedupe was a no-op
  and `/job-feedback` listed empty rows. New `scripts/record_scored.py` persists every
  scored job.
- **Feedback resurrection.** Any `jobs_seen` row now counts as "seen" during dedupe/filter
  — status is lifecycle metadata, not membership, so a `rejected` job no longer reappears
  next run.
- `filter.py`: en-dash experience ranges ("2 – 4 yrs") now parse the lower bound; bare
  "lakh" requires compensation context so "10 lakh users" isn't misread as salary.
- **Apify retry/backoff restored** on the live path (lost in a prior cleanup) — transient
  5xx/408/transport errors now retry with 2s→4s backoff, max 3 attempts; auth/credit and
  HTTP 400 don't retry. Empty 200 responses are accepted by default (opt into one retry
  via `actors.json` `retry_empty_runs`) instead of the old 3x-retry-on-empty that tripled
  spend on runs returning nothing.
- Wired in `apify-client` SDK (declared as a dependency but never used) so long scrapes
  aren't capped by the 300s server-side ceiling of the raw `run-sync-get-dataset-items`
  call; raw HTTP remains the fallback.

### Housekeeping
- Removed `PLAN.md` / `PLAN_INTELLIGENCE_PROMPT.md` (superseded planning docs).
  `PLAN_INTELLIGENCE.md` stays — it's cited by `CLAUDE.md` for interview-bar research.
- `server/scheduler.py`: `schedule_slots_ist` entries accept `{"name","time"}` in
  addition to plain `"HH:MM"`, so multiple slots can share a clock time. Backward
  compatible.

---

## v1.6.2 — 2026-07-09

### Release title: "One-Command Install" (patch)

`pipx install "jobpilot-ai[server]"` required remembering the `[server]` extra to get the
local web UI. Since `jobpilot-ai` is the only PyPI package (no lean core-only use case for
end users), fold the extra into the base install.

### Changed
- **`[server]` extra removed from the PyPI package.** `fastapi`, `uvicorn`, `sse-starlette`,
  `apscheduler`, and `claude-agent-sdk` moved from `[project.optional-dependencies].server`
  into base `dependencies` in `pyproject.toml`. `pipx install jobpilot-ai` (no extra) now
  installs the pipeline and the optional local web UI together. `tray` and `dev` extras are
  unchanged. Homebrew/AUR/Scoop wrappers and docs updated to drop `[server]` from every
  install command.
- Source installs (`requirements.txt` / `requirements-server.txt`, used by `setup.sh` /
  `scripts/jobpilot_setup.py`) are unchanged — that split still lets contributors skip the
  heavier web-UI deps if they only need the chat-driven pipeline.

---

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
