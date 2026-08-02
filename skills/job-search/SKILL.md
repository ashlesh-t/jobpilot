---
name: job-search
description: The main JobPilot pipeline. Invoke for /job-search [optional override prompt]. Runs the phases in order — scrape, dedupe, filter (pure Python, no LLM), then discovery, relevance, scoring, company intel, salary research, report and delivery.
---

# /job-search [optional override prompt]

Run the whole JobPilot pipeline, **fully autonomously**. Never pause for confirmation. If a
step fails, log it and continue with the next one.

## How this skill relates to the phases

The pipeline is defined once, as a sequence of phases in `orchestrator/phases.py`. Each
reasoning phase has its own skill file with the exact rules for that step:

| # | Phase | Who runs it | Detail |
|---|---|---|---|
| 1 | scrape | `scripts/apify_scraper.py` | Layer A — no LLM |
| 2 | dedupe | `scripts/dedupe.py` | Layer A — no LLM |
| 3 | filter | `scripts/filter.py` | Layer A — no LLM |
| 4 | discover | you | `skills/job-phase-discover/SKILL.md` |
| 5 | relevance | you | `skills/job-phase-relevance/SKILL.md` |
| 6 | score | you | `skills/job-phase-score/SKILL.md` |
| 7 | intel | you | `skills/job-phase-intel/SKILL.md` |
| 8 | salary | you | `skills/job-phase-salary/SKILL.md` |
| 9 | persist | `scripts/record_scored.py` | Layer A — no LLM |
| 10 | report | `scripts/report_generator.py` | Layer A — no LLM |
| 11 | notify | `scripts/notify_run.py` | Layer A — no LLM |

**When JobPilot is running as a service, you never see this file** — the orchestrator invokes
each phase skill separately, which is what makes stop, resume and per-phase rerun possible.

This file is the path for a human running `/job-search` in a Claude Code session. It sets up
the run, then walks the phases in order, following each phase skill exactly. **Do not
duplicate or paraphrase the phase rules here — open the phase file and follow it.** If the two
ever disagree, the phase file wins.

## Autonomy contract — this skill MUST NOT

- Call `AskUserQuestion` at any point.
- Prompt for secrets inline. A missing secret means
  `[skip] <source> — secret missing, configure it in JobPilot → My Info`, then continue.
- Wait for user input before proceeding.

## Pre-conditions

`profile.json` exists with `profile_verified: true`, `preferences.json` exists, and secrets are
stored. If any of these is missing, log the specific item and degrade gracefully — **never
block**.

## Override prompt

Text after `/job-search` is an override, in one of two forms:

- `OVERRIDE: force RUN_MODE=<full|native>` — skip the run-mode logic below and use that mode.
- Anything else — a relevance/scoring hint, passed through to the relevance and scoring phases
  (e.g. "prioritise remote ML roles").

## Repo path resolution (read this first)

Every `scripts/…` and `config/…` path is relative to the JobPilot **repo root**. Resolve it
once and use it for every shell command and Read call:

- `CLAUDE_PLUGIN_ROOT` set (installed as a Claude Code plugin) → that is the root. Write
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/apify_scraper.py"`.
- Otherwise the root is the current working directory, and the paths work as written.

## Artifact paths

Artifacts are **run-scoped**. If `JOBPILOT_RUN_DIR` is set, every artifact lives at
`$JOBPILOT_RUN_DIR/<name>.json`; otherwise they fall back to `/tmp/jobpilot_<name>.json`. Ask
the helper rather than hardcoding either:

```bash
python3 -c "import sys; sys.path.insert(0,'scripts'); import jp_paths; print(jp_paths.artifact('scored'))"
```

Artifact names in order: `raw`, `scrape_status`, `deduped`, `filtered`, `discovered`,
`relevant`, `scored`, `notify_receipt`.

---

## Step 0 — Run mode, keywords, lessons

### 0a — Decide the run mode

If the override contains `OVERRIDE: force RUN_MODE=<mode>`, use that mode and skip the
alternation (but still write the bookkeeping).

Otherwise read `~/.claude/job-hunt-ai/cache/run_state.json` (treat a missing file as `{}`) and
decide from today's date in IST:

```
last_full_run   = run_state.get("last_full_run", "")
scheduled_mode  = run_state.get("next_scheduled_mode", "full")

if last_full_run == today OR scheduled_mode == "native":
    RUN_MODE = "native"          # free native scrapers only
    run_state["next_scheduled_mode"] = "full"
else:
    RUN_MODE = "full"            # native + Apify
    run_state["last_full_run"] = today
    run_state["next_scheduled_mode"] = "native"

write run_state back
```

Alternating keeps the paid Apify sources to roughly one run a day while the free sources run
every time.

Apify key rotation is automatic: the scraper moves `APIFY_TOKEN` → `_2` → `_3` as credit runs
out, and degrades to native-only when all slots are exhausted.

Log: **"Run mode: `<RUN_MODE>` (last full run: `<date>`). Native-only skips
LinkedIn/Glassdoor/Naukri/Cutshort/Wellfound."**

### 0b — Enrich the search keywords

From `experience_years` and `graduation`, write seniority terms into
`preferences.search_keywords_extra`:

- fresher (0 years, or graduating within a year): `"fresher entry level junior graduate new grad 0-2 years"`
- 1–2 years: `"junior mid-level 1-3 years"`
- 3+ years: leave empty.

`job_market_focus` already drives source selection inside `apify_scraper.py` — nothing to do.

### 0c — Load the lessons cache

Read `~/.claude/job-hunt-ai/cache/apify_lessons.json` (or `config/apify_lessons_seed.json` on a
first run). Keep it in context: its `source_quirks` explain each source's oddities, and you
update it at the end of the run.

## Step 1 — Profile check

Read `~/.claude/job-hunt-ai/cache/profile.json`.

- `profile_verified == true` → continue.
- Otherwise: run `python3 scripts/resume_parser.py <active resume path>`, read
  `/tmp/jobpilot_resume_raw.txt`, extract every field you can (name, skills, roles, projects,
  education, graduation date, links, experience years), write the profile, and proceed.
  **Do not ask questions** — infer best-effort and note the ambiguities in the run summary.

---

## Steps 2–4 — Layer A (pure Python, no LLM)

> **Never use `sleep N && tail`** to wait for output — the harness blocks those chains. For
> anything slower than ~10s, launch with `run_in_background: true` and await the notification,
> or poll with the Monitor tool. Then read the output file directly.

```bash
python3 scripts/apify_scraper.py            # add --native-only when RUN_MODE=native
python3 scripts/dedupe.py
python3 scripts/filter.py
```

`apify_scraper.py` runs the free native scrapers first, then the Apify sources. Read
`scrape_status` afterwards: for any source reporting an error, one `WebSearch` for the
corrected actor input schema is worth it — record what you learn in `apify_lessons.json`.

Print: **"Layer A complete: X raw → Y after dedupe → Z after filter"**, and note how many jobs
have no description.

---

## Steps 5–8 — Reasoning phases

Follow each phase skill exactly, in order. Each reads its input artifact and writes its output
artifact; do not skip ahead or merge phases.

1. `skills/job-phase-discover/SKILL.md` — `filtered` → `discovered`
2. `skills/job-phase-relevance/SKILL.md` — `filtered` + `discovered` → `relevant`
3. `skills/job-phase-score/SKILL.md` — `relevant` → `scored`
4. `skills/job-phase-intel/SKILL.md` — `scored` → `scored`
5. `skills/job-phase-salary/SKILL.md` — `scored` → `scored`

Apply any non-OVERRIDE hint from the override prompt in the relevance and scoring phases.

---

## Steps 9–11 — Persist, report, deliver

```bash
python3 scripts/record_scored.py "$(python3 -c "import sys;sys.path.insert(0,'scripts');import jp_paths;print(jp_paths.artifact('scored'))")"
python3 scripts/report_generator.py
python3 scripts/notify_run.py --run-mode "<RUN_MODE>"
```

`record_scored.py` writes the jobs into the database, which is what makes cross-run dedupe,
the dashboard, and the feedback loop work. `report_generator.py` writes the styled XLSX.
`notify_run.py` builds the digest and delivers it, the report, and any tailored resumes to
every configured channel — and writes a receipt artifact recording what actually went through.

Always attempt all three, even if an earlier phase failed: partial results still beat nothing.

---

## Resume tailoring

Tailoring is **no longer part of a run**. It is a per-job action — in the web UI, the "Tailor
resume" button on any job; from a chat session, `/job-tailor <job_id>`. Tailoring every top
match on every run produced resumes nobody sent; doing it on demand, for the job the user has
actually decided to apply to, produces better ones.

---

## Update the lessons cache

Write `~/.claude/job-hunt-ai/cache/apify_lessons.json` with what this run learned: per-source
`last_success`, `zero_result_runs`, any `field_overrides` you had to apply, and `last_updated`.

## Failure handling

Track failures as you go — `{step, reason}` — and never abort the whole run for one of them.
The persist, report and notify steps are always attempted.

Finish with a short summary: the run mode, the counts at each stage, the top matches, where the
report was written, what was delivered, and any steps that failed with the reason.
