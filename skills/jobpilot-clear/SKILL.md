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

2. **On CONFIRM**, run:
   ```bash
   python3 scripts/jobpilot_clear.py
   ```
   This clears only the current account's own history — this account's cached scores
   (`JobUserScore` rows, so previously seen jobs can be rescored), feedback rows, this
   account's generated reports, and this account's `learning.json` (History reset must
   also reset learned ranking bias — it derives from the deleted feedback rows).
   `company_intel.json` is kept: it's public research shared across every account on
   this instance, not personal history. It prints a JSON summary:
   `{"scores_removed": N, "feedback_removed": N, "reports_removed": N, "learning_reset": true|false}`.

3. **Confirm** what was cleared, from that JSON: number of job scores removed, feedback
   rows removed, and that the reports directory is now empty. Reassure the user that
   `preferences.json`, `profile.json`, and everything under `resumes/` were left untouched.

## Notes
- This does NOT touch `resumes/tailored/` — only `reports/`. Mention this if the user expected
  tailored PDFs to be deleted too.
