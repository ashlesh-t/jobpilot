# Getting Started with JobPilot

A complete, beginner-friendly walkthrough. If you've never used Apify or a Telegram bot
before, follow this top to bottom and you'll have JobPilot running in ~15 minutes.

---

## 0. What you'll end up with

A scheduled task that, once a day, quietly scrapes multiple job sources, has Claude score
each posting against your resume with real judgment, and sends you a Telegram message with
your top matches plus a CSV. You do nothing day-to-day except read Telegram.

---

## 1. Install the prerequisites

| Tool | Why | How to get it |
|---|---|---|
| **Python 3.11+** | Runs the pipeline | https://www.python.org/downloads/ — verify with `python3 --version` |
| **sqlite3** | Local job cache | Usually preinstalled. macOS: built in. Ubuntu: `sudo apt install sqlite3`. Windows: ships with Python |
| **Claude Desktop (Pro)** | Runs the scheduled task and skills | The scheduled run uses your Pro subscription |
| **tectonic** *(optional)* | Compiles LaTeX resumes to PDF | macOS: `brew install tectonic`. Else see https://tectonic-typesetting.github.io. Skip it if you only use `.docx` resumes |

You also need two free accounts: **Apify** and a **Telegram bot**. Steps 3 and 4 cover those.

---

## 2. Get the code and run setup

```bash
# put the repo here
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/ashlesh-t/jobpilot
cd jobpilot

# one-time setup: creates ~/.claude/job-hunt-ai/, installs deps, inits the database, syncs slash commands
chmod +x setup.sh
./setup.sh
```

`setup.sh` creates your **data directory** at `~/.claude/job-hunt-ai/` (kept separate from the
code), installs Python dependencies, and syncs the slash commands to `.claude/commands/`. Re-run
`./setup.sh` anytime you pull an update — it's idempotent.

---

## 2b. (Recommended) Connect Apify MCP to Claude Desktop

This lets Claude call Apify actors directly as tools — no Python HTTP code involved, and no
API token stored in config files. Auth is handled via OAuth in your browser.

**Option A — Claude Desktop:**
1. Open Claude Desktop → **Settings → Connections**
2. Click **Add remote MCP server**
3. Enter URL: `https://mcp.apify.com/sse`
4. Complete OAuth in the browser (sign in with your Apify account)

**Option B — Claude Code CLI:**
```bash
claude mcp add --transport sse apify https://mcp.apify.com/sse
```

When connected, `/job-search` will call Apify actors directly through the MCP. If the MCP is
not connected (e.g. during a scheduled task), the pipeline falls back to the `apify-client`
Python SDK automatically — nothing breaks.

> **Note:** The Apify MCP uses your Apify account's credit balance. The free tier (~$5/month)
> covers about one run per day whether you use MCP or the SDK.

---

## 3. Get your Apify token (required for SDK fallback)

Apify is the service that does the actual scraping. The free tier (~$5 credit/month) covers
about one run per day.

1. Sign up free at **https://console.apify.com**.
2. Go to **Settings → Integrations** (direct link: https://console.apify.com/account/integrations).
3. Copy your **Personal API token**.
4. Paste it when `setup.sh` asks for your Apify token.

> **Note:** Even without an Apify token, JobPilot will still fetch free sources — Remote OK,
> We Work Remotely, and HN "Who is Hiring" — at no cost. The Apify token unlocks LinkedIn,
> Indeed, Glassdoor, and Naukri.

---

## 4. Create your Telegram bot (required)

You need two things: a **bot token** and your **chat ID**.

### 4a. Bot token
1. Open Telegram and message **@BotFather** (https://t.me/BotFather).
2. Send `/newbot`, pick a name and a username ending in `bot`.
3. BotFather replies with a token like `123456789:AAH...`. That's your `TELEGRAM_BOT_TOKEN`.

### 4b. Find your chat ID
1. Send any message (e.g. "hi") to your new bot in Telegram so it has a conversation to see.
2. In a browser, open (replace `<TOKEN>` with your bot token):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Look for `"chat":{"id":123456789,...}`. That number is your `TELEGRAM_CHAT_ID`.

> Tip: if `getUpdates` is empty, message your bot again and refresh the page.

---

## 5. Fill in your secrets

`setup.sh` already did this interactively — the wizard collected your Apify token, Telegram
bot token, and chat ID, validated each one, and saved them to `~/.claude/job-hunt-ai/.env`.

To verify everything was stored:
```bash
cd ~/projects/jobpilot
python3 scripts/secrets.py
# Expect: APIFY_TOKEN: FOUND / TELEGRAM_BOT_TOKEN: FOUND / TELEGRAM_CHAT_ID: FOUND
```

To change a secret later, just re-run `./setup.sh` — it will detect existing keys and let you
update only the ones you want. Or edit `~/.claude/job-hunt-ai/.env` directly.

---

## 6. Connect Google Drive and upload your resume

JobPilot keeps your resume in Google Drive so it's never tied to a specific machine.

**a. Connect Google Drive in Claude Desktop**
Open Claude Desktop → **Settings → Connections** → connect your Google Drive account.

**b. Create the resume folder**
In Google Drive, create a folder named exactly: **`jobpilot-resume`**

**c. Upload your resume**
Upload your resume as a **PDF file** into the `jobpilot-resume` folder. Any filename is fine.
If you have multiple versions, upload all of them — `/job-setup` will let you pick.

**d. Run /job-setup inside Claude Desktop**
```
/job-setup
```

The skill will:
1. Check that your secrets are set and Google Drive is connected — and tell you exactly what's
   missing if anything is wrong.
2. Find your `jobpilot-resume` folder and list the PDFs in it.
3. If you have multiple PDFs, show a numbered list and ask which one to use.
4. Download and cache the chosen PDF, then **Claude reads and understands your resume
   interactively** — it will ask you to clarify missing details (project descriptions, company
   names for internships, graduation year) and confirm your skill set. This takes 2–3 minutes
   and produces a complete, accurate profile that drives all scoring.
5. Ask for your job preferences (locations, role types, experience level, etc.).

Your answers are saved to `~/.claude/job-hunt-ai/options/preferences.json` and your verified
resume profile to `~/.claude/job-hunt-ai/cache/profile.json` (with `profile_verified: true`).

> **Expect Claude to ask you questions.** During step 4 above, Claude reads your resume and
> may ask things like "I see internship entries but no company names — can you clarify?" or
> "Your projects section looks empty — can you briefly describe your main projects?" Answer
> these so your profile is complete. Better profile = better job scores.

You can re-run `/job-setup` anytime, or just tell Claude "raise my CTC floor to 18 and add Remote".

---

## 7. Test each piece before automating

These quick checks confirm everything works end to end:

```bash
cd ~/projects/jobpilot

# 1) Telegram works — sends "JobPilot connected ✅" to your chat
python3 scripts/telegram_notify.py --test

# 2) A real (tiny) scrape + filter dry run
python3 scripts/apify_scraper.py     # prints how many jobs were scraped from each source
python3 scripts/dedupe.py
python3 scripts/filter.py            # prints location filter breakdown

# 3) A full manual run inside Claude Desktop
/job-search
```

If `/job-search` produces a CSV in `~/.claude/job-hunt-ai/reports/` and a Telegram message
arrives, you're done.

---

## 8. (Optional) Add India-specific job sources

`config/actors.json` has slots for Naukri, Wellfound, and Cutshort Apify actors. To enable them:

1. Go to **https://apify.com/store** and search for "naukri scraper", "wellfound jobs", "cutshort".
2. Copy the actor ID (e.g. `someuser/naukri-scraper`).
3. Open `config/actors.json` and fill in the matching field:
   ```json
   "naukri_scraper": "someuser/naukri-scraper"
   ```

Remote OK and We Work Remotely are always active at no cost — no setup needed.

---

## 9. (Optional) Google Drive uploads

If you already connected Google Drive in step 6a, Drive uploads are automatic — `/job-search`
uses the Drive MCP connector to push the CSV and tailored resumes to a folder called
`JobPilot Reports` in your Drive. Nothing extra to configure.

If you skipped Drive, that's fine — you'll still get the CSV and resumes via Telegram.

---

## 10. Schedule it

In Claude Desktop: **Schedule → New Task**, set it to **09:30 IST, weekdays**, and paste:

```
Run the JobPilot job search pipeline. Load skills from ~/projects/jobpilot. Execute /job-search fully autonomously:
1. Run scripts/apify_scraper.py, dedupe.py, filter.py via bash (Layer A — no LLM)
2. Claude scores, filters, and researches salary on survivors (Layer B — no Python scripts needed)
3. Write CSV report, tailor resumes for top matches, push to Telegram and Google Drive
Do not pause for confirmation. If any script fails, log the error and continue.
```

One run per day keeps you inside Apify's free tier.

---

## 11. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Secret 'X' not found` | The value isn't in `~/.claude/job-hunt-ai/.env` or the keyring. Re-check step 5; run `python3 scripts/secrets.py`. |
| Telegram test sends nothing | Wrong `TELEGRAM_CHAT_ID`, or you never messaged the bot first (step 4b). |
| `0 raw jobs scraped` | Missing/invalid `APIFY_TOKEN`, exhausted Apify credit, or the actor IDs in `config/actors.json` changed — verify them in the Apify Store. Free sources (Remote OK, WWR) still run without a token. |
| Scores look very low | `profile_verified` is likely `false` in `profile.json` — run `/job-setup` and let Claude read your resume interactively. Scores depend on a complete profile. |
| Claude asks me questions during /job-setup | This is expected. Claude is reading your resume and clarifying missing details. Answer them for a complete profile. |
| `tectonic: command not found` | Install tectonic, or it falls back to DOCX automatically. |
| Drive upload skipped | Google Drive not connected in Claude Desktop. Go to Settings → Connections and connect it. |
| Want to re-see old jobs | Run `/jobpilot-clear` (type CONFIRM) to wipe the seen-job cache. |
| profile.json looks wrong (bad education, empty projects) | Run `/job-setup` again. Claude will re-read the resume and ask you to correct it. |

---

## Where everything lives (quick reference)

```
~/projects/jobpilot/                 # the code (this repo)
~/.claude/job-hunt-ai/               # YOUR data (not in the repo)
├── .env                             # secrets
├── options/preferences.json         # your search criteria
├── cache/jobs.sqlite                # seen-jobs cache
├── cache/profile.json               # your resume profile (Claude-verified)
├── resumes/base.pdf                 # your master resume (cached from Drive)
├── resumes/base.tex                 # LaTeX source (optional, enables PDF tailoring)
├── resumes/tailored/                # generated tailored resumes (PDF or DOCX)
└── reports/YYYY-MM-DD-<slot>.csv    # generated reports
```
