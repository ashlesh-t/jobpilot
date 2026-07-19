---
name: job-search
description: The main JobPilot pipeline. Invoke for /job-search [optional override prompt]. Runs Layer A (native + Apify scrape, dedupe, filter — pure Python, no LLM) then Layer B (relevance + experience gate, ATS scoring, salary research, styled XLSX report, resume tailoring, Telegram/Discord notify) over the survivors.
---

# /job-search [optional override prompt]

Run the full JobPilot pipeline. Designed to run **fully autonomously** — do not pause for
confirmation. If a script fails, log the error and continue with the next step.

This skill is the single source of truth for the pipeline. It is executed both directly in a
Claude Code session and headless by the local service (`server/`) under whichever engine the
user chose — so it must never require interaction.

**Autonomy contract — this skill MUST NOT:**
- Call `AskUserQuestion` at any point during the run.
- Prompt for secrets inline (APIFY_TOKEN, Telegram tokens). If a secret is missing,
  log `[skip] <source> — secret missing, run /job-setup to configure` and continue.
- Wait for user input before proceeding to the next step.

**Pre-conditions (assumed complete before /job-search runs):**
- `/job-setup` has been completed: `profile.json` exists with `profile_verified: true`,
  `preferences.json` exists, secrets are stored.
- If any pre-condition is violated, log the specific missing item and degrade gracefully
  (skip that source/step), **never block**.

**Override prompt:** any text passed after `/job-search` is an override. Two forms:
- `OVERRIDE: force RUN_MODE=<full|native>` — skip the run-state logic in Step 0a and use that
  mode (this is how the local service's "Full / Native" buttons work).
- Any other text — a relevance/scoring hint applied in Step B1/B3 (e.g. "prioritise remote ML").

**Repo path resolution (read this first).** Every `scripts/…` and `config/…` path in this
skill is relative to the JobPilot **repo root**. Resolve that root once, at the start, and use
it for every shell command *and* Read-tool call:
- If the `CLAUDE_PLUGIN_ROOT` environment variable is set (JobPilot installed as a Claude Code
  plugin), the repo root is `${CLAUDE_PLUGIN_ROOT}`. In shell commands write
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/apify_scraper.py"`; for Read-tool calls use that
  absolute path.
- Otherwise (git clone / headless service run) the repo root is the current working directory —
  `scripts/…` and `config/…` work as written.
Data paths under `~/.claude/job-hunt-ai/…` and `/tmp/…` are absolute and never need the prefix.

---

## Step 0 — Run mode, keyword enrichment, lessons cache

### 0a — Decide run mode

If the override prompt contains `OVERRIDE: force RUN_MODE=<mode>`, set `RUN_MODE` to that value
and skip the alternation logic below (but still write `run_state.json` bookkeeping).

Otherwise read `~/.claude/job-hunt-ai/cache/run_state.json` (create as `{}` if missing) and
decide based on today's date in IST (Asia/Kolkata):

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

**Apify key rotation (full runs only):** the scraper auto-rotates `APIFY_TOKEN` →
`APIFY_TOKEN_2` → `APIFY_TOKEN_3` on credit exhaustion; if all slots are exhausted it sends a
Telegram alert and degrades to native-only. `run_state.json` tracks exhausted slots.

Log: **"Run mode: <RUN_MODE> (last full run: <last_full_run>). Native-only runs skip
LinkedIn/Glassdoor/Naukri/Cutshort/Wellfound."**

### 0b — Search keyword enrichment

Read `preferences.json` and `profile.json`. Based on `experience_years` and `graduation`, infer
seniority search terms and write them as a plain string into `preferences.json`
`search_keywords_extra`:

- `experience_years == 0` or fresh graduate (graduation ≤ current year + 1):
  `"fresher entry level junior graduate new grad 0-2 years"`
- `experience_years` 1–2: `"junior mid-level 1-3 years"`
- `experience_years` 3+: leave empty.

`job_market_focus` (`india` | `global` | `both`) drives source selection inside
`apify_scraper.py` automatically — no action needed here.

### 0c — Load the lessons cache

Read `~/.claude/job-hunt-ai/cache/apify_lessons.json` (or `config/apify_lessons_seed.json` if
the cache doesn't exist yet). Keep it in context — you update it at the end of the run and use
its `source_quirks` to interpret each source's jobs.

---

## Step 1 — Profile verification

Read `~/.claude/job-hunt-ai/cache/profile.json`.

- If `profile_verified == true`: continue directly, no action needed.
- If `profile_verified` is `false` or the file does not exist:
  1. Run `python3 scripts/resume_parser.py ~/.claude/job-hunt-ai/resumes/base.pdf` (dumb text
     extractor — never calls the LLM).
  2. Read `/tmp/jobpilot_resume_raw.txt`.
  3. Extract all fields autonomously (name, skills, roles, projects, education,
     graduation_date, github_url, portfolio_url, experience_years). **Do NOT ask questions** —
     infer best-effort, mark `profile_verified: true`, and note any ambiguities in the run
     summary for the user to fix later via `/job-setup`.
  4. Write `profile.json` and proceed immediately.

---

## Layer A — Scraping, dedupe, filter (pure Python, no LLM)

> **Never use `sleep N && tail` or `sleep N && <cmd>` to wait for output — the harness blocks
> these chains.** For scripts that run longer than ~10s:
> - Launch with `run_in_background: true`, then await the completion notification.
> - To poll for a file, use the Monitor tool with an `until` loop.
> - After completion, read the output files directly — do NOT tail them.

### A1 — Scrape (Apify MCP preferred, Python SDK fallback)

**If the Apify MCP is connected** (a `run_actor` tool is available): read `config/actors.json`
and the lessons cache, build each actor's input from its `confirmed_schema` (e.g.
`openclawai/job-board-scraper` needs `searchTerms` array, not a `keywords` string), call each
actor via MCP, then run the free sources and merge:
```bash
python3 scripts/apify_scraper.py --free-only
```
Merge MCP results into `/tmp/jobpilot_raw.json`.

**If the Apify MCP is NOT connected**, run the hybrid scraper (respecting RUN_MODE from 0a):
```bash
python3 scripts/apify_scraper.py            # full: native + Apify
python3 scripts/apify_scraper.py --native-only   # native mode
```
It runs native scrapers first (Internshala, RemoteOK, WeWorkRemotely, Remotive, Arbeitnow,
Jobicy, Hasjob, YC, HN, Telegram channels) then the Apify layer if a valid token exists, and
applies the lessons-cache field overrides automatically. Writes `/tmp/jobpilot_raw.json`.

### A2 — Diagnose scraper failures

Read `/tmp/jobpilot_scrape_status.json`. For any source with `"status": "failed"` or
`"count": 0`:
1. `WebSearch` `apify "<actor_id>" returns 0 results input schema` and
   `apify "<actor_id>" correct input fields example`.
2. If you find a corrected schema, update `apify_lessons.json` (`field_overrides`,
   `value_transforms` such as `"split_array"`, plus a dated `zero_result_runs` note). Log
   `⚠️ <actor_id> failed — updated lessons cache`.
3. If nothing useful is found, log and continue — never abort.
For sources that succeeded, set their `last_success` to today.

### A3 — Dedupe + filter

```bash
python3 scripts/dedupe.py    # -> /tmp/jobpilot_deduped.json
python3 scripts/filter.py    # -> /tmp/jobpilot_filtered.json
```
`filter.py` applies location + city-alias match, deadline, experience cap, and CTC/company
rules, and adds `exp_req_years` + `location_weight` to each job.

Print: **"Layer A complete: X raw → Y after dedup → Z after filter"**, and note
`<N> jobs have no JD` if any `has_jd == false`.

### A4 — Company career-page crawl (optional)

Read `config/target_companies.json`. If `"enabled": true`:
1. Filter companies by `job_market_focus` (`india` → focus india/both; `global` →
   global/both; `both` → all).
2. `WebFetch` each `careers_url`; extract roles visible without JavaScript (title, location,
   apply URL). Skip SPA-only pages (blank body) — log and continue.
3. Keep roles matching `role_types` (case-insensitive title check).
4. Build a canonical job dict per role: `source_board = "direct-<company_slug>"`,
   `has_jd: false` if no description, `job_id` = same SHA1 as
   `make_job_id(company, role, location, source_board)`.
5. Skip jobs whose `job_id` is already in the seen set (query SQLite inline). Cap **5 per
   company**. Append to `/tmp/jobpilot_filtered.json` (read → merge → write).
6. Log `[careers] <Company>: N roles added` (or `skipped — SPA-only / 0 matches`).

These jobs enter Layer B on equal footing with scraper results.

### A5 — WebSearch job discovery (Layer B, free)

Claude's own WebSearch is the third sourcing channel (native scrapers → Apify → WebSearch).
Run **at most 3 searches** built from `preferences.json`:

```
"<role_types[0]> fresher <current year> <location_priority[0]>" (site:boards.greenhouse.io OR site:jobs.lever.co OR site:jobs.ashbyhq.com)
"<preferred_stack[0]> <role_types[0]> hiring <location_priority[0]>"
"<role_types[1]> new grad remote india apply"
```

For each credible posting found (**cap 10 total**): build the canonical job dict —
`job_id` = same SHA1 as `make_job_id(company, role, location, "websearch")`,
`source_board: "websearch"`, `application_url` = the posting page, `has_jd` per available
text. Skip any `job_id` already in the seen set (SQLite) or already present in
`/tmp/jobpilot_filtered.json`. Append survivors to `/tmp/jobpilot_filtered.json`
(read → merge → write), exactly like A4. Log `[websearch] N jobs added`. If searches fail,
log and continue — never block.

---

## Layer B — Claude scores, researches, tailors, notifies

### B0 — Build the apply-URL preservation map

Before any scoring, build a URL map from `/tmp/jobpilot_filtered.json` so apply links are
never lost when scored records are rebuilt:
```python
url_map = {job["job_id"]: job.get("application_url", "") for job in filtered_jobs}
```
After computing each scored record, always re-attach:
```python
scored_job["application_url"] = scored_job.get("application_url") or url_map.get(scored_job["job_id"], "")
```

### B1 — Relevance filter + experience gate

Read all jobs from `/tmp/jobpilot_filtered.json` and `preferences.json`.

**Experience gate (hard drop):** scan `jd_full` for explicit requirements ("X+ years",
"minimum X years", "X-Y years of experience", "requires X years"). Extract `required_years`.
If `required_years > profile.experience_years + 2`:
- set `experience_gate_drop: true`, `score = 0`, `effective_score = 0`,
  `why = "Hard drop: role requires <N>yr, profile has <M>yr"`.
- keep in data (bottom of report), but skip salary research and tailoring.

**Domain relevance:** drop jobs clearly off-domain (sales/HR/finance/legal when the user wants
SWE/Backend/ML), contract/freelance-only when the user prefers full-time, or gibberish/empty
titles. Keep all ambiguous jobs — do not over-filter.

Apply any non-OVERRIDE **override prompt** hint here.

Print: **"Relevance filter: Z → N jobs for scoring (M hard-dropped for experience)"**.

### B2 — JD enrichment for empty descriptions (cap 25)

For jobs where `jd_full` is empty or < 120 chars AND `source_board` is `linkedin` (or any paid
board that returned no description):
1. `WebFetch` the `application_url` — LinkedIn/company pages often render the JD without login.
2. If that yields nothing, `WebSearch` `"<company> <role> careers"` and `WebFetch` the company
   careers/ATS page.
Write recovered text back into `jd_full`, set `jd_source: "fetched"`. Cap 25; skip a page that
takes >~8s. **Do NOT** scrape LinkedIn with a logged-in session — it risks banning the account.

### B3 — ATS scoring (write the scored JSON)

**Score-cache reuse:** before scoring each job, check
`SELECT score_json FROM score_cache WHERE job_id=? AND resume_hash=?` (current
`preferences.resume_hash`). On a hit, reuse the cached `score`/`matched_skills`/
`missing_skills` (log `cache-hit <job_id>`) and skip re-derivation — scores stay consistent
across runs. (A resume change clears the cache automatically in `dedupe.py`.)

For each remaining job, read the **full** `jd_full` and `profile.json`:

**Extract JD hard skills:**
- `must_have_skills` (≤6): concrete tech skills the JD explicitly requires.
- `nice_to_have` (≤4): preferred/bonus skills.
- `jd_hard_skills` = union of the two (the JD's skill footprint).
- `degree_required`: from the JD.

**Score:**
- `matched_skills`: profile skills present in `jd_hard_skills` (case-insensitive). Never invent
  matches — only skills that exist in `profile.skills`.
- `missing_skills`: important `jd_hard_skills` not in the profile (top ~8).
- `keyword_score` = `min(100, round(len(matched_skills) / max(len(jd_hard_skills), 1) * 100))`.
  Score against **what the JD asks for**, not the full profile list — a Golang-only JD where
  the candidate matches Go+Docker+K8s+CI/CD scores ~80, not ~20.
- `semantic_score` (0–100): holistic fit — stack alignment, seniority (fresher OK for
  entry/junior), project relevance, product vs pure-service company.
- `score` (pure fit, 0–100 — drives every threshold gate):
  - jobs **with** a real JD: `round(0.5*semantic + 0.5*keyword, 1)`, `score_confidence: "high"`.
  - jobs **still without** a JD after B2: `round(0.9*semantic + 0.1*title_keyword, 1)`,
    `score_confidence: "low"`, append `"⚠️ No JD available"` to `why`, set
    `skip_tailoring: true`.
- `why`: one sentence. `jd_summary`: 3–5 short bullet strings.
- carry over `location_weight`, `exp_req_years`, `source_board`, `posted_date`, `company`,
  `role`, `location`, `job_id`; re-attach `application_url` from `url_map` (B0).
- `effective_score` = `score * location_weight` — used **only for sort order**, never for a
  gate. **Never multiply `score` by `location_weight`.**

**Location override:** for any job whose `location` is empty/`"Not specified"`/`"India"`/
ambiguous, read `~/.claude/job-hunt-ai/cache/locations.json` and resolve from `source_board`
or JD city hints; if the JD implies remote, use the remote weight; if unresolvable, leave
`location_weight` at 0.75 and note it in `why`. Log
`location '<raw>' re-resolved to '<canonical>' → weight <w>`.

**Feedback pattern report:** if `user_feedback` has rows, run
`SELECT uf.status, js.company, js.role FROM user_feedback uf JOIN jobs_seen js ON uf.job_id = js.job_id ORDER BY uf.feedback_date DESC LIMIT 20;`
and surface any pattern in the run summary (e.g. "high-scoring GCC jobs keep rejecting").
The *numeric* learning adjustment happens in B3b below — never here, and never on `score`.

Rank by `effective_score` (desc), hard-dropped jobs at the bottom. Apply any non-OVERRIDE
override hint. Write the full enriched list to **`/tmp/jobpilot_scored.json`**.

### B3b — Company intel, bar-aware ranking, learning adjustment

All three adjust **ranking only** (`effective_score`) — `score` and every threshold gate
(tailoring, salary) are never touched by this step.

**1. Company intel** (`~/.claude/job-hunt-ai/cache/company_intel.json`, read it first):
for the top ~8 jobs with `score >= 55`, look up the lowercased company name. For at most
**5 cache-misses per run**, run one WebSearch each:
`"<company> <role-family> interview experience rounds site:geeksforgeeks.org OR site:ambitionbox.com OR site:glassdoor.co.in"`
(retry once without the site filter). Write what you learn as a cache entry:

```json
{
  "navi": {
    "archetype": "dsa-gate-product",
    "rounds": "OT + 2 DSA rounds + HM round",
    "tests": ["DSA medium (DP, binary search)", "OOP", "DBMS"],
    "dsa_intensity": "high",
    "fresher_friendly": true,
    "prep_focus": "Grind medium DP/graph problems; be fluent in complexity analysis",
    "sources": ["<url>"],
    "fetched_at": "YYYY-MM-DD",
    "ttl_days": 45
  }
}
```

Archetype enum: `dsa-gate-product | api-depth-startup | genai-portfolio-startup |
gcc-enterprise | mass-recruiter | unknown`. If nothing credible is found, cache
`{"archetype": "unknown", ...}` too (so the miss isn't re-searched). Re-fetch entries older
than `ttl_days`. Attach `archetype`, `prep_focus` to each covered job.

**2. bar_fit** (`∈ [-8, +8]`, from archetype × `profile.interview_readiness`; treat a missing
`interview_readiness` block as all-`unknown`, never ask):
- `dsa-gate-product` and `dsa_level` in (none, basic, unknown) → −8…−4
- `genai-portfolio-startup` and profile has a shipped RAG/LLM project → +4…+8
- `gcc-enterprise` with strong resume projects → +2…+5
- `mass-recruiter` or `unknown` archetype → 0

**3. learning_adj** (`~/.claude/job-hunt-ai/cache/learning.json`; skip entirely if the file
is missing or `outcome_count < 5`):

```
relevant     = matched_skills ∪ {archetype, source_board}   # only keys present in the file
learning_adj = clip(10 * (mean(w[s] for s in relevant) - 1.0), -10, +10)   # 0 if relevant is empty
```

Then for every job: `effective_score = score * location_weight + bar_fit + learning_adj`.
Add `gap_signals` (≤3 short strings) to each top-20 job — what the company's bar demands
that the profile can't show (e.g. `"No DSA signal — this company gates on medium DP"`).
Append `(bar N)` / `(learning N)` to `why` when |bar_fit| ≥ 4 or |learning_adj| ≥ 2.
Re-rank, rewrite `/tmp/jobpilot_scored.json`.

### B3c — Persist scored jobs (cross-run memory)

```bash
python3 scripts/record_scored.py /tmp/jobpilot_scored.json
```

Upserts every scored job into `jobs_seen` (company/role/location/score — this is what makes
cross-run dedupe and `/job-feedback` work) and `score_cache` (score + matched_skills +
archetype, keyed by resume hash — fuel for the learning loop). Pure Python, no LLM.

### B4 — Salary research (top ~20, India-aware)

For the top ~20 by `score` with **`score >= 55`** AND `experience_gate_drop != true` — gate on
`score`, not `effective_score` (a score=72 job in a 2nd-choice city still deserves research):
1. **AmbitionBox actor** via Apify MCP if available:
   `call-actor "thirdwatch/ambitionbox-scraper"` with
   `{ "companies": ["<company>"], "roles": ["<role-slug>"], "includeCompanyReviews": false }`.
2. **Fallback** `WebSearch`:
   `"<company> <role> salary India LPA" site:ambitionbox.com OR glassdoor.co.in`.
3. `your_demand = round_to_0.5( max(target_ctc_min_lpa, market_75th_pct * score/100) )` — never
   below `target_ctc_min_lpa`.
4. Set `market_salary` (e.g. "8–14 LPA"), `your_demand` (e.g. "12 LPA"), `salary_source`
   (`AmbitionBox` / `Glassdoor` / `web-estimated` / `not-found`). **Never invent a number** —
   leave blank if uncertain. Write results back into `/tmp/jobpilot_scored.json`.

### B5 — Styled XLSX report (top 20)

```bash
python3 scripts/report_generator.py --input /tmp/jobpilot_scored.json \
  --output ~/.claude/job-hunt-ai/reports/YYYY-MM-DD-<slot>-<mode>.xlsx
```
`<slot>` = morning (<12 IST) / afternoon (12–17) / evening (17+); `<mode>` = `full` or `native`
(matches RUN_MODE so the filename shows the run type). The script colours rows by score
(≥75 green, 60–74 yellow), freezes the header, hyperlinks the apply link, and caps at 20 rows.
All scored jobs remain in `/tmp/jobpilot_scored.json`.

Print: **"Report written: N scored (M hard-dropped, K no-JD) → <path>"**.

### B6 — Resume tailoring (top matches)

Read `score_threshold` from preferences (default **65**). For freshers
(`experience_years == 0`) use `min(score_threshold, 60)`. For the top 5 jobs with
**`score >= threshold`** (gate on `score`, not `effective_score`) AND
`experience_gate_drop != true` AND `skip_tailoring != true`:
- If `~/.claude/job-hunt-ai/resumes/base.tex` exists: edit it to weave in `matched_skills`
  (never invent experience/dates/employers), write `/tmp/<company>-<job_id>.tex`, compile with
  `tectonic /tmp/<company>-<job_id>.tex --outdir ~/.claude/job-hunt-ai/resumes/tailored/`.
  If tectonic fails, save the `.tex` to `resumes/tailored/` directly.
- Else: `python3 scripts/resume_tailor.py <job_id> --matched-skills <csv>` (DOCX).

Self-cap at 5 per run. If fewer than 5 qualify, print why.

### B7 — Notify (Telegram / Discord)

Build a plain-text digest (top 5 jobs) resolving each apply link via `url_map` (B0) first, then
the scored record's `application_url`:

```
JobPilot — YYYY-MM-DD, <slot> [<mode>]
────────────────────────────────────────
Top matches:

1. <role> @ <company> (Score: <score>)
   <market_salary> | <location>
   <application_url>
   Prep: <prep_focus>          ← only when the job has one

... (up to 5)
────────────────────────────────────────
Total: X raw → Y filtered → Z scored → W tailored
<N> jobs had no JD | <M> hard-dropped (exp. mismatch)
<warnings for any failed scrapers>
Report + tailored resumes attached.
────────────────────────────────────────
```
Flag Google-Form apply URLs (`docs.google.com/forms`, `forms.gle`) with ⚠️ and no-JD jobs with
`[no JD]`. If any Apify actors failed, add `⚠️ <actor> failed — see apify_lessons.json`.

Send via the notifier (respects `preferences.notify_channels`, default Telegram; the XLSX
report and tailored resumes are attached automatically):
```bash
python3 scripts/telegram_notify.py --digest "<text>" --xlsx "<report_path>" --run-mode "<RUN_MODE>"
```
`--run-mode` (`full`/`native`) adds the mode label to the header and, on native runs, appends a
line naming which premium sources were skipped. **Telegram/Discord are the sole delivery
mechanism — there is no Drive step** (removed in issue #12: base64 over the MCP boundary
truncated files > ~10 KB).

---

## Step C — Update the lessons cache

After a full run, update `~/.claude/job-hunt-ai/cache/apify_lessons.json`:
1. For each actor that returned > 0 items: set `last_success` to today.
2. For each failed actor: add a `zero_result_runs` entry if a diagnosis was found.
3. Persist any new `field_overrides` / `value_transforms` from A2.
4. Update `"last_updated"` to today. Write with the Write tool.

---

## Failure handling

Wrap every step so a single failure logs and continues — **never abort the whole pipeline**.
Always attempt B5 (report) and B7 (notify) even if earlier steps partially failed. Track
failures in a `_failed_steps` list: `{"step": "B4-salary-<company>", "reason": "<msg>"}`.

## Final summary

Print:
```
Done. N jobs scored (M hard-dropped, K no-JD). Top match: <company> <role> (score: <X>).
W resumes tailored. Report + resumes → <channels>.
```
If `_failed_steps` is non-empty, append:
```
⚠️ Skipped / degraded steps:
  - <step>: <reason>
Run /job-setup to fix configuration, or check apify_lessons.json for actor failures.
```
This block also rides along in the B7 digest so the user sees failures without the terminal.
