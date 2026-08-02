# JobPilot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Your job hunt, automated — running entirely on your own machine.

JobPilot scrapes a dozen job sources, reads every posting against your actual resume,
scores the matches, researches what they pay, tailors your resume to the ones worth
applying to, and tracks every application from first click to offer. It runs on a
schedule, in the background, and shows you all of it in a local web app.

Nothing is uploaded anywhere. Your resume, your job history and your API keys stay on
your machine.

```sh
pipx install jobpilot-ai
jobpilot setup
jobpilot start
```

---

## What a run actually does

A run is eleven steps you can watch, stop, resume, and re-run individually:

| Step | What happens | Who does it |
|---|---|---|
| Scrape | Fetch postings from every configured source | Python — free, no LLM |
| Remove duplicates | Drop what you've already seen | Python |
| Apply hard filters | Location, deadline, experience cap | Python |
| Search for more | Company career pages and targeted searches | AI |
| Check relevance | Drop off-domain roles; recover missing descriptions | AI |
| Score the matches | Compare each description against your profile | AI |
| Company intelligence | How each company actually interviews | AI |
| Salary research | Real market ranges for your top matches | AI |
| Save results | Into your database | Python |
| Build the spreadsheet | Styled XLSX of the top matches | Python |
| Send the digest | Telegram, Discord, or neither | Python |

Scraping, filtering and reporting never touch the LLM, which is why a run is cheap. The
reasoning steps are where the AI earns its keep.

**Stop** finishes the current step cleanly and keeps everything already done.
**Resume** picks up from exactly there. **Re-run** on a single step redoes just that step
and the ones that depend on it.

## How scoring works

Every job gets a `score` out of 100:

- half from **which of the skills the job asks for you actually have** — measured against
  what that description asks for, not your whole skill list
- half from an **overall judgement of fit** — stack, seniority, project relevance, the
  kind of company

That score drives every threshold. A separate `effective_score` handles ordering only: it
adjusts for how much you want that location, how well you fit the company's interview
style, and what your past application outcomes have taught JobPilot.

## Setup

`jobpilot setup` walks you through it in the terminal:

1. **You** — name and contact
2. **Storage** — PostgreSQL in Docker if you have it, SQLite otherwise. Both fully supported.
3. **AI backend** — Claude Code on a Pro/Max subscription (no per-token cost), an Anthropic
   API key (metered, with an exact cost meter), Gemini, or any headless agent CLI
4. **Job sources** — optional Apify token for LinkedIn, Naukri, Glassdoor and Indeed.
   Eight free sources work without it.
5. **Delivery** — Telegram (scan a QR, press Start, and the chat is linked automatically)
   and Discord

Then `jobpilot start` and finish in the browser: upload your resume, confirm the extracted
profile, set your preferences.

## The web app

| Page | What it's for |
|---|---|
| **Home** | Dashboard, charts, and the full filterable job table with CSV/XLSX export |
| **Job Hunt** | Start a run and watch it step by step; manage your resumes |
| **Applications** | Board and table view of everything you've applied to, with a dated history |
| **Tailored Resumes** | Every resume rewritten for a specific job, with the Overleaf source |
| **Scheduler** | Run times, the background service, and what happens after downtime |
| **My Info** | Profile, preferences, credentials, health checks |
| **Assistant** | Ask about your own jobs, scores and runs |

Light and dark, works offline, no external requests.

## Resume tailoring

Open any job and choose **Tailor resume**. JobPilot rewrites your active resume to
emphasise what that job asks for — it reorders and rewords, and never invents experience,
employers or dates.

Output lands in `resumes/tailored/<JOBID>-<COMPANY>/`:

```
FirstName_LastName_Resume.pdf
FirstName_LastName_Resume.tex     # compiles unchanged on Overleaf
meta.json                         # skills matched, ATS score before and after
```

The template is ATS-safe by construction — single column, no tables or images, standard
section names — because that is what survives automated parsing. Every generated document
is validated against those rules before it is compiled.

**Always read a tailored resume before sending it.** Automated tailoring can shift spacing
and page breaks.

## Scheduling

Add run times on the Scheduler page and install the background service. JobPilot then
starts with your machine.

If the machine was off when a run was due, JobPilot runs it **once** when it comes back —
not once per missed slot, and not at all if the miss is older than your grace window. No
network at run time means a retry ladder (1, 5, 15, 30 minutes), not a recorded failure.

## Cost

On a Claude Pro or Max subscription, runs cost nothing per token — the meter shows tokens
used and no dollar amount, because there is no per-token charge.

With an Anthropic API key, every phase, tailoring job and assistant answer is priced into a
cost ledger you can see per run and per month.

Apify is optional and has a free tier.

## Commands

```
jobpilot setup      guided setup
jobpilot start      setup if needed, then serve and open the UI
jobpilot serve      run the service without opening a browser
jobpilot stop       stop a running service
jobpilot doctor     health check (--live also verifies your login and probes sources)
jobpilot logs -f    tail the service log
jobpilot db         up | down | status | url
jobpilot service    install | uninstall | status
jobpilot migrate    import state from JobPilot v1
```

## Job sources

**Free, no token needed:** Internshala, RemoteOK, We Work Remotely, Remotive, Arbeitnow,
Jobicy, Hacker News "Who is hiring", YC startups, and Telegram job channels.

**With an Apify token:** LinkedIn, Naukri, Glassdoor, Indeed, Wellfound, Cutshort —
sources that block direct access. If credit runs out, JobPilot rotates through your other
token slots and then degrades to free sources rather than failing the run.

## Where things live

```
~/.claude/job-hunt-ai/
├── cache/            database, profile, caches
├── options/          preferences.json
├── resumes/          your resumes, and tailored/ output
├── reports/          generated spreadsheets
├── runs/<run_id>/    per-run artifacts, kept so any step can be re-run later
└── logs/             service log
```

Credentials are **not** in there — they go into your operating system's keyring.

## Upgrading from v1

`jobpilot setup` detects v1 data and offers to import it: preferences, profile, job
history, score cache, feedback and run history. The import is idempotent and never deletes
or modifies your v1 files. You can also run it directly with `jobpilot migrate`.

Two things changed that you will notice:

- **Google Drive is gone.** Resumes are uploaded in the web app instead. Nothing to
  connect, nothing to authorise.
- **Setup no longer happens inside Claude Desktop.** `jobpilot setup` and the web app
  replace `/job-setup` entirely.

The Claude Code plugin still works if you prefer driving it from chat — see
[GETTING_STARTED.md](GETTING_STARTED.md).

## Requirements

- Python 3.11+
- Optional: Docker (for PostgreSQL — SQLite is used otherwise)
- Optional: `tectonic` (to compile tailored resumes to PDF locally — otherwise you get the
  Overleaf-ready source)
- An AI backend: a Claude Pro/Max subscription, or an Anthropic API key

## Contributing

```sh
git clone https://github.com/ashlesh-t/jobpilot && cd jobpilot
python -m venv venv && venv/bin/pip install -e ".[dev]"
npm --prefix ui install && npm --prefix ui run build
venv/bin/pytest
```

The built UI in `ui/dist` is committed so a source install needs no Node toolchain.

MIT licensed.
