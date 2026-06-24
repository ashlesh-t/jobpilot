---
name: jobpilot-clear
description: Reset JobPilot history. Invoke for /jobpilot-clear. Requires explicit CONFIRM, then deletes cached job IDs, the score cache, and generated reports. Preferences and resume are preserved.
---

# /jobpilot-clear

Wipe JobPilot's run history so previously seen jobs can resurface. Keeps preferences and resume.

## Steps

1. **Require explicit confirmation.** Print exactly:
   > This will delete all cached job IDs and reports. Your preferences and resume are kept.
   > Type CONFIRM to proceed.
   Do nothing unless the user replies with `CONFIRM`.

2. **On CONFIRM**, run via bash against `~/.claude/job-hunt-ai/cache/jobs.sqlite`:
   ```bash
   sqlite3 ~/.claude/job-hunt-ai/cache/jobs.sqlite "DELETE FROM jobs_seen; DELETE FROM score_cache;"
   rm -rf ~/.claude/job-hunt-ai/reports/*
   ```

3. **Confirm** what was cleared: number of job rows removed, score-cache rows removed, and that
   the reports directory is now empty. Reassure the user that `preferences.json`, `profile.json`,
   and everything under `resumes/` were left untouched.

## Notes
- This does NOT touch `resumes/tailored/` — only `reports/`. Mention this if the user expected
  tailored PDFs to be deleted too.
