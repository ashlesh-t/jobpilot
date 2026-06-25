---
name: job-search
description: The main JobPilot pipeline. Invoke for /job-search [optional override prompt]. Runs Layer A (scrape, dedupe, filter — pure Python, no LLM) then Layer B (ATS scoring, salary research, report, resume tailoring, Telegram + Drive push) over the survivors.
---

# /job-search [optional override prompt]

Run the full JobPilot pipeline. Designed to run fully autonomously inside a scheduled task —
do not pause for confirmation. If a script fails, log the error and continue with the next step.

## Step 0 — Search keyword enrichment (Claude, before Layer A)

Read `~/.claude/job-hunt-ai/options/preferences.json` and `~/.claude/job-hunt-ai/cache/profile.json`.
Based on `experience_years`, `graduation`, and `role_types`, infer appropriate search enrichment
terms. Write them as a plain string into `preferences.json` field `search_keywords_extra`.

Examples:
- `experience_years=0` or fresh graduate (graduation ≤ current year + 1): write
  `"fresher entry level junior graduate new grad 0-2 years"`
- `experience_years=2–3`: write `"junior mid-level 1-3 years"`
- `experience_years=5+`: leave empty or omit fresher terms entirely.

This field is read by `apify_scraper.py` and appended to the Apify keyword query. Never
hardcode seniority terms in Python — Claude infers them here.

## Layer A — pure Python via bash (NO LLM)

Run each step with `python3` and read the printed counts. These scripts must never call the LLM.

1. `python3 scripts/apify_scraper.py` -> writes `/tmp/jobpilot_raw.json`
2. `python3 scripts/dedupe.py` -> writes `/tmp/jobpilot_deduped.json`
3. `python3 scripts/filter.py` -> writes `/tmp/jobpilot_filtered.json`
4. Print: **"Layer A complete: X raw -> Y after dedup -> Z after filter"**

## Layer B — LLM reasoning on the Z survivors

5. For each job in `/tmp/jobpilot_filtered.json`:
   - `python3 scripts/ats_scorer.py <job_id>` -> score JSON.
   - If `score >= 60`: `python3 scripts/salary_research.py <company> <role> <location>`.
6. Apply any **override prompt** the user passed (e.g. "focus on remote backend roles",
   "rank by salary") to adjust ranking or focus.
7. `python3 scripts/report_generator.py` -> writes the dated CSV into `reports/`.
8. For the top 5 matches with `score >= 75`: `python3 scripts/resume_tailor.py <job_id>`
   (the script self-caps at 5 per run).
9. `python3 scripts/telegram_notify.py` — sends the CSV, tailored PDFs, and a formatted digest.
10. `python3 scripts/drive_upload.py` — writes `/tmp/jobpilot_drive_manifest.json`.
11. Read the manifest. Use the Google Drive MCP `search_files` tool to find or confirm the
    `"JobPilot Reports"` folder exists (create it via `create_file` with folder MIME type if not).
    For each file in the manifest, upload it via the Drive MCP `create_file` tool into that folder.
    Log: `[drive] Uploaded <name> -> <link>` for each success.
    If Drive MCP is unavailable or any upload fails, log the error and continue — do not abort.
12. Print: **"Done. Report sent to Telegram + Drive. Top match: <company> <score>"**

## Scoring detail
For the semantic ATS step this skill relies on the internal `resume-validate` skill /
`scripts/ats_scorer.py`, which scores a JD against `profile.json` (60% semantic + 40% keyword).

## Failure handling
Wrap each step so a single failure (e.g. Apify quota, Telegram timeout) is logged and the
pipeline continues. Always attempt the report + notification even if tailoring failed.
