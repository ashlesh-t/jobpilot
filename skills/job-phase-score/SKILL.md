---
name: job-phase-score
description: "JobPilot pipeline phase 6 of 11 — score every job against the user's profile and write the scored artifact. Invoked by the orchestrator as /job-phase-score; not meant to be run directly."
---

# Phase: ATS scoring

Carved verbatim out of `/job-search` step B3. This is the phase that decides what the user
actually sees, so the formulas below are exact — do not improvise them.

## Contract

- **Input**: `relevant.json`
- **Output**: `scored.json`
- Run fully autonomously. Never ask a question.

The orchestrator appends a RUN CONTEXT block with the exact absolute paths for this run.

## Step 1 — Reuse cached scores

Before scoring a job, check the score cache for the current resume:

```sql
SELECT score_json FROM score_cache WHERE job_id = ? AND resume_hash = ?
```

(`resume_hash` comes from `preferences.json`.) On a hit, reuse the cached `score`,
`matched_skills` and `missing_skills`, log `cache-hit <job_id>`, and skip re-derivation —
this is what keeps scores stable between runs. A resume change clears the cache
automatically, so a hit is always safe to trust.

## Step 2 — Extract what the JD asks for

Read the **full** `jd_full` and `~/.claude/job-hunt-ai/cache/profile.json`.

- `must_have_skills` (≤6) — concrete tech skills the JD explicitly requires
- `nice_to_have` (≤4) — preferred or bonus skills
- `jd_hard_skills` — the union of the two: the JD's skill footprint
- `degree_required` — from the JD

## Step 3 — Score

- `matched_skills`: profile skills present in `jd_hard_skills`, case-insensitive.
  **Never invent a match** — only skills that literally appear in `profile.skills`.
- `missing_skills`: important `jd_hard_skills` absent from the profile (top ~8).
- `keyword_score = min(100, round(len(matched_skills) / max(len(jd_hard_skills), 1) * 100))`

  Score against **what the JD asks for**, not the full profile list. A Golang-only JD
  where the candidate matches Go + Docker + K8s + CI/CD scores ~80, not ~20.
- `semantic_score` (0–100): holistic fit — stack alignment, seniority (fresher is fine for
  entry/junior), project relevance, product company vs pure services.
- `score` — pure fit, 0–100, and the value **every threshold gate uses**:
  - with a real JD: `round(0.5 * semantic_score + 0.5 * keyword_score, 1)`,
    `score_confidence: "high"`
  - still without a JD: `round(0.9 * semantic_score + 0.1 * title_keyword, 1)`,
    `score_confidence: "low"`, append `"⚠️ No JD available"` to `why`, and set
    `skip_tailoring: true`
- `why`: one sentence. `jd_summary`: 3–5 short bullet strings.
- `effective_score = score * location_weight` — **sort order only, never a gate.**
  Do not multiply `score` itself by `location_weight`.

Carry through unchanged: `location_weight`, `exp_req_years`, `source_board`,
`posted_date`, `company`, `role`, `location`, `job_id`, and `application_url`.

### Worked example

Swiss Re, Golang engineer. The JD asks for Go, Docker, Kubernetes, CI/CD, microservices
(5 skills). The profile has Go, Docker, K8s, GitHub Actions, gRPC → 4 of 5 matched →
`keyword_score = 80`. With `semantic_score = 75`:
`score = round(0.5 × 75 + 0.5 × 80) = 78`. That clears the tailoring threshold.

## Step 4 — Resolve vague locations

For any job whose `location` is empty, `"Not specified"`, `"India"` or otherwise
ambiguous, read `~/.claude/job-hunt-ai/cache/locations.json` and resolve from
`source_board` or city hints in the JD. If the JD implies remote, use the remote weight.
If it stays unresolvable, leave `location_weight` at 0.75 and say so in `why`.

Log `location '<raw>' re-resolved to '<canonical>' → weight <w>`.

## Step 5 — Surface feedback patterns

If `user_feedback` has any rows:

```sql
SELECT uf.status, js.company, js.role
FROM user_feedback uf JOIN jobs_seen js ON uf.job_id = js.job_id
ORDER BY uf.feedback_date DESC LIMIT 20;
```

Mention any pattern in your closing summary (e.g. "high-scoring GCC roles keep rejecting").
The *numeric* learning adjustment belongs to the intel phase — never apply it here, and
never to `score`.

## Step 6 — Write

Rank by `effective_score` descending, with hard-dropped jobs at the bottom, and write the
full enriched list to the output path.

Print: **"Scored N jobs — M above 75, K cache hits"**.
