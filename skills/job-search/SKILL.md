---
name: job-search
description: The main JobPilot pipeline. Invoke for /job-search [optional override prompt]. Runs Layer A (scrape, dedupe, location-filter — pure Python, no LLM) then Layer B where Claude directly filters, scores, researches salary, writes the report CSV, tailors resumes, and sends the Telegram digest.
---

# /job-search [optional override prompt]

Run the full JobPilot pipeline. Designed to run fully autonomously — do not pause for
confirmation. If a script fails, log the error and continue with the next step.

---

## Step 0 — Search keyword enrichment

Read `~/.claude/job-hunt-ai/options/preferences.json` and `~/.claude/job-hunt-ai/cache/profile.json`.
Based on `experience_years` and `graduation`, infer seniority search terms and write them as
a plain string into `preferences.json` field `search_keywords_extra`:

- `experience_years == 0` or fresh graduate (graduation ≤ current year + 1): write
  `"fresher entry level junior graduate new grad 0-2 years"`
- `experience_years` 1–2: write `"junior mid-level 1-3 years"`
- `experience_years` 3+: leave empty or omit fresher terms.

---

## Step 1 — Profile verification

Read `~/.claude/job-hunt-ai/cache/profile.json`.

If `profile_verified` is `false` or the file does not exist:
1. Run `python3 scripts/resume_parser.py ~/.claude/job-hunt-ai/resumes/base.pdf`
2. Read `/tmp/jobpilot_resume_raw.txt`
3. Follow the same profile verification steps as `/job-setup` Step F — extract all fields,
   ask clarifying questions, write complete `profile.json` with `profile_verified: true`.
4. Continue once verification is complete.

If `profile_verified` is `true`, continue directly.

---

## Step 0b — Load lessons cache

Read `~/.claude/job-hunt-ai/cache/apify_lessons.json` (or `config/apify_lessons_seed.json`
if the cache doesn't exist yet). Keep this in context — you will update it at the end of
the run and use the `source_quirks` section to guide how you interpret each source's jobs.

---

## Layer A — Scraping

### Step A1: Job scraping (Apify MCP preferred, Python SDK fallback)

**If the Apify MCP is connected** (check by attempting to list available MCP tools — look for
`run_actor` in the tool list):

Read `config/actors.json` and preferences. Use `confirmed_schema` from the lessons cache
to build the correct input for each actor. For `openclawai/job-board-scraper`, the lessons
cache specifies `searchTerms` (array) not `keywords` (string).

Call each actor via MCP, collect results, merge, then run free sources:
```bash
python3 scripts/apify_scraper.py --free-only
```
Merge MCP results with `/tmp/jobpilot_raw.json` and write back.

**If Apify MCP is NOT connected:**
```bash
python3 scripts/apify_scraper.py
```
The scraper loads `apify_lessons.json` automatically and applies the correct field overrides.

### Step A2 — Diagnose scraper failures

After Step A1, read `/tmp/jobpilot_scrape_status.json`.

For any source with `"status": "failed"` or `"count": 0`:

1. Run WebSearch: `apify "<actor_id>" returns 0 results input schema 2025`
2. Also search: `apify "<actor_id>" correct input fields example`
3. If you find an updated input schema or explanation:
   - Update `~/.claude/job-hunt-ai/cache/apify_lessons.json`:
     - Add `field_overrides` if field names differ from what we use
     - Add `value_transforms` if types differ (e.g. `"split_array"` for string→array)
     - Write `notes` and `zero_result_runs` entry with today's date and diagnosis
   - Log: `⚠️ <actor_id> failed — updated lessons cache with diagnosis`
4. If no useful info found: log the failure and continue. Do NOT abort the pipeline.

For sources that succeeded: update `last_success` to today's date in the lessons cache.

### Steps A3–A4 (always run):

```bash
python3 scripts/dedupe.py
python3 scripts/filter.py
```

Print: **"Layer A complete: X raw → Y after dedup → Z after location filter"**

Also note: `<N> jobs have no JD (LinkedIn/other)` if any `has_jd == false` jobs exist.

---

## Layer B — Claude does everything

### Step B1: Smart relevance filter

Read all jobs from `/tmp/jobpilot_filtered.json`. Read `preferences.json`.

**Experience gate (hard drop):**
For each job, scan the full `jd_full` for explicit experience requirements:
patterns like "X+ years", "minimum X years", "X-Y years of experience", "requires X years".
Extract `required_years` (integer). If `required_years > profile.experience_years + 2`:
- Mark job as `experience_gate_drop: true`
- Set `score = 0`, `effective_score = 0`
- `why = "Hard drop: role requires <N>yr experience, profile has <M>yr"`
- Keep in data (include in CSV at bottom), but skip salary research, skip tailoring.

**Domain relevance filter:**
Eliminate jobs that are clearly off-domain:
- Wrong domain (sales, HR, finance, legal when user wants SWE/Backend/ML)
- Contract/freelance-only with no mention of full-time (if user prefers full-time)
- Complete gibberish or empty title

Apply any **override prompt** the user passed at this stage.

Keep all ambiguous jobs — do not over-filter.

Print: **"Relevance filter: Z → N jobs for scoring (M hard-dropped for experience)"**

### Step B2: ATS scoring

For each non-hard-dropped job, score using the full `jd_full` and `profile.json`.

**No-JD handling:**
If `has_jd == false` (LinkedIn and similar where JD text is absent):
- `semantic_score = 30` (neutral baseline — no text to judge)
- `keyword_score` = compute normally against role title only (not full JD)
- Append `"⚠️ No JD available"` to `why`
- Do NOT tailor resume for this job (flag `skip_tailoring: true`)

**Standard scoring:**
- `matched_skills`: skills from `profile.skills` present in JD (case-insensitive)
- `missing_keywords`: top 8 technical terms in JD not in `profile.skills`
- `keyword_score` (0–100): `len(matched_skills) / len(profile.skills) * 100`
- `semantic_score` (0–100): holistic fit judgment — tech stack, seniority, project relevance
- `score` (0–100): `round(0.5 * semantic_score + 0.5 * keyword_score, 1)`
- `why`: one sentence explaining the score
- `jd_summary`: 3–5 bullet points on role responsibilities
- `location_weight`: from the job's `location_weight` field (set by filter.py)
- `effective_score`: `score * location_weight`
- `required_years`: integer extracted from JD, or null if not stated

Sort all jobs by `effective_score` descending. Hard-dropped jobs go to the bottom (effective_score = 0).

**Feedback signal (if user_feedback table has data):**
```bash
sqlite3 ~/.claude/job-hunt-ai/cache/jobs.sqlite "
  SELECT uf.status, js.company, js.role
  FROM user_feedback uf
  JOIN jobs_seen js ON uf.job_id = js.job_id
  ORDER BY uf.feedback_date DESC LIMIT 20;
"
```
If you see a pattern (e.g. company type consistently leads to rejection despite high scores,
or lower-scoring companies gave interviews), note this in the run summary. Do NOT auto-adjust
scores based on feedback — just surface the pattern.

### Step B3: Salary research (top matches only)

For jobs with `score >= 60` AND `experience_gate_drop != true` AND `has_jd != false`,
run up to 3 targeted WebSearch queries per job:

1. `"<company> India salary software engineer 2025 site:glassdoor.co.in OR ambitionbox.com"`
2. `"<role title> fresher salary <primary_city> LPA 2025"`
3. `"<company> CTC package freshers campus placement 2024 OR 2025"`

Extract LPA range from results. Rules:
- If a company-specific result is found: use it and note the source
- If only market-average data is found: use it but label as `"market avg — no <company>-specific data"`
- If nothing found for all 3 queries: set `salary_range = "No data found"` and
  `demand_estimate = "Insufficient public data for this company in India"`
- **Never invent a range.** If uncertain, say so explicitly.

### Step B4: Write the report CSV

Use the Write tool to create:
`~/.claude/job-hunt-ai/reports/YYYY-MM-DD-<slot>.csv`
where `<slot>` is `morning` (before 12 IST), `afternoon` (12–17 IST), or `evening` (17+ IST).

**Write ALL scored jobs to the CSV** — no top-N cap. Hidden gems at rank 40 should be visible.
Hard-dropped jobs are included at the bottom with `experience_gate_drop = true`.

CSV columns (in this order):
```
job_id, company, role, location, source_board, posted_date,
score, keyword_score, semantic_score, location_weight, effective_score,
matched_skills, missing_keywords, why_score,
has_jd, experience_gate_drop, required_years,
salary_range, demand_estimate,
application_url, apply_url_type, jd_summary, jd_full
```

`apply_url_type` classification:
- `greenhouse` if URL contains `greenhouse.io`
- `lever` if URL contains `lever.co`
- `ashby` if URL contains `ashbyhq.com`
- `workday` if URL contains `workday` or `myworkdayjobs`
- `google_form` if URL contains `docs.google.com/forms` or `forms.gle` — add `⚠️` prefix
- `linkedin_easy` if URL contains `linkedin.com`
- `company_direct` otherwise

Sort rows by `effective_score` descending.

Print: **"Report written: N jobs total (M hard-dropped, K no-JD) → <path>"**

### Step B5: Resume tailoring

Compute effective tailoring threshold:
- If `profile.experience_years == 0`: `effective_threshold = min(score_threshold, 60)`
- Else: `effective_threshold = score_threshold` (default 75 from preferences)

For the top 5 jobs where:
- `score >= effective_threshold`
- `experience_gate_drop != true`
- `skip_tailoring != true` (i.e. has_jd is not false)

**If `~/.claude/job-hunt-ai/resumes/base.tex` exists:**
1. Read `base.tex`
2. Edit to emphasise `matched_skills` — weave into skills section, objective line, experience bullets
3. Write to `/tmp/<company>-<job_id>.tex`
4. Compile:
   ```bash
   tectonic /tmp/<company>-<job_id>.tex --outdir ~/.claude/job-hunt-ai/resumes/tailored/
   ```
   If tectonic fails: save `.tex` to `resumes/tailored/` directly.

**If no `base.tex`:**
```bash
python3 scripts/resume_tailor.py <job_id> --matched-skills <comma-separated-matched-skills>
```

Self-cap at 5 resumes per run. Print reason if fewer than 5 qualify (e.g. "Only 2 jobs met
the 60-point threshold — tailored 2 resumes").

### Step B6: Build and send Telegram digest

Build digest text (plain text, no markdown). Show top 5 jobs:

```
JobPilot — YYYY-MM-DD, <slot>
━━━━━━━━━━━━━━━━━━━━
Top matches:

1. <role> @ <company> (Score: <score>)
   <salary_range> | <location>
   <application_url>

2. ...  (up to 5 entries)

━━━━━━━━━━━━━━━━━━━━
Total: X raw → Y filtered → Z scored → W tailored
<N> jobs had no JD (LinkedIn) | <M> hard-dropped (exp. mismatch)
<warnings for any failed scrapers>
CSV + resumes → Drive
━━━━━━━━━━━━━━━━━━━━
```

Flag Google Form URLs with ⚠️. Flag no-JD jobs with `[no JD]` suffix.

If any Apify actors failed, add: `⚠️ <actor> failed after 3 retries — see apify_lessons.json`

Send:
```bash
python3 scripts/telegram_notify.py --digest "<digest_text>" --csv "<report_csv_path>"
```

### Step B7: Drive upload

```bash
python3 scripts/drive_upload.py
```
Read `/tmp/jobpilot_drive_manifest.json`. Upload each file via Drive MCP.
If Drive MCP unavailable, log and continue.

---

## Step C — Update lessons cache

After the full run completes, update `~/.claude/job-hunt-ai/cache/apify_lessons.json`:

1. For each Apify actor that returned > 0 items: update its `last_success` to today's date.
2. For each actor that failed: add entry to `zero_result_runs` if diagnosis was found.
3. If a new `field_overrides` or `value_transforms` was discovered during A2 diagnosis: write it.
4. Update `"last_updated"` to today's date.

Write the updated lessons JSON using the Write tool.

---

## Final summary

Print:
**"Done. N jobs scored (M hard-dropped, K no-JD). Top match: <company> <role> (score: <score>).
W resumes tailored. Report sent to Telegram + Drive."**

---

## Failure handling

Wrap each step so a single failure is logged and the pipeline continues. Always attempt
B4 (CSV), B6 (Telegram), and B7 (Drive) even if earlier steps partially failed.
