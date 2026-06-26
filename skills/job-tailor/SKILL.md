---
name: job-tailor
description: Tailor your resume to a single job and ATS-score it. Invoke for /job-tailor <job_id | JD text | URL>. Looks up or fetches the JD, Claude scores the fit, edits a LaTeX or DOCX resume to match, compiles it, and reports ATS score before vs after.
---

# /job-tailor <job_id OR JD text OR URL>

Tailor the user's resume to one specific job posting.

## Steps

1. **Resolve the JD** from the argument:
   - **job_id** → look up `jd_full` from `/tmp/jobpilot_filtered.json` first; if not found,
     query the SQLite `jobs_seen` table at `~/.claude/job-hunt-ai/cache/jobs.sqlite`.
   - **URL** → fetch the page with WebFetch and extract the job-description text.
   - **raw text** → use it directly.

2. **Score before tailoring** — read `~/.claude/job-hunt-ai/cache/profile.json` and the JD text.
   Compute the ATS score inline (no external script):
   - `matched_skills`: skills from `profile.skills` present in the JD
   - `missing_keywords`: top technical terms in the JD not in `profile.skills`
   - `keyword_score` = `len(matched_skills) / len(profile.skills) * 100`
   - `semantic_score` = your holistic judgment (0–100) of how well the background fits
   - `score` = `round(0.5 * semantic_score + 0.5 * keyword_score, 1)`
   Print: **"Before tailoring: score <score>/100, matched: <matched_skills>"**

3. **Tailor the resume:**

   **If `~/.claude/job-hunt-ai/resumes/base.tex` exists (or user says yes to LaTeX):**
   - If user hasn't confirmed LaTeX source, ask: "Do you want to use your LaTeX source? [Y/n]"
   - Read `base.tex` (or ask user to paste it if they prefer a custom version)
   - Edit to weave in `matched_skills` and important `missing_keywords`:
     - Update the skills/technical section to lead with JD-relevant technologies
     - Rephrase experience bullets to naturally include key terms
     - Update objective/summary line to mention the target role and company
   - Write edited `.tex` to `/tmp/<company>-<job_id>.tex`
   - Compile via bash:
     ```bash
     tectonic /tmp/<company>-<job_id>.tex --outdir ~/.claude/job-hunt-ai/resumes/tailored/
     ```
   - If tectonic fails or is not installed: save the `.tex` to `resumes/tailored/` directly
     and tell the user to compile it on Overleaf.

   **If no LaTeX source:**
   ```bash
   python3 scripts/resume_tailor.py <job_id> --matched-skills <comma-separated-matched-skills>
   ```
   This generates `~/.claude/job-hunt-ai/resumes/tailored/<company>-<jobid>.docx`.

4. **Score after tailoring** — re-read the tailored resume text (`.tex` or DOCX content)
   alongside the JD and recompute the score using the same inline method as step 2.
   Print: **"After tailoring: score <new_score>/100 (+<delta>)"**

5. **Report** the delta, the keywords now matched, and remaining gaps so the user can decide
   whether to push further. Suggest 2–3 specific additions if the score is still below 75.

## Notes
- Never fabricate experience, employers, dates, or metrics. Tailoring = rephrasing + emphasis only.
- Honour the `top_n_tailor` cap from `preferences.json` (default 5 per run).
- If `profile_verified` is false in `profile.json`, run the profile verification step from
  `/job-setup` Step F before scoring.
