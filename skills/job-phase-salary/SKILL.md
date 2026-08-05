---
name: job-phase-salary
description: "JobPilot pipeline phase 8 of 11 — research the real market salary range for top matches and compute what to ask for. Invoked by the orchestrator as /job-phase-salary; not meant to be run directly."
---

# Phase: Salary research

Carved verbatim out of `/job-search` step B4.

## Contract

- **Input**: `scored.json`
- **Output**: `scored.json` — rewritten in place with salary fields added.
- Run fully autonomously. Optional phase: if research fails, leave the fields blank and
  finish cleanly.

The orchestrator appends a RUN CONTEXT block with the exact absolute paths for this run.

## Which jobs

The top ~20 by `score` with **`score >= 55`** and `experience_gate_drop != true`.

Gate on `score`, not `effective_score` — a score-72 job in a second-choice city still
deserves the research, and `effective_score` has location weighting baked into it.

## How

This phase always runs on the fast model tier (Haiku-class) — a market-CTC lookup is
simple search-and-read work, not judgment, and a heavier model answers it no better for
a much higher cost. The orchestrator enforces this; it isn't something to second-guess
in the run.

Run one `WebSearch` per job, using the job's own `exp_req_years` (fall back to the
profile's `experience_years` if the job doesn't state one):

```
Average CTC <company> <role>, <years> years of experience
```

Example: `Average CTC Swiss Re Software Engineer, 2 years of experience`

Read the result snippets (AmbitionBox, Glassdoor, Levels.fyi, Naukri and similar salary
aggregators show up directly in these searches — no separate actor call needed) and
extract the range they report. If the first search returns nothing usable, one retry
with the role's seniority dropped (e.g. "Software Engineer" instead of "Senior Software
Engineer II") is fine; don't keep querying past that.

## What to write

- `market_salary` — the observed range, e.g. `"8–14 LPA"`
- `your_demand` — round to the nearest 0.5 LPA: the top of the observed range if
  `score >= 80`, the midpoint if `65 <= score < 80`, the low end otherwise — but never
  below `target_ctc_min_lpa` from preferences, regardless of what the range says
- `salary_source` — one of `web-search` / `not-found`

**Never invent a number.** Leave the field blank and set `salary_source: "not-found"` when
you're unsure. A blank cell is honest; a fabricated range walks the user into a negotiation
with a wrong anchor.

Write the results back into the artifact.

Print: **"Salary: N researched, M found a real range"**.
