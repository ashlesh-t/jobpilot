---
name: job-phase-discover
description: "JobPilot pipeline phase 4 of 11 — find jobs the scrapers missed, via company career pages and targeted web search. Invoked by the orchestrator as /job-phase-discover; not meant to be run directly."
---

# Phase: Discover extra jobs

Carved verbatim out of `/job-search` steps A4 and A5. The scrapers cover the job boards;
this phase covers the roles that only ever appear on a company's own careers page or in
a search result.

## Contract

- **Input**: `filtered.json` — the jobs that survived the hard filters.
- **Output**: `discovered.json` — *only the newly discovered* jobs, in the same canonical
  shape. Write an empty array `[]` if you find nothing; the next phase merges the two
  files, so never rewrite `filtered.json` here.
- Run fully autonomously. Never ask a question. Never run a later phase.
- Degrade gracefully: if a fetch or search fails, log it and continue. This phase is
  optional — finishing with `[]` is a perfectly good outcome.

The orchestrator appends a RUN CONTEXT block with the exact absolute paths for this run.
Use those paths, not the examples here.

## Canonical job shape

Every job you add must match what the scrapers produce, or the downstream phases will
drop it:

```json
{
  "job_id": "<sha1 of company|role|location|source_board>",
  "company": "", "role": "", "location": "",
  "experience_req": "", "jd_full": "", "application_url": "",
  "source_board": "direct-<company-slug>" | "websearch",
  "posted_date": "", "last_date": "", "has_jd": true
}
```

Compute `job_id` with the project's own helper so it matches the scrapers exactly:

```bash
python3 -c "
import sys; sys.path.insert(0, 'scripts/scrapers')
from _common import make_job_id
print(make_job_id('<company>', '<role>', '<location>', '<source_board>'))"
```

## Step 1 — Company career pages

Read `config/target_companies.json`. If `"enabled"` is not `true`, skip to step 2.

1. Keep companies matching `job_market_focus` from preferences (`india` → india/both,
   `global` → global/both, `both` → all).
2. `WebFetch` each `careers_url` and extract roles visible without JavaScript — title,
   location, apply URL. A blank body means an SPA-only page: log it and move on.
3. Keep roles whose title matches any of `role_types` (case-insensitive).
4. Set `source_board = "direct-<company_slug>"` and `has_jd: false` when there's no
   description text.
5. Cap **5 roles per company**.
6. Log `[careers] <Company>: N roles added` or `skipped — SPA-only / 0 matches`.

## Step 2 — Targeted web search

Run **at most 3 searches**, built from preferences:

```
"<role_types[0]> fresher <current year> <location_priority[0]>" (site:boards.greenhouse.io OR site:jobs.lever.co OR site:jobs.ashbyhq.com)
"<preferred_stack[0]> <role_types[0]> hiring <location_priority[0]>"
"<role_types[1]> new grad remote india apply"
```

For each credible posting, build the canonical dict with `source_board: "websearch"` and
`application_url` set to the posting page. **Cap 10 jobs total** across all searches.

Log `[websearch] N jobs added`.

## Step 3 — Deduplicate, then write

Drop any job whose `job_id` already appears in `filtered.json`, and any already recorded
as seen:

```bash
python3 -c "
import sqlite3, os
db = os.path.expanduser(os.environ.get('JOBPILOT_DIR','~/.claude/job-hunt-ai')) + '/cache/jobs.sqlite'
print([r[0] for r in sqlite3.connect(db).execute(\"SELECT job_id FROM jobs_seen WHERE status='active'\")])"
```

Write the survivors to the output path as a JSON array.

Finish with one line: **"Discovery: N from career pages, M from search → K new jobs"**.
