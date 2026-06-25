---
name: job-setup
description: One-time JobPilot configuration wizard. Invoke for /job-setup. Runs pre-flight checks (secrets, Google Drive MCP, jobpilot-resume folder), lets user pick their resume PDF from Drive, parses it, then collects job preferences into preferences.json.
---

# /job-setup

Configure JobPilot for the user. Run this once at install, or whenever criteria change.
**Stop at the first failing pre-flight check** and print a single clear fix instruction.

---

## Pre-flight checks

### A. Secrets check
Run via bash:
```bash
python3 scripts/secrets.py APIFY_TOKEN TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID
```
If any key prints `MISSING`:
> "Some required secrets are not set. Run `./setup.sh` from the jobpilot directory
> to fill them in, then re-run `/job-setup`."

Stop. Do not continue.

### B. Google Drive MCP check
Try to list files in Google Drive using the Google Drive MCP tool. If the MCP tool is
unavailable or returns an auth error:
> "Google Drive is not connected.
> Go to **Claude Desktop → Settings → Connections** and connect your Google Drive,
> then re-run `/job-setup`."

Stop. Do not continue.

### C. jobpilot-resume folder check
Search Google Drive for a folder named exactly **`jobpilot-resume`**.

If not found:
> "The `jobpilot-resume` folder does not exist in your Google Drive.
> Please create it, upload your resume as a PDF file, then re-run `/job-setup`."

Stop. Do not continue.

---

## Resume selection

### D. List PDFs in jobpilot-resume
List all files with MIME type `application/pdf` inside the `jobpilot-resume` folder.

**0 PDFs found:**
> "No PDF found in `jobpilot-resume`. Upload your resume as a PDF file to that
> folder in Google Drive, then re-run `/job-setup`."
Stop.

**1 PDF found:**
> "Found: **<filename>**. Use this as your resume? [Y/n]"
- Y → proceed to step E.
- N → "Upload the correct PDF to the `jobpilot-resume` folder and re-run `/job-setup`." Stop.

**2 or more PDFs found:**
Show a numbered list, e.g.:
```
  1. resume_2025.pdf
  2. resume_backend.pdf
  3. cv_latest.pdf
```
> "Which resume should JobPilot use? Enter a number."
Use the chosen file.

### E. Download and cache resume
1. Download the selected PDF from Google Drive via the MCP tool.
2. Write the file contents to: `~/.claude/job-hunt-ai/resumes/base.pdf`
3. Parse it via bash:
   ```bash
   python3 scripts/resume_parser.py ~/.claude/job-hunt-ai/resumes/base.pdf
   ```
   Pass `--drive-file-id <file_id>` to also persist the Drive file ID:
   ```bash
   python3 scripts/resume_parser.py ~/.claude/job-hunt-ai/resumes/base.pdf --drive-file-id <file_id>
   ```
   This writes `~/.claude/job-hunt-ai/cache/profile.json` and updates `resume_hash`,
   `resume_path`, and `resume_drive_file_id` in `preferences.json`.
4. Confirm `preferences.json` now contains `resume_drive_file_id` matching the chosen PDF's
   Drive file ID. Future runs use this to skip re-download when the file hasn't changed.

On re-runs: if `resume_drive_file_id` already matches the current PDF in the folder and the
hash has not changed, skip the download and reuse the cached `base.pdf`.

---

## Preferences questionnaire

Check for `~/.claude/job-hunt-ai/options/preferences.json`:
- If it exists, ask: **"Edit existing or start fresh?"** If "edit", preserve current values
  as defaults and only overwrite what the user changes. If "fresh", start from
  `config/preferences.example.json`.

Ask these questions in order and record every answer into `preferences.json`.
Use the AskUserQuestion tool with multi-select where noted.

- **Preferred work locations** — options: Bengaluru / Remote / Hyderabad / Mumbai / Pune /
  Other. Multi-select; allow custom typed values. Store as `locations` (and set `remote_ok`
  true if Remote chosen).

- **Location priority order** — if more than one location was selected, show the list
  numbered (e.g. `1. Bengaluru  2. Remote  3. Hyderabad`) and ask:
  > "Rank these by priority — 1 = most preferred (gets the most job suggestions).
  > Enter numbers in order, e.g. '2 1 3'."
  Reorder the list accordingly and store as `location_priority` in `preferences.json`.
  If only one location was selected, set `location_priority` equal to `locations` and skip.
  Higher priority locations are searched at full volume; lower priority at half volume.
- **Minimum target CTC in LPA** — a number. This is the CTC floor. Store as
  `target_ctc_min_lpa`.
- **Role types** — options: SWE / Backend / Full Stack / ML-AI / DevOps-Infra /
  Data Engineering / Other. Multi-select + free text. Store as `role_types`.
- **Experience range** — options: 0–1 yr fresher / 1–2 yr / 2–3 yr / Other (free text).
  Store the lower bound as integer `experience_years`.
- **Degree and expected/completed graduation** — e.g. "B.Tech CS, July 2026". Store as
  `degree` and `graduation`.
- **Preferred tech stack** — optional; user may skip (will be inferred from resume). Store as
  `preferred_stack`.

---

## Confirmation summary

Print a tidy summary of every stored preference plus the parsed profile highlights
(name, skills count, experience years detected) so the user can verify everything looks right.

---

## Notes
- Never invoke any scraping here — this skill is configuration only.
- If `resume_parser.py` fails (corrupt PDF, unreadable), print the error and ask the user to
  upload a different PDF to the `jobpilot-resume` folder, then re-run `/job-setup`.
