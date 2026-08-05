---
name: job-phase-intel
description: "JobPilot pipeline phase 7 of 11 — research how each company interviews, adjust ranking for the interview bar, and apply learned weights. Invoked by the orchestrator as /job-phase-intel; not meant to be run directly."
---

# Phase: Company intelligence and bar-aware ranking

Carved verbatim out of `/job-search` step B3b. Job-description text can't show the *hiring
bar*: some companies gate freshers on medium DSA, others dig into your projects, others
screen on communication. This phase adds that.

## Contract

- **Input**: `scored.json`
- **Output**: `scored.json` — rewritten in place with intel fields and updated
  `effective_score`.
- Everything here adjusts **ranking only**. `score` and every threshold gate (tailoring,
  salary) must come out untouched.
- Run fully autonomously. This phase is optional — if research fails, leave the ranking
  as it is and finish cleanly.

The orchestrator appends a RUN CONTEXT block with the exact absolute paths for this
run, including `instance_cache_dir` and `user_cache_dir` — use those, never the
`~/.claude/job-hunt-ai/cache/` path directly, since this instance may have more than
one account.

## Step 1 — Company intel

Read `<instance_cache_dir>/company_intel.json` first — company interview intel is
public research, shared across every account on this instance, not personal history.
For the top ~8 jobs with `score >= 55`, look up the lowercased company name.

For at most **5 cache misses per run**, run one WebSearch each:

```
"<company> <role-family> interview experience rounds site:geeksforgeeks.org OR site:ambitionbox.com OR site:glassdoor.co.in"
```

Retry once without the site filter. Write what you learn back to the cache:

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
gcc-enterprise | mass-recruiter | unknown`.

**Cache the misses too**, as `{"archetype": "unknown", ...}` — otherwise every run pays to
re-search the same company and learns nothing. Re-fetch entries older than `ttl_days`.

Attach `archetype` and `prep_focus` to each covered job.

## Step 2 — bar_fit ∈ [−8, +8]

From archetype × `profile.interview_readiness`. Treat a missing `interview_readiness`
block as all-`unknown` — **never ask the user**, this phase runs unattended.

| Situation | `bar_fit` |
|---|---|
| `dsa-gate-product` and `dsa_level` is none/basic/unknown | −8 … −4 |
| `genai-portfolio-startup` and the profile has a shipped RAG/LLM project | +4 … +8 |
| `gcc-enterprise` with strong resume projects | +2 … +5 |
| `mass-recruiter` or `unknown` archetype | 0 |

## Step 3 — learning_adj

Read `<user_cache_dir>/learning.json` — this account's own outcome-learned weights,
never another account's. **Skip this step entirely** if the file is missing or
`outcome_count < 5` — a handful of outcomes is noise, not signal.

```
relevant     = matched_skills ∪ {archetype, source_board}   # only keys present in the file
learning_adj = clip(10 * (mean(w[s] for s in relevant) - 1.0), -10, +10)   # 0 if relevant is empty
```

## Step 4 — Re-rank and write

For every job:

```
effective_score = score * location_weight + bar_fit + learning_adj
```

Add `gap_signals` (≤3 short strings) to each top-20 job — what this company's bar demands
that the profile can't demonstrate, e.g. `"No DSA signal — this company gates on medium DP"`.

Append `(bar N)` or `(learning N)` to `why` when `|bar_fit| >= 4` or `|learning_adj| >= 2`,
so the ranking stays explainable.

Re-rank by `effective_score` and rewrite the artifact.

Print: **"Intel: N companies researched (M cache hits), K jobs re-ranked"**.
