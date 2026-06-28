---
name: job-search
description: The main JobPilot pipeline. Invoke for /job-search [optional override prompt]. Runs Layer A (native + Apify scrape, dedupe, filter — pure Python, no LLM) then Layer B (ATS scoring, salary research, styled XLSX report, resume tailoring, Telegram + Drive push) over the survivors.
---

# /job-search [optional override prompt]

Run the full JobPilot pipeline. Designed to run fully autonomously — do not pause for
confirmation. If a script fails, log the error and continue with the next step.

**Autonomy contract — this skill MUST NOT:**
- Call `AskUserQuestion` at any point during the run.
- Prompt for secrets inline (APIFY_TOKEN, Telegram tokens). If a secret is missing,
  log `[skip] <source> — secret missing, run /job-setup to configure` and continue.
- Wait for user input before proceeding to the next step.

**Pre-conditions (assumed complete before /job-search runs):**
- `/job-setup` has been completed: `profile.json` exists with `profile_verified: true`,
  `preferences.json` exists, secrets are stored, Drive MCP UUID is in `settings.local.json`.
- If any pre-condition is violated, log the specific missing item and degrade gracefully
  (skip that source/step), **never block**.

---

## Step 0 — Tiered scheduling + Search keyword enrichment

### 0a — Decide run mode

Read `~/.claude/job-hunt-ai/cache/run_state.json` (create as `{}` if missing).

Determine today's date in IST (Asia/Kolkata).

```
last_full_run   = run_state.get("last_full_run", "")
scheduled_mode  = run_state.get("next_scheduled_mode", "full")
exhausted_slots = run_state.get("exhausted_slots", [])

if last_full_run == today OR scheduled_mode == "native":
    RUN_MODE = "native"          # native scrapers only (free)
    run_state["next_scheduled_mode"] = "full"
else:
    RUN_MODE = "full"            # native + Apify
    run_state["last_full_run"] = today
    run_state["next_scheduled_mode"] = "native"

write run_state back to run_state.json
```

- `RUN_MODE = "native"` → run `python3 scripts/apify_scraper.py --native-only`
- `RUN_MODE = "full"`   → run `python3 scripts/apify_scraper.py` (with Apify)

**Apify key rotation (applies during full runs only):**
The scraper auto-rotates `APIFY_TOKEN` → `APIFY_TOKEN_2` → `APIFY_TOKEN_3` when it detects
credit exhaustion. If all slots are exhausted, it sends a Telegram alert and degrades to
native-only automatically. `run_state.json` tracks which slots are exhausted.

Log: **"Run mode: <RUN_MODE> (last full run: <last_full_run>)"**

### 0b — Search keyword enrichment

Read `~/.claude/job-hunt-ai/options/preferences.json` and `~/.claude/job-hunt-ai/cache/profile.json`.
Based on `experience_years` and `graduation`, infer seniority search terms and write them as
a plain string into `preferences.json` field `search_keywords_extra`:

- `experience_years == 0` or fresh graduate (graduation ≤ current year + 1): write
  `"fresher entry level junior graduate new grad 0-2 years"`
- `experience_years` 1–2: write `"junior mid-level 1-3 years"`
- `experience_years` 3+: leave empty or omit fresher terms.

`job_market_focus` (`india` | `global` | `both`) in preferences drives source selection
automatically inside `apify_scraper.py` — no action needed here. Never hardcode seniority terms
in Python; Claude infers them in this step.

## Step 1 — Profile verification

Read `~/.claude/job-hunt-ai/cache/profile.json`.

If `profile_verified` is `true`: continue directly — no action needed.

If `profile_verified` is `false` or the file does not exist:
1. Run `python3 scripts/resume_parser.py ~/.claude/job-hunt-ai/resumes/base.pdf`
2. Read `/tmp/jobpilot_resume_raw.txt`
3. Extract all fields autonomously (name, skills, roles, projects, education, graduation_date,
   github_url, portfolio_url, experience_years). **Do NOT ask clarifying questions** — infer
   best-effort from the text, mark `profile_verified: true`, and continue. Note any ambiguities
   in the run summary for the user to fix via `/job-setup`.
4. Write `profile.json` and proceed immediately.
These scripts must never call the LLM. Run each and read the printed counts.

1. `python3 scripts/apify_scraper.py` -> writes `/tmp/jobpilot_raw.json`
   - Runs the **native scrapers first** (free: Internshala, RemoteOK, WeWorkRemotely,
     Remotive, Arbeitnow, Jobicy) and then the **Apify layer** (LinkedIn, Glassdoor,
     Indeed-IN, Naukri, Cutshort, Wellfound, ATS) only if a valid `APIFY_TOKEN` exists.
   - **If Apify credit is exhausted or the token is invalid**, the script prints a one-time
     inline prompt for a fresh `APIFY_TOKEN`. In an interactive run, paste a new token to
     continue with paid sources; otherwise the pipeline proceeds with native results only.
     Note in the final digest if paid sources were skipped.
2. `python3 scripts/dedupe.py` -> writes `/tmp/jobpilot_deduped.json`
3. `python3 scripts/filter.py` -> writes `/tmp/jobpilot_filtered.json`
   (location + city-alias match, experience cap, CTC/company, keyword pre-filter;
   adds `exp_req_years` and `location_weight` to each job)
4. Print: **"Layer A complete: X raw -> Y after dedup -> Z after filter"**

If `profile_verified` is `true`, continue directly.

---

## Step 0b — Load lessons cache

Read `~/.claude/job-hunt-ai/cache/apify_lessons.json` (or `config/apify_lessons_seed.json`
if the cache doesn't exist yet). Keep this in context — you will update it at the end of
the run and use the `source_quirks` section to guide how you interpret each source's jobs.

---

## Layer A — Scraping

> **IMPORTANT — never use `sleep N && tail` or `sleep N && <any-command>` to wait for script output.**
> These chains are blocked by the harness. For scripts that run longer than ~10s:
> - Launch with `run_in_background: true` in the Bash tool, then await the completion notification.
> - For polling until a file appears: use the Monitor tool with an `until` loop (e.g. `until [ -f /tmp/jobpilot_raw.json ]; do sleep 2; done`).
> - After the script completes, read output files directly — do NOT tail them.

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

## Step A0.5 — Company Career Page Crawl (optional, Layer B)

Read `config/target_companies.json`. If `"enabled": true`:

1. Filter companies by `job_market_focus`:
   - `india` → companies with `"focus": "india"` or `"both"`
   - `global` → companies with `"focus": "global"` or `"both"`
   - `both` → all companies
2. For each company, use WebFetch MCP to fetch `careers_url`.
3. From the HTML, extract job listings visible without JavaScript (title, location, apply URL).
   Skip companies where the page is SPA-only (blank HTML body) — log and continue.
4. Keep only roles matching `role_types` from preferences (case-insensitive title check).
5. For each matching role, build a canonical job dict:
   - `source_board`: `"direct-<company_name_slug>"` (e.g. `"direct-google"`)
   - `company`, `role`, `location`, `application_url` from parsed HTML
   - `jd_full`: empty or any visible snippet; `has_jd: false` if no description found
   - `last_date`: empty (career pages rarely show deadlines)
   - `job_id`: compute same SHA1 hash as `make_job_id(company, role, location, source_board)`
6. Skip any job whose `job_id` is already in the seen-jobs set (load from SQLite inline).
7. Cap at **5 results per company** to avoid flooding.
8. Append qualifying jobs to `/tmp/jobpilot_filtered.json` (read → merge → write).
9. Log: `[careers] <Company>: N matching roles added` (or `skipped — SPA-only / 0 matches`).

These jobs enter Layer B scoring on equal footing with the scraper results.

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

For jobs with **`score >= 60`** (pure fit, NOT effective_score) AND `experience_gate_drop != true` AND `has_jd != false`,
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
### B0 — Build apply-URL preservation map

Before any scoring or enrichment, build a URL map from `/tmp/jobpilot_filtered.json` so that
apply links are never lost when Claude reconstructs scored records:

```python
url_map = {job["job_id"]: job.get("application_url", "") for job in filtered_jobs}
```

Keep `url_map` in memory for the rest of Layer B. After computing each scored record, always
re-attach the URL:
```python
scored_job["application_url"] = scored_job.get("application_url") or url_map.get(scored_job["job_id"], "")
```

This guarantees that a URL captured by the scraper is never silently dropped when Claude
writes the scored JSON, even if the record was rebuilt from scratch during scoring.

### B1 — JD enrichment for empty descriptions (cap 25)

For jobs where `jd_full` is empty or < 120 chars AND `source_board` is `linkedin` (or any
paid board that returned no description), enrich the JD before scoring:
1. `WebFetch` the `application_url` — LinkedIn/company pages often render the JD without login.
2. If that yields nothing useful, `WebSearch` `"<company> <role> careers"` and `WebFetch` the
   company careers/ATS page.
Write the recovered text back into the job's `jd_full` and set `jd_source: "fetched"`.
Cap at 25 enrichments; skip a page if it takes more than ~8s. **Do NOT** scrape LinkedIn with a
logged-in session — it risks banning the account used to apply.

### B2 — ATS scoring (write the scored JSON)

For each surviving job, read the **full** `jd_full` and `profile.json`, then compute:

**Step 1 — extract JD hard skills:**
- `must_have_skills` (≤6): concrete tech skills the JD explicitly requires.
- `nice_to_have` (≤4): skills mentioned as preferred/bonus.
- `jd_hard_skills` = union of must_have_skills + nice_to_have (the JD's skill footprint).
- `degree_required`: extracted from the JD.

**Step 2 — score:**
- `matched_skills`: profile skills present in `jd_hard_skills` (case-insensitive). Capped to
  skills that exist in `profile.skills` — do not invent matches.
- `missing_skills`: important hard skills in `jd_hard_skills` not in the profile (top ~8).
- `keyword_score` = `min(100, round(len(matched_skills) / max(len(jd_hard_skills), 1) * 100))`.
  Score against **what the JD asks for**, not the full profile skills list. This means a
  Golang-only JD where the candidate matches Go+Docker+K8s+CI/CD scores ~80, not ~20.
- `semantic_score` (0–100): holistic fit — stack alignment, seniority (fresher OK for
  entry/junior), projects, product vs pure-service company.
- `score` (pure fit, 0–100, drives all threshold gates):
  - jobs **with** a real JD: `round(0.5*semantic + 0.5*keyword, 1)`, `score_confidence: "high"`.
  - jobs **still without** a JD after B1: `round(0.9*semantic + 0.1*title_keyword, 1)`,
    `score_confidence: "low"`.
- `why`: one sentence justifying the score.
- `jd_summary`: 3–5 short bullet strings.
- carry over `location_weight`, `exp_req_years`, `source_board`, `posted_date`, `company`,
  `role`, `location`, `job_id`.
- `application_url`: always re-attach from `url_map` (built in B0) — **never omit or leave blank
  when the map has a URL for this job_id**.
- `effective_score` = `score * location_weight` — used **only for sort order**, never for gates.

**Location override (B2 Layer B — Claude resolves what filter.py couldn't):**
For any job where `location` is empty, `"Not specified"`, `"India"`, or otherwise ambiguous,
read `~/.claude/job-hunt-ai/cache/locations.json` and resolve:
- Match the job's `source_board` or JD text for city hints (e.g. "office in Bangalore")
- If the JD implies remote: set `location_weight` to the remote weight from locations.json
- If unresolvable: leave `location_weight` at 0.75 (neutral) and note in `why`
Log: `location '<raw>' re-resolved to '<canonical>' via '<matched>' → weight <w>`

Rank by `effective_score` (descending). Apply any **override prompt** the user passed here.

### B3 — Salary research (top 20, India-aware)

For the top ~20 by `score` (pure fit) with **`score >= 55`** — gate on `score`, NOT
`effective_score`. A strong match with a 2nd-choice location (score=72, effective=61) still
deserves salary research.

1. **AmbitionBox actor** (India salaries) via Apify MCP, if Apify is available:
   `call-actor "thirdwatch/ambitionbox-scraper"` with
   `{ "companies": ["<company>"], "roles": ["<role-slug>"], "includeCompanyReviews": false }`.
   Extract the LPA range for the matching role.
2. **Fallback** `WebSearch`: `"<company> <role> salary India LPA" site:ambitionbox.com OR glassdoor.co.in`.
3. `your_demand = round_to_0.5( max(target_ctc_min_lpa, market_75th_pct * score/100) )` — never
   below `target_ctc_min_lpa`.
4. Set `market_salary` (e.g. "8–14 LPA"), `your_demand` (e.g. "12 LPA"),
   `salary_source` ("AmbitionBox" / "Glassdoor" / "web-estimated" / "not-found").
   Leave blank rather than invent a number.

Write the enriched list (all fields above) to **`/tmp/jobpilot_scored.json`**.

### B4 — Styled XLSX report (top 20)

```bash
python3 scripts/report_generator.py --input /tmp/jobpilot_scored.json \
  --output ~/.claude/job-hunt-ai/reports/YYYY-MM-DD-<slot>.xlsx
```
`<slot>` = morning (<12 IST) / afternoon (12–17) / evening (17+). The script colours rows by
score (≥75 green, 60–74 yellow), freezes the header, hyperlinks the apply link, and caps at 20.
All scored jobs remain in `/tmp/jobpilot_scored.json`; only the report is capped.

### B5 — Resume tailoring (top matches)

Read `score_threshold` from preferences (default **65**). For the top 5 jobs with
**`score >= score_threshold`** — gate on `score` (pure fit), NOT `effective_score`.
A job with score=72 in a 2nd-choice city (effective=61) should still get a tailored resume.
- If `~/.claude/job-hunt-ai/resumes/base.tex` exists: edit it to weave in `matched_skills`
  (never invent experience/dates/employers), write `/tmp/<company>-<job_id>.tex`, and compile
  with `tectonic ... --outdir ~/.claude/job-hunt-ai/resumes/tailored/`.
- Else: `python3 scripts/resume_tailor.py <job_id> --matched-skills <csv>` (DOCX).
Self-cap at 5 per run.

### B6 — Telegram digest

When building the digest, resolve each job's apply link via `url_map` (built in B0) first,
then fall back to the `application_url` field in the scored record. This ensures URLs captured
by the scraper but omitted during scoring reconstruction are still included in the digest.

Build a plain-text digest (top 3 jobs, flag ⚠️ Google-Form apply links, note if Apify paid
sources were skipped), then:
```bash
python3 scripts/telegram_notify.py --digest "<text>" --xlsx "<report_path>"
```
(If `telegram_notify.py` only accepts `--csv`, pass the xlsx path to it as the attachment.)

### B7 — Drive upload

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

## Failure handling

Wrap every step in try/except logic (or equivalent). A single step failure must log the error and
continue — **never abort the whole pipeline**. Always attempt B4 (report), B6 (Telegram), and
B7 (Drive) even if earlier steps partially failed.

Track failures in a `_failed_steps` list throughout the run. Each entry:
`{"step": "B3-salary-<company>", "reason": "<brief error message>"}`.

### Drive upload (B7)
Read `/tmp/jobpilot_drive_manifest.json`. Use the Drive MCP `search_files` to find the
`"JobPilot Reports"` folder (create via `create_file` with folder MIME type if missing), then
upload each manifest file via `create_file`. Log `[drive] Uploaded <name> → <link>`.
If Drive MCP is unavailable or any upload fails, log and continue — do not abort.

---

## Final summary

Print:
```
Done. N jobs scored (M hard-dropped, K no-JD). Top match: <company> <role> (score: <X>).
W resumes tailored. Report → Telegram + Drive.
```

If `_failed_steps` is non-empty, append a skipped/failed section:
```
⚠️ Skipped / degraded steps:
  - <step>: <reason>
  - <step>: <reason>
Run /job-setup to fix configuration issues, or check apify_lessons.json for actor failures.
```

This summary also appears in the Telegram digest (B6) as a trailing warning block, so the
user sees failures even without reading the terminal output.
