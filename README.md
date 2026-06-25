# JobPilot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Automated, personal job-hunting pipeline for Claude Code.

## 1. What it does

JobPilot scrapes roughly ten job sources (LinkedIn, Indeed, Glassdoor, Google Jobs, Naukri,
plus Greenhouse / Lever / Ashby / Workday application pages and Hacker News "Who is hiring")
through Apify and free APIs, then scores every posting against your resume. The strongest
matches get a tailored resume and land in a dated CSV report. A Telegram digest of the top
picks is pushed automatically on whatever schedule you set.

## 2. Prerequisites

- **Claude Desktop Pro** (the scheduled task runs under your Pro subscription).
- **Apify account** — free tier is fine (~$5 credit/month).
- **Telegram bot** — create one with [@BotFather](https://t.me/BotFather) and grab your chat ID.
- **Python 3.11+**.
- **tectonic** (optional) — only needed to compile LaTeX resumes to PDF.

> **New here?** Follow [GETTING_STARTED.md](GETTING_STARTED.md) for a full step-by-step walkthrough — how to get your Apify token, create a Telegram bot, find your chat ID, fill in `.env`, and verify each piece before scheduling.

## 3. Install

Three paths, pick one:

**a. Plugin install (recommended)**
```bash
claude plugin install github:<YOUR_GITHUB_USERNAME>/jobpilot
```

**b. Clone + setup**
```bash
git clone https://github.com/<YOUR_GITHUB_USERNAME>/jobpilot ~/projects/jobpilot
cd ~/projects/jobpilot
./setup.sh
```

**c. Future `.mcpb` bundle** — a one-click `.mcpb` installer is planned; not yet available.

## 4. One-time setup

**a. Run `./setup.sh`** — creates `~/.claude/job-hunt-ai/`, installs Python deps, initialises
the SQLite cache, and runs an interactive wizard that collects your Apify token, Telegram bot
token, and chat ID (validates each one live before saving).

**b. Connect Google Drive** in Claude Desktop → Settings → Connections.

**c. Create a folder** named `jobpilot-resume` in your Google Drive and upload your resume
as a PDF file into it.

**d. Run `/job-setup`** in Claude Desktop. It checks that secrets and Google Drive are ready,
lets you pick your resume PDF from the Drive folder (shows a numbered list if there are
several), downloads and parses it, then asks for your job preferences (locations, CTC floor,
role types, experience, degree, optional tech stack).

Everything personal — secrets, preferences, cached resume, reports — lives in
`~/.claude/job-hunt-ai/`, never in the repo. The resume source of truth stays in Google Drive.

## 5. Daily use

Once the scheduled task is set up, you do nothing. It fires on your cadence, runs the full
pipeline, and pushes results to Telegram. Just check Telegram for the digest and the attached
CSV.

## 6. Slash command reference

| Command | What it does | When to use |
|---|---|---|
| `/job-setup` | Collect preferences + parse resume into a profile | Once, at first install, or to change criteria |
| `/job-search` | Full pipeline: scrape -> dedupe -> filter -> score -> research -> report -> tailor -> notify | Manually, or via scheduled task |
| `/job-tailor <job_id\|URL\|JD>` | Tailor resume to one job; ATS score before vs after | When you want to apply to a specific role |
| `/jobpilot-clear` | Wipe seen-job cache, score cache, and reports (keeps prefs + resume) | To reset history and re-surface old jobs |

## 7. Resume versioning

Keep your master resume as `~/.claude/job-hunt-ai/resumes/base.tex` (LaTeX) or `base.docx`.
JobPilot reads from it and writes tailored copies into `resumes/tailored/`. Use **git** as your
version control for the base resume — commit changes there and JobPilot will re-parse when the
file hash changes.

## 8. Editing preferences

Either hand-edit `~/.claude/job-hunt-ai/options/preferences.json`, or just ask Claude in
natural language (e.g. "raise my CTC floor to 18 LPA and add Remote") and it will update the
file for you.

## 9. Cost

Layer A (scraping + filtering) costs nothing in LLM tokens — it is pure Python. The only spend
is Apify usage; the free tier (~$5 credit/month) covers roughly **one run per day**. Tune
`schedule_slots_ist` to a single daily slot to stay free. LLM usage in Layer B is covered by
your Claude Pro subscription.

## 10. Contributing / marketplace listing

PRs welcome. To list in a Claude plugin marketplace, publish this repo publicly and share the
`claude plugin install github:<USERNAME>/jobpilot` one-liner. A `.mcpb` bundle and pip-installable
helper package are on the roadmap.
