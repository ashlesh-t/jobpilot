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

## Step F — Claude reads and verifies the resume → profile.json

**Run this step if** `profile.json` does not exist, or `profile_verified` is `false` (including
after a resume-hash change), or the user explicitly asks to re-read the resume. Otherwise reuse
the cached profile.

1. Read `/tmp/jobpilot_resume_raw.txt` (written by `resume_parser.py` in step E).
2. Read the existing `~/.claude/job-hunt-ai/cache/profile.json` (to compare/correct, not blindly reuse).
3. Carefully extract: full name, email, **all** technical skills, roles held (title, company,
   duration), projects (name, stack, 1-line description), education (degree, college, year),
   publications, and `experience_years` (0 for a student/intern-only fresher). Also extract:
   - `github_url` — any `github.com/...` link in the resume text (else `""`, do not invent).
   - `portfolio_url` — a personal site/domain if present (else `""`).
   - `graduation_date` — e.g. `"July 2026"` (from the education section).
4. **Ask the user to clarify** anything genuinely missing or ambiguous (e.g. empty projects,
   unclear company names). Do not ask about details already clearly readable.
5. Write the complete `~/.claude/job-hunt-ai/cache/profile.json`, including these fields:
   ```json
   {
     "name": "...", "email": "...", "skills": ["..."], "experience_years": 0,
     "roles_held": [{"title": "...", "company": "...", "duration": "..."}],
     "projects": [{"name": "...", "stack": ["..."], "description": "..."}],
     "education": {"degree": "...", "college": "...", "year": "..."},
     "publications": [],
     "graduation_date": "July 2026",
     "github_url": "", "portfolio_url": "",
     "locations": [],
     "availability": "",
     "notice_period_days": 0,
     "profile_verified": true,
     "hash": "<resume_hash from preferences.json>"
   }
   ```
6. After the preferences questionnaire, set `profile.locations`/`availability`/`notice_period_days`
   to match the answers, and **warn** if `profile.locations` and `preferences.locations` diverge.
7. Print: *"Profile captured: <name>, <N> skills, <N> projects, graduating <year>. Verified ✓"*

---

## Preferences questionnaire

Check for `~/.claude/job-hunt-ai/options/preferences.json`:
- **Always read the file first** (even when starting fresh) before writing it — the Write tool
  requires a prior Read. If it does not exist, read `config/preferences.example.json` as the
  starting template.
- If `preferences.json` exists, ask: **"Edit existing or start fresh?"** If "edit", preserve
  current values as defaults and only overwrite what the user changes. If "fresh", start from
  `config/preferences.example.json`.

Ask these questions **one batch at a time** using the AskUserQuestion tool. Each question may
have **at most 4 explicit options** (the tool auto-adds "Other" for free-text, giving 5 total).

**Batch 1 — Location & market**

- **Preferred work locations** — multi-select, max 4 options:
  Bengaluru / Remote / Hyderabad / Mumbai
  (user types other cities via "Other"). Store as `locations`; set `remote_ok: true` if Remote chosen.

- **Location priority order** — if more than one location was selected, show the list numbered
  and ask the user to rank them (1 = most preferred). Reorder and store as `location_priority`.
  If only one location was selected, set `location_priority` equal to `locations` and skip this question.

- **Job market focus** — single-select, max 3 options:
  - Both — India boards (Naukri/Cutshort/Internshala) + global remote boards
  - India-first — prioritise Indian boards; skip US-timezone remote boards
  - Global remote — focus on global remote boards only
  Store as `job_market_focus` (`both` | `india` | `global`). Default `india`.

**Batch 2 — Role & experience**

- **Role types** — multi-select, max 4 options:
  SWE / Backend / Full Stack / ML-AI
  (user types DevOps, Data Engineering etc. via "Other"). Store as `role_types`.

- **Experience range** — single-select, max 3 options:
  - 0–1 yr fresher — `experience_years = 0`; no hard CTC filter
  - 1–2 yr — `experience_years = 1`
  - 2–3 yr — `experience_years = 2`
  Store the lower bound as integer `experience_years`.

**Batch 3a — CTC, Availability, Degree, Tailoring Threshold** (one AskUserQuestion call, up to 4 questions)

Use the AskUserQuestion tool with these four questions together:

- **"What is your minimum target CTC?"**
  Header: `Min CTC`
  Options: `< 3 LPA`, `3–6 LPA`, `6–10 LPA`, `10+ LPA`
  (+ Other for exact figure). Parse the integer from the answer and store as `target_ctc_min_lpa`.
  Note: for freshers (`experience_years == 0`) CTC is not a hard filter — it's used for scoring reference only.

- **"When can you start? (availability)"**
  Header: `Availability`
  Options: `Immediately`, `After 1 month`, `After 2–3 months`, `After graduation`
  (+ Other for custom date). Store as `availability_date`; set `notice_period_days` (0 for immediately/fresher).

- **"What degree are you pursuing or did you complete?"**
  Header: `Degree`
  Options: `B.Tech / B.E. (graduating 2026)`, `B.Tech / B.E. (already graduated)`, `M.Tech / M.E.`, `BCA / MCA / B.Sc`
  (+ Other — user types exact degree + graduation year, e.g. "B.Tech CS, May 2026").
  Store as `degree` and parse `graduation` from the answer.

- **"Resume tailoring threshold — jobs at or above this score get a tailored resume"**
  Header: `Tailor Score`
  Options: `55 — cast wide net`, `65 — balanced (default)`, `75 — selective`, `85 — top matches only`
  (+ Other for custom number). Store as `score_threshold` (integer, default 65).

**Batch 3b — Preferred stack and profile URLs** (one AskUserQuestion call, 3 questions)

- **"Preferred tech stack? (optional — will be inferred from resume if skipped)"**
  Header: `Tech Stack`
  multiSelect: true
  Options: `Python / ML / Data Science`, `Java / Spring / Microservices`, `JavaScript / Node / React`, `Skip — infer from resume`
  (+ Other to type custom stack). Store as `preferred_stack`; empty string if skipped.
  Also used as Cutshort skill filters when Apify is available.

- **"LinkedIn profile URL? (optional — paste yours via Other)"**
  Header: `LinkedIn URL`
  Options: `Skip (optional)`, `linkedin.com/in/username — type yours via Other`
  User selects "Other" to type their actual URL. Store as `linkedin_profile_url`.

- **"Naukri profile URL? (optional — paste yours via Other)"**
  Header: `Naukri URL`
  Options: `Skip (optional)`, `naukri.com/mnjuser/profile — type yours via Other`
  Used for reference only — never auto-logged-in. Store as `naukri_profile_url`.

After collecting all answers, **read `profile.json` before writing it** to mirror `locations`,
`availability_date`, and `notice_period_days` into it (per step F.6), and warn if profile vs
preference locations diverge.

---

## Step F2 — Generate canonical locations cache

After writing `preferences.json`, generate `~/.claude/job-hunt-ai/cache/locations.json` using
your knowledge of city spellings, aliases, and regional variations. This cache is the
authoritative source for location matching in every `/job-search` run.

**Weight assignment from priority_rank:**
- rank 0 (most preferred): weight 1.0
- rank 1: weight 0.85
- rank 2+: weight 0.7
- "remote" (any rank): weight 0.85

**Alias expansion rules** — for each city in `location_priority`, expand to include:
- Common alternate spellings (Bengaluru ↔ Bangalore, Gurugram ↔ Gurgaon)
- Official/historic names (Mumbai ↔ Bombay, Chennai ↔ Madras, Kolkata ↔ Calcutta)
- Airport/postal codes (BLR, DEL, BOM, MAA, HYD)
- Metro-area names (Navi Mumbai, Thane, PCMC, Noida, Greater Noida, NCR)
- Common short forms (Hyd, Pune, Blr)
- Remote aliases: "work from home", "wfh", "anywhere", "pan india", "pan-india"

**Format:**
```json
{
  "canonical": {
    "bengaluru": {
      "aliases": ["bangalore", "blr", "bengaluru urban", "electronic city"],
      "priority_rank": 0,
      "weight": 1.0
    },
    "remote": {
      "aliases": ["work from home", "wfh", "anywhere", "pan india", "pan-india"],
      "priority_rank": 1,
      "weight": 0.85
    }
  }
}
```

**Idempotency:** if `locations.json` already exists, read it first. Only overwrite entries
whose city appears in the current `location_priority` — do not remove cities added by a
previous setup run unless they are no longer in preferences.

Write the file using the Write tool. Print:
> "Location cache written: N cities, K total aliases."

---

## Step G — Telegram Channel Scraper (optional)

Telegram channel scraping provides free India job leads from curated public channels.
It requires a personal Telegram API key (separate from the bot token used for notifications).

**Skip this step if the user declines** — it is entirely optional. Native scraping works fine without it.

### G1 — Check if already configured

If `~/.claude/job-hunt-ai/cache/telegram.session` exists, use AskUserQuestion:
- Question: "Telegram channel scraper is already authenticated. Skip this step?"
- Header: `Telegram Auth`
- Options: `Yes — skip, already set up`, `No — re-authenticate`

If user picks "Yes" → skip to Confirmation summary.

### G2 — Explain and get consent

Use AskUserQuestion:
- Question: "The Telegram channel scraper reads recent job posts from public Indian job channels (e.g. @techjobsindia, @bengalurujobs) via the Telegram API — no bots. It requires a personal API key from my.telegram.org. Your account is only used to READ public channels — nothing is posted on your behalf. Set this up?"
- Header: `Telegram Scraper`
- Options: `Yes — set it up`, `No — skip this step`

If user picks "No" → skip.

### G3 — Collect API credentials

Output the following instructions as plain chat text (not in AskUserQuestion — the user needs to copy commands):

> **Never paste your API credentials into this chat** — they stay on your machine only.
>
> **Step 1 — Get your credentials:**
> 1. Go to **https://my.telegram.org** and log in with your phone number
> 2. Click **API Development Tools**
> 3. Create an app if you don't have one (any name e.g. "JobPilot", platform "Other")
> 4. Copy your **App api_id** (a number) and **App api_hash** (a 32-char hex string)
>
> **Step 2 — Save them locally by running the command for your OS:**
>
> **Linux / macOS** — run in Terminal:
> ```bash
> cd ~/my_works/jobpilot && python3 -c "
> import sys; sys.path.insert(0, 'scripts')
> from secrets import set_secret
> set_secret('TELEGRAM_API_ID', '<YOUR_API_ID>')
> set_secret('TELEGRAM_API_HASH', '<YOUR_API_HASH>')
> print('Secrets saved.')
> "
> ```
>
> **Windows** — run in Command Prompt or PowerShell:
> ```bat
> cd %USERPROFILE%\my_works\jobpilot && python -c "import sys; sys.path.insert(0, 'scripts'); from secrets import set_secret; set_secret('TELEGRAM_API_ID', '<YOUR_API_ID>'); set_secret('TELEGRAM_API_HASH', '<YOUR_API_HASH>'); print('Secrets saved.')"
> ```
>
> Replace `<YOUR_API_ID>` with the number and `<YOUR_API_HASH>` with the hex string from my.telegram.org.

Then use AskUserQuestion to wait for confirmation:
- Question: "Have you saved your Telegram API credentials? (Did you see 'Secrets saved.' in your terminal?)"
- Header: `Credentials Saved`
- Options: `Yes — I saw "Secrets saved." — continue`, `I need help / something went wrong`

If user picks "I need help":
- Print: "Check that you replaced both placeholders with your real values from my.telegram.org. The API ID is a number (e.g. 12345678) and the API hash is a 32-character hex string. Re-run the command and look for 'Secrets saved.'"
- Use AskUserQuestion again with the same two options to re-confirm before proceeding to G4.

### G4 — Authenticate (interactive)

The `--auth` script requires real interactive terminal input (phone number + OTP). **Do NOT run it via the Bash tool** — it will hang. Instead, output this message to the user:

> Run this command **directly in your terminal** (or prefix with `!` in this chat to run it in the session):
>
> ```bash
> cd ~/my_works/jobpilot && python3 scripts/scrapers/telegram_channels.py --auth
> ```
>
> It will ask for your phone number (with country code, e.g. +91...) and then the OTP that Telegram sends you.
> When it prints **"Authenticated as: Your Name (@username)"**, come back here.

Then use AskUserQuestion to wait for the result:
- Question: "Did the Telegram authentication succeed?"
- Header: `Telegram Auth`
- Options: `Yes — session saved, continue`, `It failed / I got an error`, `Skip — I'll set this up later`

If user picks "It failed":
- Print: "Common fixes: (1) Make sure TELEGRAM_API_ID and TELEGRAM_API_HASH are set correctly — re-run the G3 command to overwrite them. (2) Ensure telethon is installed: `pip install telethon`. (3) Check your phone number includes the country code, e.g. +91."
- Use AskUserQuestion again with the same three options.

If user picks "Skip" → proceed to Confirmation summary without channel discovery.

### G5 — Discover and validate Telegram channels

Run channel discovery immediately after successful authentication:

```bash
cd ~/my_works/jobpilot && python3 scripts/scrapers/telegram_channels.py --discover
```

This validates the built-in seed list against the live Telegram network, searches for additional active Indian job channels, and rewrites `config/telegram_channels.json` with only live, accessible channels.

Read the output and show the user:
> "Channel validation complete: **N live channels saved** (M dead removed, K newly discovered)."

If the script prints an error or exits non-zero, log the error and skip — the existing `config/telegram_channels.json` remains unchanged.

After completion (or skip), confirm:
> "Telegram channel scraper ready. Live channels will be scraped on every `/job-search` run."

---

## Confirmation summary

Print a tidy summary of every stored preference (including `job_market_focus`, `availability_date`,
`score_threshold`) plus the verified profile highlights (name, skills count, projects count,
graduation year, github/portfolio if found) so the user can verify everything looks right.

---

## Notes
- Never invoke any scraping here — this skill is configuration only.
- If `resume_parser.py` fails (corrupt PDF, unreadable), print the error and ask the user to
  upload a different PDF to the `jobpilot-resume` folder, then re-run `/job-setup`.
- `profile_verified: true` is the contract that profile.json is complete and Claude-reviewed.
  The `/job-search` skill checks this flag and triggers inline re-verification if false.
- **AskUserQuestion hard limit:** each question may have at most 4 explicit options. The tool
  always appends "Other" automatically, giving users a free-text escape hatch.
- **Write rule:** always Read a file before Writing it, even when creating it fresh. Read the
  existing file (or the example template if it doesn't exist) before every Write call.
