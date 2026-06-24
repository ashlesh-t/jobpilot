---
name: resume-validate
description: Internal scoring skill used by /job-search (not called directly by the user). Given a JD dict and profile.json, returns a weighted match score (60% semantic + 40% keyword) plus matched/missing keywords and concrete resume suggestions.
---

# resume-validate (internal)

Score a single job description against the user's parsed resume profile. This skill is invoked
by `/job-search`; users do not call it directly. The reference implementation lives in
`scripts/ats_scorer.py`.

## Inputs
- A JD dict (must include `job_id`, `jd_full`, `role`, `company`).
- `~/.claude/job-hunt-ai/cache/profile.json` (parsed resume).

## Output — a score JSON with exactly these keys
- `score` — 0–100, weighted **60% semantic + 40% keyword**.
- `keyword_score` — 0–100. `(matched_keywords / total_jd_keywords) * 100`.
- `semantic_score` — 0–100. `cosine_similarity(embed(jd_full), embed(resume_text)) * 100`.
- `matched_keywords` — list of profile skills/terms present in the JD.
- `missing_keywords` — important JD terms absent from the resume.
- `suggested_additions` — specific phrases the user could add to the resume to close gaps.
- `why` — one-sentence, human-readable explanation of the score.

## Method
Use `sentence-transformers` with the small local model `all-MiniLM-L6-v2` for the semantic
component. Keyword matching is case-insensitive over the JD text. Cache each result in the
SQLite `score_cache` table keyed on `(job_id, resume_hash)` so re-runs are free.
