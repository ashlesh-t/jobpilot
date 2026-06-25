# Getting Started with JobPilot

A complete, beginner-friendly walkthrough. If you've never used Apify or a Telegram bot
before, follow this top to bottom and you'll have JobPilot running in ~15 minutes.

---

## 0. What you'll end up with

A scheduled task that, once a day, quietly scrapes ~10 job sources, scores each posting
against your resume, and sends you a Telegram message with your top matches plus a CSV. You
do nothing day-to-day except read Telegram.

---

## 1. Install the prerequisites

| Tool | Why | How to get it |
|---|---|---|
| **Python 3.11+** | Runs the pipeline | https://www.python.org/downloads/ — verify with `python3 --version` |
| **sqlite3** | Local job cache | Usually preinstalled. macOS: built in. Ubuntu: `sudo apt install sqlite3`. Windows: ships with Python |
| **Claude Desktop (Pro)** | Runs the scheduled task | The scheduled run uses your Pro subscription |
| **tectonic** *(optional)* | Compiles LaTeX resumes to PDF | macOS: `brew install tectonic`. Else see https://tectonic-typesetting.github.io. Skip it if you only use `.docx` resumes |

You also need two free accounts: **Apify** and a **Telegram bot**. Steps 3 and 4 cover those.

---

## 2. Get the code and run setup

```bash
# put the repo here
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/ASHLESHA05/jobpilot
cd jobpilot

# one-time setup: creates ~/.claude/job-hunt-ai/, installs deps, inits the database
chmod +x setup.sh
./setup.sh
```

`setup.sh` creates your **data directory** at `~/.claude/job-hunt-ai/` (kept separate from the
code) and copies a blank `.env` into it. Everything personal — your secrets, preferences,
resume, reports — lives in that folder, never in the repo.

---

## 3. Get your Apify token (required)

Apify is the service that does the actual scraping. The free tier (~$5 credit/month) covers
about one run per day.

1. Sign up free at **https://console.apify.com**.
2. Go to **Settings → Integrations** (direct link: https://console.apify.com/account/integrations).
3. Copy your **Personal API token**.
4. Paste it into your `.env` (next step) as `APIFY_TOKEN`.

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
4. Download the chosen PDF to `~/.claude/job-hunt-ai/resumes/base.pdf` and parse it.
5. Ask for your job preferences (locations, CTC floor, role types, experience, etc.).

Your answers are saved to `~/.claude/job-hunt-ai/options/preferences.json` and your parsed
resume profile to `~/.claude/job-hunt-ai/cache/profile.json`. You can re-run `/job-setup`
anytime, or just tell Claude "raise my CTC floor to 18 and add Remote".

---

## 7. Test each piece before automating

These quick checks confirm everything works end to end:

```bash
cd ~/projects/jobpilot

# 1) Telegram works — sends "JobPilot connected ✅" to your chat
python3 scripts/telegram_notify.py --test

# 2) A real (tiny) scrape + filter dry run
python3 scripts/apify_scraper.py     # prints how many jobs were scraped
python3 scripts/dedupe.py
python3 scripts/filter.py            # prints the filter breakdown

# 3) A full manual run inside Claude Desktop
/job-search
```

If `/job-search` produces a CSV in `~/.claude/job-hunt-ai/reports/` and a Telegram message
arrives, you're done.

---

## 8. (Optional) Google Drive uploads

If you already connected Google Drive in step 6a, Drive uploads are automatic — `/job-search`
uses the Drive MCP connector to push the CSV and tailored resumes to a folder called
`JobPilot Reports` in your Drive. Nothing extra to configure.

If you skipped Drive, that's fine — you'll still get the CSV and reports via Telegram.

---

## 9. Schedule it

In Claude Desktop: **Schedule → New Task**, set it to **09:30 IST, weekdays**, and paste:

```
Run the JobPilot job search pipeline. Load skills from ~/projects/jobpilot. Execute /job-search fully autonomously:
1. Run scripts/apify_scraper.py, dedupe.py, filter.py via bash (Layer A — no LLM)
2. Score and research surviving candidates (Layer B)
3. Generate CSV report, tailor resumes for top matches, push to Telegram and Google Drive
Do not pause for confirmation. If any script fails, log the error and continue.
```

One run per day keeps you inside Apify's free tier.

---

## 10. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Secret 'X' not found` | The value isn't in `~/.claude/job-hunt-ai/.env` or the keyring. Re-check step 5; run `python3 scripts/secrets.py`. |
| Telegram test sends nothing | Wrong `TELEGRAM_CHAT_ID`, or you never messaged the bot first (step 4b). |
| `0 raw jobs scraped` | Missing/invalid `APIFY_TOKEN`, exhausted Apify credit, or the actor IDs in `config/actors.json` changed — verify them in the Apify Store. |
| Scores look low / all keywords missing | `sentence-transformers` not installed (it falls back to a rougher proxy). Run `pip install -r requirements.txt`. |
| `tectonic: command not found` | Install tectonic, or use `.docx` resumes (the tailor auto-falls back to DOCX). |
| Drive upload skipped | Google Drive not connected in Claude Desktop. Go to Settings → Connections and connect it. |
| Want to re-see old jobs | Run `/jobpilot-clear` (type CONFIRM) to wipe the seen-job cache. |

---

## Where everything lives (quick reference)

```
~/projects/jobpilot/                 # the code (this repo)
~/.claude/job-hunt-ai/               # YOUR data (not in the repo)
├── .env                             # secrets
├── options/preferences.json         # your search criteria
├── cache/jobs.sqlite                # seen-jobs + score cache
├── cache/profile.json               # parsed resume
├── resumes/base.pdf                 # your master resume (cached from Drive)
├── resumes/tailored/                # generated tailored resumes
└── reports/YYYY-MM-DD-<slot>.csv    # generated reports
```
