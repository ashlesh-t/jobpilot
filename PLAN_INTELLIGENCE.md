# JobPilot Intelligence Upgrade Plan

Research-grounded plan for upgrading JobPilot's matching intelligence: real hiring-bar data
in scoring, Claude WebSearch as a discovery source, and a recursive learning loop over
`/job-feedback` outcomes. Follow-up to the initial scoring/location upgrade (EPICs A–E, since
implemented); EPICs here continue the lettering at F.

## Root-Cause Analysis (what actually holds intelligence back)

| # | Symptom | Real root cause (evidence) |
|---|---------|----------------------------|
| 1 | **Cross-run memory is broken** — the same jobs are re-scored every run; "seen" dedupe is a no-op | The only writer of `jobs_seen` is [resume_tailor.py:80] which inserts *only* `job_id`, `tailored_resume_path`, dates, `status`. Scored/reported jobs are never recorded. DB proof: 41 rows in `score_cache`, only **6** rows in `jobs_seen` — all with **empty** `company`, `role`, `match_score`. So [dedupe.py:50-53] / [filter.py:86-88] `WHERE status='active'` matches almost nothing. |
| 2 | **/job-feedback is unusable** — the list it shows the user is blank | [job-feedback SKILL Step 1] selects `js.company, js.role, js.location, js.match_score` from `jobs_seen` — all NULL (see #1). The user is asked "What happened with — ?" with no company name. This is why `user_feedback` has **0 rows** despite 6 tailored resumes. The learning loop has no fuel. |
| 3 | **Feedback resurrects jobs** — tagging an outcome makes the job reappear as "new" next run | [feedback.py:52-55] sets `jobs_seen.status = 'applied'/'rejected'/…`, but [dedupe.py:51] and [filter.py:87] exclude only `status='active'`. Any job with feedback drops out of the seen-set and re-enters the pipeline, gets re-scored and re-reported. |
| 4 | **Scoring is blind to the actual hiring bar** | [job-search SKILL B3] and [CLAUDE.md Scoring] compare JD text vs profile text only. But the *interview reality* differs radically by company archetype (research below): Navi = hard DSA gate, Signzy = API/system-design depth, Swiss Re = resume-project deep-dives, Accenture = communication/cognitive screens, GenAI startups = production-RAG portfolio. Two jobs with identical keyword overlap can have opposite realistic odds for this profile — the score can't see it, and the report never tells the user what to prep. |
| 5 | **No learning** — outcomes can never influence anything | [job-search SKILL B3 "Feedback signal"] explicitly says "**Do NOT auto-adjust scores** — just report it". `score_cache` is written ad-hoc but read by nothing (grep: only [dedupe.py:84] DELETE and [jobpilot-clear SKILL]). There is no mechanism, formula, or storage for outcome-driven adjustment. |
| 6 | Fresher-relevant jobs wrongly dropped on experience | [filter.py:116] range regex `(?:-|-|to)` contains two ASCII hyphens but **no en-dash `–`**, though the docstring at [filter.py:115] promises `"2 – 4 yrs"` support. An en-dash JD falls through to the second regex which matches the *upper* bound ("4 yrs") → `exp_req=4 ≥ cap 3` → dropped. Same for "0 – 2 years" fresher posts read as `exp_req=2`. |
| 7 | Doc drift misleads the scoring agent | [CLAUDE.md Key files] still lists `scripts/ats_scorer.py` and `scripts/salary_research.py` (**neither exists**) and a Drive step ([CLAUDE.md Layer B] "drive_upload") that [job-search SKILL B7] says was removed in issue #12. CLAUDE.md's Scoring section cites "[job-search SKILL B2]" but scoring moved to **B3**. Dead code: [apify_scraper.py:206-245] `run_apify_actor`/`_call_apify_actor` (retry path) is never called — `run_actor_safe` uses `_run_actor` with **no retries**, while the digest text promises "failed after 3 retries". |

**Cross-cutting insight:** #1–#3 are one broken chain: nothing durable is recorded per job →
feedback can't be collected → learning is impossible. Fixing the record-keeping (EPIC F) is the
prerequisite for every intelligence feature in this plan.

---

## Research Findings (grounding for EPICs G–I)

Per-archetype interview reality for companies actually present in the latest reports
(`~/.claude/job-hunt-ai/reports/2026-06-29-morning.xlsx`). Aggregate signals only; no
individual profiles.

| Company (archetype) | Rounds & what's actually tested | Source type |
|---|---|---|
| **Navi** — `dsa-gate-product` (fintech product) | 3 rounds: DoSelect online test (aptitude + math + coding), then 2 DSA rounds — 2 problems/90 min, easy-medium DP & binary search, then medium-hard DP; hiring-manager round. Prep advice from offer-holders: "practice DSA a lot, prepare OOP and DBMS". Rejections happen at the DSA rounds. | GeeksforGeeks Interview Experiences: "Navi Technologies Interview Experience for SDE 1" (on-campus 2022, off-campus 2022/2023 — multiple reports) |
| **Signzy** — `api-depth-startup` (fintech startup) | 5 online rounds: MongoDB queries + schema design live; projects + 1 DSA; HLD system design; deep API round (JWT, API standards, Docker/K8s) with Principal engineer; culture fit. Practical web/API depth outweighs raw DSA volume. | LeetCode Discuss "Signzy SDE-1 Bangalore Oct 2023 [Offer]"; Glassdoor Signzy interview questions (83); Naukri Code360 full-stack experience (0–2 yrs) |
| **Swiss Re** — `gcc-enterprise` (insurance GCC) | 3–6 rounds over weeks-to-months: phone screen, technical (resume-project deep-dive; Python/SQL/PySpark/cloud basics), managerial + HR. Projects on the resume drive the technical round. | Glassdoor "Swiss Re Interview Questions in Bangalore" (409 reviews); InterviewQuery Swiss Re SWE guide |
| **Accenture** — `mass-recruiter` | 6 eliminatory stages: AI-graded spoken-English communication test (63 Qs), cognitive ability (critical/abstract/verbal), technical MCQ (pseudocode, CS fundamentals), 2 coding problems in 45 min (easy), then light tech + HR interview (arrays, SQL, OOP, projects, "Why Accenture"). Bar is breadth + communication, not depth. | PrepInsta "Accenture Recruitment Process 2025"; GeeksforGeeks "Accenture Recruitment Process"; Glassdoor ASE interview questions |
| **GenAI startups** (SnapFind, Replicacia, Donyati, Tayana…) — `genai-portfolio-startup` | Screen → technical → system design → behavioral, but content is LLM-era: RAG design, chunking/embedding choices, evals, cost/latency trade-offs, prompt-injection safety, structured outputs. One **production-quality end-to-end RAG project** discussed in depth is the accepted-candidate pattern. | Careery "AI Engineer Interview Questions 2026"; Simplilearn GenAI interview guide; stackoverflowtips Top-50 GenAI/LLM questions |

**Accepted-candidate shape & rejection reasons (fresher, India, 2024–26 batch)** — aggregate:
- Primary stated rejection reason at product companies: cannot solve medium LeetCode / explain
  complexity — "AI-specialization before DSA foundation" is called out as *the* wall for this
  batch. (GetPersonalisedCV analysis "AI/ML Skills vs DSA, India 2026"; Grapevine thread on
  non-DSA startups confirms the DSA gate is the norm, its absence the exception.)
- ATS-level rejection: JD names specific technologies, resume speaks only in generalities.
  (same sources)
- Startups that skip DSA instead test practical depth (APIs, system design, shipped projects)
  — matching the Signzy/GenAI patterns above. (Grapevine; LeetCode Discuss)

**Gap analysis vs this profile** (`~/.claude/job-hunt-ai/cache/profile.json`): strong on
exactly what `genai-portfolio-startup` and `gcc-enterprise` archetypes reward (CogniRepo =
production RAG/MCP system; SparkSentinel = PySpark/Kafka/XGBoost; real internships at Boomi &
GOwarm.ai; VISAPP publication). **Unknown/unrepresented:** any DSA-readiness signal (no
LeetCode/CodeChef handle, no competitive-programming line) — which the research says is the
#1 fresher gate at `dsa-gate-product` companies like Navi, and partially at Accenture-style
coding rounds. Current scoring would rank a Navi SDE JD *above* a Signzy one on keyword overlap
alone, while the realistic odds ordering is likely the reverse. That signal — and the "what to
prep" guidance — is what EPICs G/H add.

---

## Priority & Dependency Overview

- **P0 (foundation, do first):** EPIC F (cross-run memory + feedback repair) — everything else
  feeds on its data. EPIC K quick fixes ride along.
- **P1:** EPIC I (learning loop — the prompt's required epic; depends on F), EPIC G (company
  intel).
- **P2:** EPIC H (bar-aware scoring + gap column; depends on G), EPIC J (WebSearch discovery).
- Layer split: **all** new intelligence lives in Layer B (skills/CLAUDE.md + tiny helpers).
  Layer A ([apify_scraper.py], [dedupe.py], [filter.py], `scripts/scrapers/`) gets only the
  mechanical fixes in F/K — no LLM, no WebSearch, no scoring, per the Layer A invariant.

---

## EPIC F — Cross-Run Memory & Feedback Repair (P0)

> **Goal:** every scored job is durably recorded with company/role/score; `/job-feedback`
> shows real jobs; tagged jobs never resurrect. This is the substrate for learning.

### Story F1 — Record every scored job in `jobs_seen` + `score_cache`

**Problem:** nothing writes scored jobs to the DB ([resume_tailor.py:80] writes only tailored
ones, and only 4 columns), so dedupe-by-seen is a no-op and feedback has nothing to show.
**Solution:** a new Layer-B step in [job-search SKILL] after B3 persists the batch in one
`python3 -c` call (mechanical DB write — no LLM logic, fine to script).

**Tasks**

- F1.1 — Add **Step B3b — Persist scored jobs** to [job-search SKILL] after B3: run a small
  helper `python3 scripts/record_scored.py /tmp/jobpilot_scored.json` that upserts every
  scored job:
  ```sql
  INSERT INTO jobs_seen (job_id, company, role, location, source, match_score,
                         resume_hash, first_seen, last_seen, status)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
  ON CONFLICT(job_id) DO UPDATE SET last_seen=excluded.last_seen,
      match_score=excluded.match_score
      -- never overwrite a feedback status back to 'active'
  ```
  and writes each job's `{matched_skills, missing_skills, score, archetype}` as `score_json`
  into `score_cache` keyed `(job_id, resume_hash)`.
- F1.2 — In [job-search SKILL B3], before scoring each job, check `score_cache` for
  `(job_id, current resume_hash)`; on hit reuse the cached score (log `cache-hit`) instead of
  re-deriving — consistent scores across runs, less work. (Resume changes already clear the
  cache: [dedupe.py:83-86].)
- F1.3 — `scripts/record_scored.py` is Layer-B-invoked but pure Python (no LLM) — document
  that distinction in [CLAUDE.md Key files].

**Acceptance Criteria**

- After one `/job-search`, `jobs_seen` row count ≈ scored count, with non-empty company/role
  and `match_score`; `score_cache` has one row per scored job.
- Second run on the same scrape shows `dedupe: removed_seen > 0` and `cache-hit` logs.
- `/job-feedback` Step 1 lists real company/role/score values.

---

### Story F2 — Stop feedback from resurrecting jobs

**Problem:** [dedupe.py:51]/[filter.py:87] treat only `status='active'` as seen; [feedback.py:53]
rewrites status, so tagged jobs come back.
**Solution:** "seen" means *any* row in `jobs_seen` — status is lifecycle metadata, not
membership.

**Tasks**

- F2.1 — Change both queries to `SELECT job_id FROM jobs_seen` (drop the status predicate) in
  [dedupe.py:50-53] and [filter.py:85-88].
- F2.2 — Keep `status` for reporting: [job-feedback SKILL Step 1] already surfaces it.

**Acceptance Criteria**

- Tag a job `rejected` via `scripts/feedback.py`, re-run dedupe+filter on a raw file containing
  it → it is dropped as seen.
- `/jobpilot-clear` still resurfaces everything (it deletes rows — unchanged behavior).

---

## EPIC G — Company Intelligence at Runtime (P1)

> **Goal:** for the jobs that matter (top of the ranking), Claude knows what the company's
> interview actually tests — cached, cheap, and reflected in the report as prep guidance.

### Story G1 — `company_intel.json` cache + research step

**Problem:** scoring and the report ignore interview reality entirely (root cause #4).
**Solution:** new Layer-B step **B3c — Company intel** in [job-search SKILL]: for the top ~8
jobs by `score ≥ 55`, look up `~/.claude/job-hunt-ai/cache/company_intel.json`; for at most
**5 cache-misses per run**, run 1 WebSearch each and write an entry. TTL 45 days.

**Tasks**

- G1.1 — Cache schema (one entry per lowercased company name):
  ```json
  {
    "navi": {
      "archetype": "dsa-gate-product",
      "rounds": "OT (DoSelect) + 2 DSA rounds + HM round",
      "tests": ["DSA medium (DP, binary search)", "OOP", "DBMS"],
      "dsa_intensity": "high",
      "fresher_friendly": true,
      "prep_focus": "Grind medium DP/graph problems; be fluent in complexity analysis",
      "sources": ["geeksforgeeks.org/interview-experiences/navi-technologies-..."],
      "fetched_at": "2026-07-19",
      "ttl_days": 45
    }
  }
  ```
  Archetype enum: `dsa-gate-product | api-depth-startup | genai-portfolio-startup |
  gcc-enterprise | mass-recruiter | unknown`.
- G1.2 — WebSearch query template (exactly one query per company, in this order of preference):
  `"<company> <role-family> interview experience rounds site:geeksforgeeks.org OR site:ambitionbox.com OR site:glassdoor.co.in"` —
  falling back to the same query without the site filter. If nothing credible is found, write
  `{"archetype": "unknown", "sources": [], ...}` so the miss is cached too (don't re-search
  every run).
- G1.3 — Seed the cache at implementation time with the five researched entries from the
  Research Findings table above (Navi, Signzy, Swiss Re, Accenture + a `genai-portfolio-startup`
  template entry) so the feature works from run one.
- G1.4 — Document the cache in [CLAUDE.md Data directory] tree.

**Acceptance Criteria**

- A run performs ≤5 WebSearch intel lookups; repeat run performs 0 for the same companies.
- Every top-8 scored job carries `archetype` and `prep_focus` fields in
  `/tmp/jobpilot_scored.json`.
- Entries older than `ttl_days` are re-fetched; `unknown` entries are cached like real ones.

---

### Story G2 — "Prep Focus" in the report and digest

**Tasks**

- G2.1 — [report_generator.py]: add a `Prep Focus` column (after `Missing Skills`) reading
  `job["prep_focus"]`, blank when absent.
- G2.2 — [job-search SKILL B7] digest: append one line to each top-5 entry:
  `   Prep: <prep_focus>` when present.

**Acceptance Criteria**

- XLSX shows Prep Focus for intel-covered rows; blank (not "None") otherwise.
- Telegram digest top-5 entries include the prep line.

---

## EPIC H — Interview-Bar-Aware Scoring & Gap Signals (P2)

> **Goal:** the score reflects realistic odds against the company's actual bar — not just JD
> text — and the report tells the user what's missing.

### Story H1 — Additive `interview_readiness` profile fields

**Problem:** the profile has no DSA/system-design readiness signal, yet that's the #1 fresher
gate (research above). Additive fields only — no renames.

**Tasks**

- H1.1 — [job-setup SKILL] Step F: after building `profile.json`, ask (setup is interactive —
  allowed there) and store:
  ```json
  "interview_readiness": {
    "dsa_level": "none | basic | medium | strong",
    "leetcode_url": "",
    "system_design": "none | basic | good",
    "spoken_english": "basic | good | fluent"
  }
  ```
- H1.2 — [job-search SKILL Step 1]: if the field is absent (old profile), default every key to
  `"unknown"` and continue — never block, never ask (autonomy contract).

**Acceptance Criteria**

- Fresh `/job-setup` writes the block; existing profiles keep working unchanged.
- No `/job-search` question is ever asked for it.

---

### Story H2 — `bar_fit` adjustment + `gap_signals`

**Problem:** archetype and readiness exist (G1/H1) but don't touch scoring or the report.
**Solution:** a small, bounded, explainable term computed inline by Claude in B3.

**Tasks**

- H2.1 — In [job-search SKILL B3], after computing `score`, compute
  `bar_fit ∈ [-8, +8]` from the archetype × readiness matrix (Claude judgment, guided):
  - `dsa-gate-product` + `dsa_level in (none, basic, unknown)` → −8 … −4
  - `genai-portfolio-startup` + profile has shipped RAG/LLM project → +4 … +8
  - `gcc-enterprise` + strong resume projects → +2 … +5; `mass-recruiter` → 0 (bar is generic)
  - `unknown` archetype → 0.
  Apply to **`effective_score` only** (`effective_score = score * location_weight + bar_fit`)
  — ranking, never threshold gates, mirroring the existing location rule
  ([CLAUDE.md Scoring] "never multiply by location_weight" precedent).
- H2.2 — `gap_signals` (≤3 short strings) per top-20 job: what the bar demands that the
  profile can't show (e.g. `"No DSA signal — Navi gates on medium DP"`). New report column
  `Gap Signals`; also drives `prep_focus` when intel is missing.
- H2.3 — Document `bar_fit` + the matrix in [CLAUDE.md Scoring] with one worked example
  (Navi SDE vs Signzy SDE-1 for this profile).

**Acceptance Criteria**

- `score` (and every gate: tailoring, salary) is byte-identical with the feature on/off;
  only ordering and new columns change.
- |bar_fit| ≤ 8 always; `why` mentions it whenever |bar_fit| ≥ 4.
- On current data, a Navi-style DSA-gate job with `dsa_level: unknown` ranks below an
  equal-score GenAI-startup job.

---

## EPIC I — Recursive Learning Loop (P1 — required)

> **Goal:** outcomes recorded by `/job-feedback` continuously and safely re-weight ranking —
> a concrete formula with hard caps, all in Layer B, cold-start neutral.

### Story I1 — `learning.json` store

**Tasks**

- I1.1 — New cache `~/.claude/job-hunt-ai/cache/learning.json`:
  ```json
  {
    "version": 1,
    "updated_at": "2026-07-19T00:00:00Z",
    "outcome_count": 0,
    "skill_weights": {},
    "archetype_weights": {},
    "source_weights": {}
  }
  ```
  Missing key ⇒ weight `1.0` (neutral). Missing file ⇒ everything neutral — cold-start safe.
- I1.2 — Document in [CLAUDE.md Data directory] + a new "Learning loop" section.

### Story I2 — Update rule (trigger, formula, caps)

**Trigger:** at the **end of every `/job-feedback` run**, for each *newly recorded* outcome.
Weights are *written* immediately but only *applied* in scoring once
`outcome_count >= 5` (single data points can't steer anything before there's a trend).

**Update rule** — for one outcome on job J with outcome value
`v ∈ {offer: +1.0, interview: +0.6, applied: 0.0, ghosted: -0.3, rejected: -0.6}`:

```
signals(J) = matched_skills(J)            # from score_cache.score_json (EPIC F)
           ∪ {archetype(J)}               # from company_intel.json (EPIC G), if known
           ∪ {source_board(J)}
for s in signals(J):
    w[s] = clip(w[s] + 0.05 * v, 0.7, 1.3)     # α = 0.05
outcome_count += 1
```

Caps make it wreck-proof: one outcome moves any weight by ≤ 0.05 (offer) — it takes **6+
consistent outcomes** to reach a cap; range `[0.7, 1.3]` bounds total influence; `applied`
is deliberately 0 (applying says nothing about fit).

**Applying it (Layer B, ranking only)** — in [job-search SKILL B3] after `effective_score`:

```
relevant = matched_skills ∪ {archetype, source_board} (only keys present in learning.json)
learning_adj = clip(10 * (mean(w[s] for s in relevant) - 1.0), -10, +10)   # 0 if none/[]
effective_score += learning_adj          # NEVER touches `score` or any threshold gate
```

**Tasks**

- I2.1 — Extend [job-feedback SKILL] with **Step 3b — Update learning weights**: after each
  `scripts/feedback.py` call, Claude reads `score_cache.score_json` + `company_intel.json` for
  that job and applies the formula above to `learning.json` (read-modify-write with the Write
  tool; read first per repo rule). Print each moved weight:
  `learning: golang 1.00 → 1.03 (interview @ Swiss Re)`.
- I2.2 — Wire the apply-side into [job-search SKILL B3], replacing the current
  "Do NOT auto-adjust scores" line ([job-search SKILL B3 Feedback signal]) with: report the
  pattern **and** apply `learning_adj` to `effective_score` when `outcome_count >= 5`;
  append `(learning +N)` to `why` when `|learning_adj| >= 2`.
- I2.3 — `/jobpilot-clear` resets `learning.json` to the empty template ([jobpilot-clear
  SKILL]) — history reset must also reset learned bias.
- I2.4 — Document trigger + formula + caps verbatim in [CLAUDE.md] so skill and doc can't
  drift.

**Acceptance Criteria**

- With 0–4 outcomes: `learning_adj = 0` for every job (weights may exist but aren't applied).
- Simulate 6 outcomes (2 offers on golang jobs, 2 rejections on dsa-gate jobs, …):
  every touched weight within `[0.7, 1.3]`, each single update ≤ 0.05, `effective_score`
  shifts by ≤ ±10, and **no** job crosses/loses a tailoring or salary gate because of it.
- Deleting `learning.json` mid-life returns scoring to exactly the pre-learning behavior.
- Layer A scripts remain LLM-free and learning-free (grep for `learning.json` in `scripts/`
  matches nothing except optional `record_scored.py` comments).

---

## EPIC J — Claude WebSearch as a Discovery Source (P2)

> **Goal:** the third sourcing channel the user asked for — native scrapers + Apify + Claude's
> own WebSearch — costs nothing and reaches postings boards miss.

### Story J1 — Bounded WebSearch discovery step

**Tasks**

- J1.1 — New **Step A5 — WebSearch discovery (Layer B)** in [job-search SKILL], after A4,
  before B0. Run ≤3 searches built from preferences:
  ```
  "<role_type> fresher 2026 <city>" (site:boards.greenhouse.io OR site:jobs.lever.co OR site:jobs.ashbyhq.com)
  "<preferred_stack[0]> <role_type> hiring <city>" posted this week
  "<role_type> new grad remote india apply"
  ```
- J1.2 — For each credible posting found (≤10 total): build the canonical dict —
  `job_id = make_job_id(company, role, location, "websearch")` (same SHA1 helper,
  [scrapers/_common.py]), `source_board: "websearch"`, `has_jd` per fetched text — skip ids
  already in the seen set or `/tmp/jobpilot_filtered.json`, then append to
  `/tmp/jobpilot_filtered.json` (read → merge → write), mirroring the existing A4
  career-crawl pattern ([job-search SKILL A4]).
- J1.3 — These jobs flow through B0–B7 on equal footing; the digest's source breakdown gains a
  `websearch=N` entry.

**Acceptance Criteria**

- ≤3 searches and ≤10 added jobs per run; every added job has an apply URL (the found page).
- No duplicates vs scraper output (job_id collision test).
- Zero changes to Layer A scripts.

---

## EPIC K — Correctness Quick Fixes (P0, ride-along)

### Story K1 — Experience-range en-dash + lakh false positives

**Tasks**

- K1.1 — [filter.py:116]: change the separator class to `(?:-|–|—|to)` (ASCII hyphen,
  en-dash, em-dash, "to") so `"2 – 4 yrs"` parses as lower-bound 2, and `"0 – 2 years"` as 0.
- K1.2 — [filter.py:231-233]: require a CTC-ish context around the lakh regex — e.g.
  `(?:ctc|salary|package|₹|rs\.?|inr|upto|up to)\D{0,15}(\d…)lpa|lakhs?` — so "10 lakh users"
  stops parsing as compensation.

**Acceptance Criteria**

- `extract_exp_req({"jd_full": "2 – 4 yrs"}) == 2`; `"0 – 2 years"` → 0.
- A JD containing only "serving 10 lakh customers" yields `ctc_unknown=True`, not a CTC match.

### Story K2 — Documentation truth & dead code

**Tasks**

- K2.1 — [CLAUDE.md Key files]: remove `ats_scorer.py`, `salary_research.py`, `drive_upload.py`
  rows (or mark drive as removed); fix the Scoring section's "[SKILL B2]" refs to **B3**; add
  `record_scored.py`, `company_intel.json`, `learning.json`.
- K2.2 — [apify_scraper.py:206-245]: delete the unused `run_apify_actor`/`_call_apify_actor`
  pair **or** route `run_actor_safe` through the retry loop; either way, make the digest's
  "after 3 retries" claim true or remove it ([job-search SKILL B7]).

**Acceptance Criteria**

- Every path named in CLAUDE.md exists; every SKILL step reference resolves.
- `grep -n "run_apify_actor" scripts/` shows either 0 defs or ≥1 call site.

---

## Out of Scope (tracked)

- Auto-scraping Blind (login-walled; only public aggregate claims used, per prompt constraint).
- Any per-candidate LinkedIn profile analysis — explicitly excluded by the prompt's ethics
  constraint; company intel stays at the aggregate level with cited sources.
- New paid services — everything above uses the already-integrated stack (Apify, Telegram,
  Claude WebSearch, SQLite, JSON caches).

---

## Suggested Execution Order for Implementing Agent

1. **F1 + F2 + K1 + K2** (memory/feedback substrate + mechanical fixes)
2. **I1 + I2** (learning loop — becomes useful the day feedback starts flowing)
3. **G1 + G2** (company intel + prep focus, seeded with this document's research)
4. **H1 + H2** (bar-aware ranking + gap signals)
5. **J1** (WebSearch discovery)

Each story is independently shippable and verifiable against its AC.
