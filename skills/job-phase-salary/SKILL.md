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

1. **AmbitionBox actor** via the Apify MCP if it's available:
   `call-actor "thirdwatch/ambitionbox-scraper"` with
   `{ "companies": ["<company>"], "roles": ["<role-slug>"], "includeCompanyReviews": false }`
2. **Fallback** — `WebSearch`:
   `"<company> <role> salary India LPA" site:ambitionbox.com OR glassdoor.co.in`

## What to write

- `market_salary` — the observed range, e.g. `"8–14 LPA"`
- `your_demand` — `round_to_0.5( max(target_ctc_min_lpa, market_75th_pct * score / 100) )`,
  never below `target_ctc_min_lpa` from preferences
- `salary_source` — one of `AmbitionBox` / `Glassdoor` / `web-estimated` / `not-found`

**Never invent a number.** Leave the field blank and set `salary_source: "not-found"` when
you're unsure. A blank cell is honest; a fabricated range walks the user into a negotiation
with a wrong anchor.

Write the results back into the artifact.

Print: **"Salary: N researched, M found a real range"**.
