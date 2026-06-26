---
name: job-setup
description: One-time JobPilot configuration wizard. Invoke for /job-setup. Runs pre-flight checks (secrets, Google Drive MCP, jobpilot-resume folder), lets user pick their resume PDF from Drive, extracts raw text, then Claude reads and understands the resume interactively to build a complete profile.json. Finally collects job preferences into preferences.json.
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
3. Run via bash:
   ```bash
   python3 scripts/resume_parser.py ~/.claude/job-hunt-ai/resumes/base.pdf --drive-file-id <file_id>
   ```
   This writes:
   - `/tmp/jobpilot_resume_raw.txt` — raw extracted text for Claude to read
   - Updates `resume_hash`, `resume_path`, `resume_drive_file_id` in `preferences.json`
   - Resets `profile_verified: false` in `profile.json` if the resume hash changed

4. Confirm `preferences.json` now contains `resume_drive_file_id` matching the chosen PDF's
   Drive file ID.

**On re-runs:** if `resume_drive_file_id` already matches the current PDF, the hash has not
changed, AND `profile.json` has `profile_verified: true`, skip steps E and F entirely and
reuse the cached profile.

---

## Step F: Claude reads and understands the resume

**Run this step if:** `profile.json` does not exist, OR `profile_verified == false` (including
after a hash change), OR the user explicitly asks to re-read the resume.

1. Read `/tmp/jobpilot_resume_raw.txt` (written by resume_parser.py in step E).
2. Read `~/.claude/job-hunt-ai/cache/profile.json` if it exists (to see any previously stored
   data to compare and correct, not to blindly reuse it).
3. **Carefully read and understand the resume.** Extract:
   - Full name and email address
   - All technical skills: programming languages, frameworks, tools, platforms, databases,
     cloud services, DevOps tools, ML/AI tools — be thorough, include everything visible
   - All roles held: job title, company name, duration (e.g. "Backend Intern at XYZ, Jun–Aug 2024")
   - All projects: name, tech stack used, 1–2 line description of what it does
   - Education: degree name (e.g. "B.Tech Computer Science"), college name, graduation year
   - Publications or open-source contributions if any
   - Estimated experience years (0 for fresher/student with only internships)
4. **Ask the user to clarify anything unclear or missing.** Examples of when to ask:
   - Company names for internships are missing or ambiguous
   - Projects section is empty or vague — "Can you briefly describe your key projects and tech stack?"
   - Graduation year is unclear
   - Skills list looks short — "I found X, Y, Z — are there other technologies you want included?"
   - Do NOT ask about things clearly readable in the text.
5. Once all information is confirmed, write `~/.claude/job-hunt-ai/cache/profile.json`:
   ```json
   {
     "name": "Full Name",
     "email": "email@example.com",
     "skills": ["python", "java", "spring boot", "docker", "..."],
     "experience_years": 0,
     "roles_held": [
       {"title": "Backend Intern", "company": "XYZ Corp", "duration": "Jun–Aug 2024"}
     ],
     "projects": [
       {
         "name": "Project Name",
         "stack": ["python", "fastapi", "postgresql"],
         "description": "Brief description of what it does"
       }
     ],
     "education": {
       "degree": "B.Tech Computer Science",
       "college": "College Name",
       "year": "2026"
     },
     "publications": [],
     "profile_verified": true,
     "hash": "<value from preferences.json resume_hash>"
   }
   ```
6. Print a confirmation:
   > "Profile captured: **<name>**, **<N> skills**, **<N> projects**, graduating **<year>**.
   > Profile saved and verified ✓"

---

## Preferences questionnaire

Check for `~/.claude/job-hunt-ai/options/preferences.json`:
- If it exists, ask: **"Edit existing or start fresh?"** If "edit", preserve current values
  as defaults and only overwrite what the user changes. If "fresh", start from
  `config/preferences.example.json`.

Ask these questions in order and record every answer into `preferences.json`.
Use the AskUserQuestion tool with multi-select where noted.

- **Preferred work locations** — options: Bengaluru / Remote / Hyderabad / Mumbai / Pune /
  Other. Multi-select; allow custom typed values. Store as `locations` (set `remote_ok: true`
  if Remote chosen).

- **Location priority order** — if more than one location was selected, show the list numbered
  and ask the user to rank them (1 = most preferred). Reorder and store as `location_priority`.
  Higher priority locations are searched at full volume; lower at half volume.
  If only one location was selected, set `location_priority` equal to `locations` and skip.

- **Minimum target CTC in LPA** — a number. Store as `target_ctc_min_lpa`. Note: for freshers
  (`experience_years == 0`) the pipeline does not hard-filter on CTC since most fresher JDs
  don't state a salary — this value is used for reference in scoring only.

- **Role types** — options: SWE / Backend / Full Stack / ML-AI / DevOps-Infra /
  Data Engineering / Other. Multi-select + free text. Store as `role_types`.

- **Experience range** — options: 0–1 yr fresher / 1–2 yr / 2–3 yr / Other (free text).
  Store the lower bound as integer `experience_years`.

- **Degree and expected/completed graduation** — e.g. "B.Tech CS, July 2026". Store as
  `degree` and `graduation`.

- **Preferred tech stack** — optional; user may skip (will be inferred from profile). Store
  as `preferred_stack`.

---

## Confirmation summary

Print a tidy summary of every stored preference plus the profile highlights
(name, skills count, projects count, experience years) so the user can verify everything.

---

## Notes
- Never invoke any scraping here — this skill is configuration only.
- If `resume_parser.py` fails (corrupt PDF, unreadable), print the error and ask the user to
  upload a different PDF to the `jobpilot-resume` folder, then re-run `/job-setup`.
- `profile_verified: true` is the contract that profile.json is complete and Claude-reviewed.
  The `/job-search` skill checks this flag and triggers inline re-verification if false.
