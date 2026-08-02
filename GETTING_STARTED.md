# Getting started

From nothing to your first scored job list. About ten minutes, most of it waiting.

---

## 1. Install

```sh
pipx install jobpilot-ai
```

No pipx? `pip install --user jobpilot-ai` works too. You need Python 3.11 or newer.

## 2. Run setup

```sh
jobpilot setup
```

Six steps in your terminal. Here's what each one wants, and what you can skip.

### You

Your name and email. The name goes on every tailored resume, so spell it the way you want
it to appear.

### Storage

JobPilot asks whether to use PostgreSQL (in a Docker container it manages for you) or a
SQLite file.

**Either is fine.** SQLite needs nothing installed and handles tens of thousands of jobs
without complaint. If you don't have Docker, JobPilot picks SQLite automatically and moves
on — it never blocks you here.

If you have v1 data, this step offers to import it. Say yes: the import is idempotent and
never touches your old files.

### AI backend

JobPilot needs an agent to read job descriptions and score them. Pick one:

- **Claude Code CLI** — if you have a Claude Pro or Max subscription. Runs cost nothing per
  token. JobPilot checks the CLI is installed *and* that you're actually signed in; if not,
  it offers to install it and walks you through `claude login`.
- **Anthropic API key** — metered, but you get an exact cost figure for every run, phase and
  tailored resume. Create one at
  [console.anthropic.com](https://console.anthropic.com/settings/keys).
- **Gemini / Antigravity** or **a custom CLI** — experimental. Claude is the tested path.

### Job sources (optional)

Eight sources are free and need nothing: Internshala, RemoteOK, We Work Remotely, Remotive,
Arbeitnow, Jobicy, Hacker News "Who is hiring", and YC.

An [Apify](https://console.apify.com/settings/integrations) token adds LinkedIn, Naukri,
Glassdoor and Indeed. The free tier is enough for a few runs a week. **Skip this if you're
not sure** — you can add it later from My Info.

### Delivery (optional)

**Telegram** is the fiddly one everywhere else, and it isn't here:

1. JobPilot shows a link and a QR code for [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, answer two questions, copy the token it gives you.
3. Paste it. JobPilot verifies it and shows a QR code for *your* bot.
4. Open your bot and press **Start**.

That's it — the chat ID is captured automatically. No copying numbers out of a JSON blob.

**Discord** is one webhook URL from Channel Settings → Integrations.

You can skip both. Results live in the web app either way.

## 3. Start it

```sh
jobpilot start
```

Your browser opens at `http://127.0.0.1:8787`.

## 4. Finish in the browser

The Job Hunt page shows what's still missing and a **Set up now** button.

1. **Upload your resume** — drag a PDF, DOCX or TEX into the drop zone.
2. **Press "Read it."** JobPilot extracts a profile from it.
3. **Check the profile.** This is what every job gets scored against, so it's worth reading.
   Fix anything wrong, then confirm it.
4. **Say what you're looking for** — cities, kinds of role, and optionally a minimum package.

## 5. Your first run

Press **Start hunt**. Watch the steps go by — scraping takes the longest, scoring costs the
most.

A few minutes later, Home fills in: your matches, sorted best-first, with a score out of
100 and what it was based on. Click any job for the full breakdown.

**If a step fails**, JobPilot keeps everything before it. Press **Resume** to continue, or
**Re-run** on that one step.

## 6. Make it automatic

On the **Scheduler** page, add a run time or two and press **Install service**. JobPilot
then starts with your machine and runs on its own.

If your machine is off when a run is due, JobPilot runs it once when you come back — not
once for every slot it missed.

---

## When something looks wrong

```sh
jobpilot doctor          # configuration check
jobpilot doctor --live   # also verifies your AI login and fetches real jobs
```

The same table is on **My Info → Health**, with a Test button beside every credential.

**No jobs found?** Try `--live` — it will tell you whether a source is down or your filters
are simply too narrow. Widening your locations or lowering the score filter usually does it.

**Runs cost more than expected?** Home shows the month's spend, and each run breaks it down
per step. On a Claude subscription this shows tokens with no dollar figure, because there's
no per-token charge.

---

## Using it from Claude Code instead

The plugin still works if you prefer chat:

```
/plugin marketplace add ashlesh-t/jobpilot
/plugin install jobpilot@jobpilot
```

Then `/job-search`, `/job-tailor <job_id>`, `/job-feedback`, `/jobpilot-clear`.

`/job-setup` is superseded — run `jobpilot setup` and use the web app instead. It's faster,
and it doesn't need Google Drive.

---

## Where your data lives

```
~/.claude/job-hunt-ai/
├── cache/            database, profile
├── options/          preferences.json
├── resumes/          your resumes, and tailored/ output
├── reports/          generated spreadsheets
├── runs/<run_id>/    per-run artifacts
└── logs/             service log
```

API keys and tokens are **not** in there — they're in your operating system's keyring.

Nothing is uploaded anywhere. To remove JobPilot entirely: `pipx uninstall jobpilot-ai`,
`jobpilot db down`, and delete that directory.
