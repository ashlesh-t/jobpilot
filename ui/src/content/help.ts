/**
 * Every piece of explanatory copy in the app, in one file.
 *
 * Keeping it here (rather than inline) means the whole product's voice can be reviewed
 * and edited in one pass, and no field ships without an explanation.
 *
 * Rules for writing these:
 *   - Say what the thing *does for the user*, not what it is internally.
 *   - One or two sentences. If it needs three, the UI is probably wrong.
 *   - No jargon the user hasn't already been taught by the page.
 */

export const help: Record<string, string> = {
  /* -- run / phases ------------------------------------------------------- */
  'run.mode':
    'Full runs include the paid sources (LinkedIn, Naukri, Glassdoor). Native runs use only the free scrapers. Auto alternates, so you get the paid sources about once a day.',
  'run.engine':
    'Which AI backend does the reading and scoring. A Claude Pro/Max subscription costs nothing per run; an API key is billed per token and shows up in the cost meter.',
  'run.phases':
    'A run is a sequence of steps. Each one can be watched, stopped, and re-run on its own without redoing the ones before it.',
  'run.stop':
    'Stops after the current step finishes cleanly. Everything already done is kept — you can resume from exactly here.',
  'run.resume':
    'Continues from the first step that has not finished. Completed steps are not repeated.',
  'run.rerun':
    'Runs this step again with fresh results. Steps that depend on it are re-run too, since their old output would no longer match.',
  'run.artifact':
    'The raw data this step produced. Useful when a result looks wrong and you want to see exactly what the step saw.',

  'phase.scrape':
    'Fetches raw postings from every configured source. Nothing is filtered or scored yet.',
  'phase.dedupe':
    'Drops postings you have already seen in an earlier run, and collapses the same job listed on several boards.',
  'phase.filter':
    'Removes jobs outside your locations, past their deadline, or above your experience cap. Purely mechanical — no judgement calls.',
  'phase.discover':
    'Looks beyond the job boards: company career pages and a few targeted searches, for roles the scrapers miss.',
  'phase.relevance':
    'Reads each posting and drops the ones that are not really your field. Also fetches descriptions that were missing.',
  'phase.score':
    'Compares every job description against your profile and scores the match out of 100.',
  'phase.intel':
    'Researches how each company actually interviews — DSA-heavy, system design, portfolio — and adjusts the ranking to your readiness.',
  'phase.salary':
    'Looks up the real market range for your top matches, so you know what to ask for.',
  'phase.persist':
    'Saves the results so they appear on your dashboard and are remembered next run.',
  'phase.report':
    'Builds the spreadsheet of your top matches, ready to download or forward.',
  'phase.notify':
    'Delivers the summary, spreadsheet and any tailored resumes to your configured channels.',

  /* -- scores ------------------------------------------------------------- */
  'score.match':
    'How well this job matches your profile, out of 100. Half comes from the specific skills the description asks for, half from overall fit.',
  'score.keyword':
    'The share of skills this job asks for that your profile actually has.',
  'score.semantic':
    'A judgement of overall fit: stack, seniority, how relevant your projects are, and the kind of company.',
  'score.effective':
    'The match score adjusted for how much you want that location, how well you fit the interview bar, and what past outcomes have taught JobPilot. Used for ordering only.',
  'score.confidence':
    'Low confidence means the job description could not be retrieved, so the score is based mostly on the title.',
  'score.bar_fit':
    'How well you fit the way this company interviews. Negative means the bar is a stretch — e.g. heavy DSA when your profile has no DSA signal.',
  'score.gap_signals':
    'What this company looks for that your profile cannot currently show. This is your prep list.',
  'score.prep_focus':
    'What to actually practise before interviewing here, based on how the company is known to interview.',

  /* -- jobs --------------------------------------------------------------- */
  'jobs.stale':
    'Jobs whose deadline has passed, or that have not appeared in any recent scan. Hidden by default so the list stays worth reading.',
  'jobs.unapplied':
    'Only shows jobs you have not marked as applied yet.',
  'jobs.package':
    'Sorted by the researched market range, not what the posting claims. Jobs with no researched range sort last.',
  'jobs.source':
    'Which board or search this job came from.',
  'jobs.export':
    'Downloads exactly the rows you are looking at, with the same columns as the emailed spreadsheet.',

  /* -- applications ------------------------------------------------------- */
  'applications.status':
    'Where this application actually stands. Every change is dated, so you can see how long each stage took.',
  'applications.funnel':
    'How many applications reached each stage. Reaching a later stage counts for every earlier one too.',
  'applications.stale':
    'Applications with no movement for two weeks. Usually worth a follow-up.',
  'applications.undo':
    'Removes the application record entirely and puts the job back in your unapplied list.',

  /* -- resumes ------------------------------------------------------------ */
  'resume.active':
    'The resume JobPilot reads when scoring jobs and the one it tailors from. Only one can be active.',
  'resume.folders':
    'Group resumes however you like — by role, by year, by company type. Only the active one is used.',
  'resume.tailor':
    'Rewrites your active resume to emphasise what this specific job asks for. It never invents experience, dates or employers.',
  'referral.draft':
    'A tailored referral-request message, drafted from your profile and this job’s description. It only ever gets saved here as a draft — nothing is sent automatically. Copy it, edit it, and send it yourself.',
  'resume.overleaf':
    'The LaTeX source next to the PDF. Paste it into Overleaf if you want to adjust the wording or layout yourself.',
  'resume.review':
    'Always read a tailored resume before sending it. Automated tailoring can shift spacing and page breaks.',

  /* -- profile / preferences ---------------------------------------------- */
  'profile.verified':
    'Confirmed means you have read the extracted profile and it is correct. Scoring uses it either way, but an unconfirmed profile is more likely to be wrong.',
  'profile.skills':
    'Only skills listed here can ever count as a match. Adding one you cannot defend in an interview inflates your scores.',
  'profile.interview_readiness':
    'Your honest current level. It only affects ordering — a low level never hides a job from you, it just stops JobPilot from recommending interviews you would not enjoy.',
  'profile.experience_years':
    'Years of professional experience. Jobs asking for more than this plus two are dropped automatically.',

  'prefs.locations':
    'Cities you would work in. The first is treated as your first choice and ranks highest.',
  'prefs.remote_ok':
    'Include remote roles regardless of where the company is.',
  'prefs.market_focus':
    'Which sources to use: India-focused boards, global remote boards, or both.',
  'prefs.role_types':
    'The kinds of role you want. Used both to search and to drop obviously off-domain results.',
  'prefs.target_ctc':
    'Your minimum acceptable package. JobPilot never suggests asking for less than this.',
  'prefs.score_threshold':
    'The match score a job must reach before JobPilot offers to tailor your resume for it.',
  'prefs.notice_period':
    'How long before you could start. Shown to you when a posting has a tight start date.',
  'prefs.stale_after_days':
    'How long a job stays in your list after it was last seen in a scan.',

  /* -- secrets / connections ---------------------------------------------- */
  'secrets.storage':
    'Stored in your operating system keyring, never in the database and never in a file JobPilot syncs anywhere.',
  'secrets.reveal':
    'Shows the full value once. Nothing is written to logs.',
  'secrets.anthropic':
    'Enables the metered Claude API backend and exact per-run costs. Not needed if you use a Claude Pro or Max subscription.',
  'secrets.apify':
    'Unlocks LinkedIn, Naukri, Glassdoor and Indeed. Optional — the free scrapers work without it.',
  'secrets.apify_slots':
    'Extra Apify accounts. JobPilot switches to the next one automatically when the first runs out of credit.',
  'secrets.telegram_bot':
    'The bot that sends your digests. Create it by messaging @BotFather in Telegram, then paste the whole token it gives you — digits, colon and letters together, like 123456789:AAH… Not just the numbers, and none of the words around it.',
  'secrets.telegram_chat':
    'Which chat the bot messages. Captured automatically the first time you message your bot.',
  'secrets.discord':
    'A second delivery channel. Create a webhook in Channel Settings → Integrations.',

  /* -- schedule ----------------------------------------------------------- */
  'schedule.slots':
    'Times of day to run automatically. Two a day is plenty — postings do not appear that fast.',
  'schedule.daemon':
    'Runs JobPilot in the background so scheduled runs happen without you opening anything.',
  'schedule.catchup':
    'If your machine was off when a run was due, JobPilot runs it once when the machine comes back — not once for every slot it missed.',
  'schedule.retry':
    'If there is no network when a run is due, JobPilot waits and retries rather than recording a failure.',
  'schedule.timezone':
    'All times are in this timezone, including across daylight-saving changes.',

  /* -- costs -------------------------------------------------------------- */
  'cost.meter':
    'What the AI backend has cost. A Claude Pro or Max subscription shows the tokens used but no dollar amount, because there is no per-token charge.',
  'cost.subscription':
    'Real token usage on a subscription plan. You are not billed per token for these.',
  'cost.estimate':
    'The provider did not report exact usage, so this is an estimate from the tokens observed.',

  /* -- storage / health --------------------------------------------------- */
  'db.backend':
    'PostgreSQL runs in a small Docker container JobPilot manages. Without Docker it uses a SQLite file instead — everything works the same.',
  'doctor.live':
    'The deeper check: verifies your AI backend is actually signed in and fetches a few real jobs from every source. Slower, and worth running when something looks wrong.',
  'doctor.quick':
    'Checks configuration only. Fast enough to run any time.',
}

export function helpFor(key: string): string | undefined {
  return help[key]
}
