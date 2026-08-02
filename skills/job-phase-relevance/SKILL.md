---
name: job-phase-relevance
description: "JobPilot pipeline phase 5 of 11 — drop off-domain roles, apply the experience gate, and recover missing job descriptions. Invoked by the orchestrator as /job-phase-relevance; not meant to be run directly."
---

# Phase: Relevance and job-description enrichment

Carved verbatim out of `/job-search` steps B0, B1 and B2. Everything the scoring phase
needs is prepared here, so scoring never has to fetch a page.

## Contract

- **Input**: `filtered.json` and `discovered.json` (the latter may be absent or `[]`).
- **Output**: `relevant.json` — the merged, relevance-checked, JD-enriched job list.
- Run fully autonomously. Never ask a question. Never score anything here.

The orchestrator appends a RUN CONTEXT block with the exact absolute paths for this run.

## Step 1 — Merge and preserve apply URLs

Concatenate both inputs, deduplicating on `job_id`. Then build the URL map, before any
record is rebuilt — a lost apply link makes a job useless no matter how well it scores:

```python
url_map = {job["job_id"]: job.get("application_url", "") for job in jobs}
```

Re-attach it to every record you write out:

```python
job["application_url"] = job.get("application_url") or url_map.get(job["job_id"], "")
```

## Step 2 — Experience gate (hard drop, but keep the record)

Read `~/.claude/job-hunt-ai/cache/profile.json` for `experience_years`.

Scan `jd_full` for explicit requirements — "X+ years", "minimum X years", "X-Y years of
experience", "requires X years" — and extract `required_years`.

If `required_years > profile.experience_years + 2`:

- set `experience_gate_drop: true`, `score: 0`, `effective_score: 0`
- set `why: "Hard drop: role requires <N>yr, profile has <M>yr"`
- **keep the job in the output.** It belongs at the bottom of the report, not in the bin —
  later phases skip it for salary research and tailoring.

## Step 3 — Domain relevance

Drop jobs that are clearly not the user's field:

- sales / HR / finance / legal roles when `role_types` is engineering
- contract or freelance-only listings when the user wants full-time
- gibberish or empty titles

**Keep everything ambiguous.** Over-filtering here is invisible and unrecoverable — a job
you drop never appears anywhere in the UI. Under-filtering just costs a little scoring
time.

## Step 4 — Recover missing job descriptions (cap 25)

For jobs where `jd_full` is empty or under 120 characters:

1. `WebFetch` the `application_url` — LinkedIn and company pages often render the
   description without a login.
2. If that yields nothing, `WebSearch` `"<company> <role> careers"` and `WebFetch` the
   company's careers or ATS page.

Write recovered text into `jd_full` and set `jd_source: "fetched"`. Skip any page taking
more than ~8 seconds. Cap at 25 fetches for the whole phase.

**Never scrape LinkedIn with a logged-in session** — it risks getting the account banned.

Jobs still without a description keep `has_jd: false`; the scoring phase handles them with
a lower-confidence formula rather than discarding them.

## Step 5 — Write

Write the full list to the output path and print:

**"Relevance: Z in → N kept for scoring (M hard-dropped on experience, K descriptions recovered)"**
