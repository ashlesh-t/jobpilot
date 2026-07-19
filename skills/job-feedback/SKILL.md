---
name: job-feedback
description: Record outcomes for jobs you applied to (applied, rejected, interview, offer, ghosted). Invoke for /job-feedback. Lists recent applied/tailored jobs and prompts for status updates.
---

# /job-feedback

Record what happened after you applied to jobs. Keeps the feedback loop alive so
JobPilot can learn which companies and roles are realistic for your profile.

> **Repo paths:** `scripts/…` are relative to the JobPilot repo root. If the
> `CLAUDE_PLUGIN_ROOT` env var is set (installed as a plugin), prefix them with it; from a git
> clone the current directory is the root. `~/.claude/…` paths are absolute.

---

## Step 1 — Find recent jobs to tag

Run:
```bash
sqlite3 ~/.claude/job-hunt-ai/cache/jobs.sqlite "
  SELECT js.job_id, js.company, js.role, js.location, js.match_score,
         js.tailored_resume_path,
         COALESCE(uf.status, 'pending') as feedback_status
  FROM jobs_seen js
  LEFT JOIN user_feedback uf ON js.job_id = uf.job_id
  WHERE js.tailored_resume_path IS NOT NULL
     OR uf.status IS NOT NULL
  ORDER BY js.last_seen DESC
  LIMIT 20;
"
```

Show the results as a numbered list:
```
Recent jobs:
1. DataArt — Backend Engineer (Bengaluru) — score 79.2 — [pending]
2. Voiro — SDE-1 (Bengaluru) — score 68.1 — [pending]
3. VISCR AI — ML Engineer (Remote) — score 65.0 — [applied]
...
```

---

## Step 2 — Prompt for status updates

For each job with status `pending`, ask:
```
What happened with <company> — <role>?
  1) applied
  2) rejected
  3) interview
  4) offer
  5) ghosted
  6) skip (do nothing)
```

Accept the number or the word. Accept "skip" or empty input to move on.

---

## Step 3 — Record each response

For each status update, call:
```bash
python3 scripts/feedback.py <job_id> <status> [--notes "<any notes the user added>"]
```

If the user wants to add a note (e.g. "got OA round"), pass it as `--notes`.

Print confirmation after each: `Recorded: DataArt Backend Engineer → interview`

---

## Step 3b — Update learning weights

After all statuses are recorded, update `~/.claude/job-hunt-ai/cache/learning.json`
(**read it first**; if missing, start from this template):

```json
{"version": 1, "updated_at": "", "outcome_count": 0,
 "skill_weights": {}, "archetype_weights": {}, "source_weights": {}}
```

For **each newly recorded outcome** on job J:

1. Get J's signals: read `score_json` from
   `SELECT score_json FROM score_cache WHERE job_id=? ORDER BY computed_at DESC LIMIT 1;`
   → `matched_skills`, `archetype`, `source_board`. If no row exists, skip this job
   (log `learning: no score record for <job_id> — skipped`).
2. Outcome value `v`: `offer +1.0 | interview +0.6 | applied 0.0 | ghosted -0.3 | rejected -0.6`.
3. For each signal `s` (each matched skill → `skill_weights`; archetype →
   `archetype_weights`; source_board → `source_weights`), with missing keys starting at 1.0:

   ```
   w[s] = clip(w[s] + 0.05 * v, 0.7, 1.3)
   ```

4. Increment `outcome_count` by 1 per outcome; set `updated_at`.

Print each moved weight: `learning: golang 1.00 → 1.03 (interview @ Swiss Re)`.

Caps make this wreck-proof: one outcome moves any weight ≤ 0.05; weights stay in
[0.7, 1.3]; `/job-search` only *applies* them once `outcome_count >= 5`, and only to
`effective_score` (ranking) — never to `score` or a threshold gate.

---

## Step 4 — Summary

After processing all jobs:
```
Feedback recorded: 3 jobs updated
  interview: DataArt (Backend Engineer)
  rejected:  Mercedes-Benz (SDE-2)
  applied:   VISCR AI (ML Engineer)

Next /job-search will use this feedback to validate scoring accuracy.
Run /job-feedback again any time to update outcomes.
```

---

## Notes

- You can also call this skill with a specific job: `/job-feedback <job_id> <status>`
  In that case, skip straight to Step 3 for that job.
- Status values: `applied`, `rejected`, `interview`, `offer`, `ghosted`
- Feedback is stored in `user_feedback` table and cross-referenced in the next
  `/job-search` run so Claude can flag if high-scoring companies consistently reject
  and low-scoring ones give interviews.
- Outcomes also feed `cache/learning.json` (Step 3b): once ≥5 outcomes exist,
  `/job-search` nudges *ranking* (never absolute scores) toward what actually gets you
  interviews. Reset it any time with `/jobpilot-clear`.
