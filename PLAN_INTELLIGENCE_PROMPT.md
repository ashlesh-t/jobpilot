# Prompt for Fable — JobPilot Intelligence Research & Planning

Research and produce a full upgrade plan for JobPilot's job-matching intelligence, grounded in
real hiring data rather than assumptions.

## CONTEXT

JobPilot (~/my_works/jobpilot) scores scraped job postings against a candidate's profile.json
and tailors resumes. Today the scoring is purely JD-text-vs-profile keyword/semantic matching
(see CLAUDE.md "Scoring" section). It has no signal on: what these companies' interviews
actually test, what background/skills their accepted candidates tend to have, or whether past
tailored applications from this user actually led to interviews/offers.

## RESEARCH PHASE

For the roles/companies currently in the user's preferences.json / recent job-hunt-ai reports:

1. **Interview process & bar:** pull interview experiences and question patterns from
   GeeksforGeeks Interview Experiences, AmbitionBox, Glassdoor, and Blind. Summarize per
   company/role: rounds, what's actually tested (DSA vs system design vs take-home vs pure
   screen), and common rejection reasons where stated.
2. **Accepted-candidate profile shape:** from public, aggregate signals only (LinkedIn "People
   also viewed"/job posts mentioning team backgrounds, published team bios, GFG/AmbitionBox
   commenters who report offers) — infer the skill/experience pattern that tends to get
   selected, not individual identities. Do not scrape or attribute conclusions to named
   private LinkedIn profiles; keep this at the aggregate "successful candidates in this role
   tend to have X" level.
3. **Gap analysis:** cross-reference against the user's actual profile.json to find what's
   missing or under-weighted that these sources suggest matters but current scoring ignores.

## DELIVERABLE

Write the plan to `jobpilot/PLAN_INTELLIGENCE.md`, following the EXACT structure already used
in `PLAN.md` in this repo: a root-cause/evidence table first, then EPICs with Goal, Stories
with Problem/Solution/Tasks/Acceptance Criteria, referencing real `file:line` locations in this
repo (`scripts/`, `skills/`, `CLAUDE.md`) wherever a change lands. Include short code/prompt
snippets inline where an implementation detail needs to be unambiguous (e.g. a new field in
`profile.json`, a new scoring term, a new WebSearch query template) — not full implementations.

## MUST INCLUDE AS ITS OWN EPIC — Recursive Learning Loop

Design how this improves over time instead of being a one-off scoring tweak:

- Wire outcomes already captured by the `/job-feedback` skill (applied/rejected/interview/offer)
  back into scoring: e.g. a per-skill or per-signal weight adjustment stored in
  `cache/score_cache` or a new `cache/learning.json`, read by Layer B before scoring.
- Define exactly what triggers a re-weight (N outcomes logged, on every `/job-feedback` run,
  weekly, etc.), what the update rule is (concrete formula, not "adjust weights"), and how it's
  capped so one bad data point can't wreck scoring.
- State clearly which parts of this stay in Layer B (Claude, using CLAUDE.md's existing
  Layer A/B split) — no scoring or learning logic may be added to Layer A
  (`apify_scraper.py`/`dedupe.py`/`filter.py`), per the repo's Layer A invariant.

## CONSTRAINTS

- Respect the existing `profile.json` / `preferences.json` schema — propose additive fields, not
  breaking renames, unless you show why a rename is necessary.
- No fabricated data: every "accepted candidates tend to have X" claim must cite the source
  page/type it came from.
- Keep it scoped to what's implementable by an agent working solo in this repo — no new paid
  services beyond what's already integrated (Apify, Telegram, Claude, Google Drive).
