# JobPilot Upgrade Plan

## Root-Cause Analysis (what actually broke)

| # | Symptom | Real root cause (evidence) |
|---|---------|----------------------------|
| 1 | Scores feel low; **0 jobs hit 60** → no tailoring, no salary | `keyword_score = len(matched)/len(profile.skills)*100` divides by **all 42 profile skills** ([CLAUDE.md scoring], [job-search SKILL B2]). A focused JD (e.g. Golang backend) can only ever mention ~8 of 42 → keyword_score caps near ~20. The 0.5/0.5 blend then drags the total to ~50. `effective_score` multiplies *again* by `location_weight`, double-penalising. |
| 2 | Internshala unfairly down-ranked | [filter.py:138-151] `location_weight()` uses bare `pl in loc` substring match. `CITY_ALIASES` ([filter.py:31]) is only wired into `location_ok` (keep/drop), **not** the weight. Internshala lists "Bangalore", preference is "Bengaluru" → no match → default **0.6**. Naukri lists "Bengaluru" → **1.0**. Navi/SnapFind (great fits) lost purely on a spelling. |
| 4 | Missing/broken apply links | **Apify actors return URLs under field names `normalize()` doesn't check.** Raw audit: naukri **0/20**, cutshort **0/30**, wellfound **0/46**, linkedin **0/1** have URLs. Native scrapers: **100%**. The `pick()` list at [apify_scraper.py:113] misses their actual key. Also no `job_id→url` map is preserved when Claude rebuilds the scored JSON, so any captured URL can be dropped. |
| 5 | HN useless (480 → 2) | [fetch_hn_whoishiring apify_scraper.py:227] queries Algolia `query="who is hiring", tags=story, hitsPerPage=1` **sorted by relevance, not date** → it grabbed item **22665510 ≈ March 2020**. Every HN "job" is a 6-year-old dead post. Pipe-splitting `Company \| Role \| Location` is also fragile. |
| 6 | Asks for permission mid-run | [settings.local.json] allowlist is keyed to **exact command strings**. Any new command/arg prompts. No broad allowlist for the pipeline scripts or Drive MCP write calls. |
| 3 | Telegram channels dead | Invalid usernames — tracked separately, being fixed by user. |

**Cross-cutting insight:** problems 1 and 2 compound. A genuinely strong match (Navi AI Scientist, raw 55.9) becomes effective 33.5 — *below* a weak Naukri job at full location weight. The ranking is currently driven more by location-string luck than by fit.

---

## Priority & Dependency Overview

- **P0 (correctness, do first):** EPIC C (apply links), EPIC A (scoring)
- **P1:** EPIC B (location), EPIC E (autonomy)
- **P2:** EPIC D (free sources)
- EPIC B Story B2 depends on B1. EPIC A Story A2 is independent of A1.

---

## EPIC A — Trustworthy Scoring

> **Goal:** A strong single-stack match scores in the 70–90 band so it crosses tailoring/salary thresholds. Location must influence *ranking* without crushing *absolute* score.

### Story A1 — Fix keyword_score denominator

**Problem:** dividing by all 42 skills makes a perfect focused match look mediocre.
**Solution:** score against **JD-relevant skills**, not the whole profile.

**Tasks**

- A1.1 — Change formula in [CLAUDE.md] and [job-search SKILL B2] to:
  `keyword_score = len(matched_skills) / max(len(jd_hard_skills), 1) * 100`, where `jd_hard_skills` = the set of concrete tech skills *the JD actually asks for* (Claude extracts this — already computed as `must_have` + `nice_to_have`).
- A1.2 — Cap at 100; floor matched set to skills present in profile.
- A1.3 — Document the new formula with one worked example (Swiss Re Golang).

**Acceptance Criteria**

- A Golang-only JD where the candidate has Go+Docker+K8s+CI/CD+microservices scores `keyword_score ≥ 70`.
- No job can exceed 100; jobs with zero JD-skill overlap score 0.
- CLAUDE.md and SKILL.md describe the *same* formula (no drift).

---

### Story A2 — Separate absolute score from location ranking

**Problem:** `effective_score = score * location_weight` corrupts the human-readable score and stacks on top of an already-low number.
**Solution:** keep `score` as pure fit (0–100, drives thresholds); use `effective_score` **only for sort order**, never for threshold gates.

**Tasks**

- A2.1 — In [SKILL B2/B5/B3]: gate tailoring (`score_threshold`) and salary research on **`score`**, not `effective_score`.
- A2.2 — Soften the weight curve so 2nd-choice/remote isn't a cliff: `1.0 / 0.85 / 0.7` instead of `1.0 / 0.7 / 0.4` ([filter.py:144-151]).
- A2.3 — Report shows both `Match Score` (pure) and a separate `Rank Score` column.

**Acceptance Criteria**

- A job with `score=72, location_weight=0.85` is tailored (72 ≥ threshold) even though `effective_score=61`.
- XLSX shows pure score in `Match Score`; sort order follows rank score.
- Re-running this exact dataset produces ≥3 jobs above the 60 tailoring threshold (vs 0 today).

---

## EPIC B — Claude-Owned Canonical Location Resolution

> **Goal:** "Bangalore" = "Bengaluru" = "BLR" everywhere, decided by Claude (not brittle Python), with canonical forms cached at setup so runs stay cheap.

### Story B1 — Build a canonical-cities cache during /job-setup

**Solution:** during setup, Claude resolves each preference location to a canonical record and writes it to cache; the pipeline reads it.

**Tasks**

- B1.1 — In [job-setup SKILL], after the location question, have Claude emit `~/.claude/job-hunt-ai/cache/locations.json`:
  ```json
  {
    "canonical": {
      "bengaluru": {
        "aliases": ["bangalore", "blr", "bengaluru urban"],
        "priority_rank": 0,
        "weight": 1.0
      },
      "remote": {
        "aliases": ["work from home", "anywhere", "wfh"],
        "priority_rank": 1,
        "weight": 0.85
      }
    }
  }
  ```
- B1.2 — Seed it from `location_priority`; Claude expands aliases (incl. regional/airport codes) using its own knowledge.
- B1.3 — Keep [filter.py:31] `CITY_ALIASES` only as an offline fallback if the cache is absent.

**Acceptance Criteria**

- After setup, `locations.json` exists with every preference city + ≥2 aliases each.
- Re-running setup with the same prefs is idempotent (no dupes).
- Deleting the cache and running pipeline still works via the Python fallback.

---

### Story B2 — Use the cache for weighting (Layer A) and let Claude override (Layer B)

**Solution:** `location_weight()` consults the cache + aliases; Claude can correct edge cases during scoring.

**Tasks**

- B2.1 — Rewrite [filter.py location_weight()] to load `locations.json` and match job location against `aliases` (not bare `pl in loc`), returning the cached `weight`.
- B2.2 — In [SKILL B2], instruct Claude to re-resolve any job whose location is ambiguous/empty and set a corrected `location_weight` before ranking.
- B2.3 — Log per-job: `location matched <canonical> via alias <x> → weight w`.

**Acceptance Criteria**

- An Internshala "Bangalore" job gets the **same weight (1.0)** as a Naukri "Bengaluru" job.
- On the captured dataset, Navi & SnapFind rank above the weak full-weight Naukri jobs.
- A job with location `""` is resolved by Claude, not silently defaulted to 0.6.

---

## EPIC C — Apply-Link Integrity (P0)

> **Goal:** Every job in the report has a working, deep apply link, or is explicitly flagged `no-link`. No silent blanks; no homepage redirects.

### Story C1 — Fix Apify actor URL extraction

**Problem:** naukri/cutshort/wellfound/linkedin return 0 URLs because the field name isn't in `pick()`.

**Tasks**

- C1.1 — Run each Apify actor once and dump raw keys (one-off diagnostic) to find the true URL field per actor (likely `jobUrl`/`detailUrl`/`jobPostUrl`/`positionUrl`/`startupUrl`).
- C1.2 — Extend the `pick()` URL list at [apify_scraper.py:113] and/or add a per-actor `url_field` override in the lessons cache (mirrors existing `field_overrides` mechanism).
- C1.3 — If an actor truly returns no URL, synthesise a deterministic search/deep link (e.g. Naukri job-title search URL) rather than leaving blank.

**Acceptance Criteria**

- naukri/cutshort/wellfound URL coverage goes from 0% to **≥90%** on a live run.
- A captured naukri URL opens the **specific job posting**, not naukri.com home.
- Per-actor URL field is recorded in `apify_lessons.json` so it survives.

---

### Story C2 — Preserve a job_id → apply_url map end-to-end

**Problem:** URLs get lost when Claude rebuilds the scored JSON.

**Tasks**

- C2.1 — In [SKILL B1/B2], before scoring, build `url_map = {job_id: application_url}` from `/tmp/jobpilot_filtered.json` and re-attach `application_url` to every scored record from this map (never hand-retype).
- C2.2 — [report_generator.py] already reads `application_url`; add a guard that logs any row where it's empty.
- C2.3 — Telegram digest pulls the same map.

**Acceptance Criteria**

- Every job present in `filtered.json` with a URL still has that exact URL in `scored.json`, the XLSX, and the digest.
- Report-gen prints `[report] N rows missing apply link: <ids>` if any are blank.

---

### Story C3 — Apply-link validation + LinkedIn resolution

**Problem:** LinkedIn-guest links don't resolve; some redirect.

**Tasks**

- C3.1 — Add a lightweight HEAD/GET check (Layer B, cap ~25, ~5s each) that flags `link_status: ok|redirect|dead`.
- C3.2 — For LinkedIn no-JD jobs, run the **already-specified but skipped** [SKILL B1 JD-enrichment] (WebFetch the job URL / company careers) — recovers both JD *and* a canonical apply URL.
- C3.3 — Fix URL encoding for links with en-dashes/special chars (the `%E2%80%93` Jumbo case).
- C3.4 — In the report, render `link_status` so dead links are visible.

**Acceptance Criteria**

- LinkedIn jobs in the report carry a resolvable URL or an enriched company-careers URL.
- Dead/redirect links are flagged, not presented as good.
- The Jumbo-style encoded URL opens correctly.

---

## EPIC D — Free-Source Health & Expansion (P2)

> **Goal:** Maximise free, high-signal sources before spending Apify credit.

### Story D1 — Fix Hacker News "Who is Hiring" freshness

**Problem:** fetching a 2020 thread.

**Tasks**

- D1.1 — Replace the relevance search in [apify_scraper.py:230] with `search_by_date`, filter `author_whoishiring` + title `Ask HN: Who is hiring`, pick the **most recent** thread (current month).
- D1.2 — Harden the `Company | Role | Location` parse: tolerate missing pipes; treat `REMOTE`/`Remote (India)` correctly; drop rows that don't parse into a plausible role.
- D1.3 — Tag each HN job with the thread month so staleness is visible.

**Acceptance Criteria**

- HN jobs come from the **latest** monthly thread (posted_date within ~35 days).
- HN survivors after filter are real, current postings (spot-check 5).
- Malformed comments are dropped, not turned into `role="See post"` noise.

---

### Story D2 — Add 2–3 more free sources

**Tasks**

- D2.1 — Add native scrapers for additional free India-relevant boards (e.g. Wellfound public RSS where available, YC Work-at-a-Startup public list, Hasjob/Instahyre public listings) following the [_common.build_job] schema.
- D2.2 — Register them under `_native_sources` in [config/actors.json].
- D2.3 — Respect `job_market_focus` via `region_ok` ([_common.py:87]).

**Acceptance Criteria**

- At least 2 new free sources return >0 jobs on a run.
- Each emits the canonical schema and 100% apply-URL coverage (the native-scraper bar).
- No new source calls Apify or the LLM (Layer A invariant).

---

## EPIC E — One-Shot Autonomous /job-search (P1)

> **Goal:** `/job-search` runs start→finish with **zero permission prompts** (everything is already configured at setup).

### Story E1 — Pipeline command allowlist

**Tasks**

- E1.1 — Add a project [`.claude/settings.json`] (committed, not `.local`) allowlisting the pipeline: `Bash(python3 scripts/apify_scraper.py*)`, `dedupe.py`, `filter.py`, `report_generator.py`, `telegram_notify.py*`, `drive_upload.py`, plus `Bash(python3 -c *)` and the Drive MCP `search_files`/`create_file`.
- E1.2 — Replace exact-string entries in [settings.local.json] with prefix patterns.
- E1.3 — Document in [job-search SKILL] that it assumes setup is complete and must not call AskUserQuestion.

**Acceptance Criteria**

- A full `/job-search` completes without a single permission prompt on a configured machine.
- No secret-bearing command is broadened (tokens still only via `secrets.py`).
- `/job-search` contains no AskUserQuestion calls.

---

### Story E2 — Graceful degradation, never block

**Tasks**

- E2.1 — Audit [SKILL] failure handling so any step failure logs + continues (B4/B6/B7 always attempted) — already specified; verify no interactive fallback remains (e.g. the inline APIFY_TOKEN prompt must be skipped in autonomous mode).
- E2.2 — Summarise skipped/failed steps in the final digest.

**Acceptance Criteria**

- Killing Apify mid-run still produces a report from native results with a noted warning.
- No step waits on stdin during `/job-search`.

---

## Out of Scope (tracked, user owns)

- **Telegram channels (problem 3):** user is fixing the usernames. Suggest moving the list to `config/telegram_channels.json` (already exists) and having Claude validate each channel resolves during `/job-setup` Step G, flagging dead ones instead of failing silently.

---

## Suggested Execution Order for Implementing Agent

1. **C1 + C2** (apply links — highest user-visible pain, pure Layer A/skill fix)
2. **A1 + A2** (scoring — unblocks tailoring & salary)
3. **B1 + B2** (location canonicalization)
4. **E1 + E2** (autonomy)
5. **D1 + D2** (free sources)

Each story is independently shippable and verifiable against its AC.
