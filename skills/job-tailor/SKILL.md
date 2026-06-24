---
name: job-tailor
description: Tailor your resume to a single job and ATS-score it. Invoke for /job-tailor <job_id | JD text | URL>. Looks up or fetches the JD, edits a LaTeX or DOCX resume to match, compiles it, and reports ATS score before vs after.
---

# /job-tailor <job_id OR JD text OR URL>

Tailor the user's resume to one specific job posting.

## Steps

1. **Resolve the JD** from the argument:
   - **job_id** -> look up the cached JD from the SQLite `jobs_seen` table at
     `~/.claude/job-hunt-ai/cache/jobs.sqlite`.
   - **URL** -> fetch the page and extract the job-description text.
   - **raw text** -> use it directly.

2. **Ask:** "Do you have your LaTeX/Overleaf source for your resume? (yes/no)"
   - **Yes** -> ask the user to paste the full `.tex` content. Edit it to weave in JD keywords,
     align the objective line and skills summary, and raise keyword density in the experience
     bullets without inventing experience. Compile with `tectonic`, then save to
     `~/.claude/job-hunt-ai/resumes/tailored/<company>-<jobid>.pdf`.
   - **No** -> run:
     ```bash
     python3 scripts/resume_tailor.py <job_id> --docx
     ```
     This generates `~/.claude/job-hunt-ai/resumes/tailored/<company>-<jobid>.docx`.

3. **Re-score** the tailored version:
   ```bash
   python3 scripts/ats_scorer.py <job_id>
   ```
   (run against the tailored resume text).

4. **Report** ATS score **before vs after**, the keywords now matched, and the remaining gaps
   (missing keywords + suggested additions) so the user can decide whether to push further.

## Notes
- Never fabricate experience, employers, or dates. Tailoring = rephrasing + emphasis only.
- Honour the score threshold and per-run tailoring cap defined in `preferences.json`.
