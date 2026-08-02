"""The phase registry — what a run is made of.

Carved out of the monolithic `skills/job-search/SKILL.md`. Each phase declares who runs
it, what it needs, and what it produces:

  kind="python"  a Layer A script, run directly as a subprocess. No LLM, instantly
                 cancellable, and free. Scrape/dedupe/filter/report/notify.
  kind="llm"     a per-phase skill executed by the configured agent. Discovery,
                 relevance, scoring, company intel, salary research.

`depends_on` drives invalidation: rerunning a phase resets everything downstream of it,
because a new scoring pass makes the old salary research and report stale.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import artifacts as A


@dataclass(frozen=True)
class Phase:
    key: str
    label: str
    help: str
    kind: str                       # "python" | "llm"
    depends_on: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    output: str | None = None
    #: skipping this phase is normal, not a failure (e.g. nothing to tailor)
    optional: bool = False
    #: attempt this even when an earlier phase failed — the user still wants a report
    always_attempt: bool = False
    #: how many times a transient failure is retried before the phase errors
    max_attempts: int = 2
    #: rough share of total run time, used for the progress bar
    weight: float = 1.0
    script: tuple[str, ...] = ()    # argv template for kind="python"
    skill: str = ""                 # slash command for kind="llm"
    tags: tuple[str, ...] = field(default_factory=tuple)


PHASES: tuple[Phase, ...] = (
    Phase(
        key="scrape",
        label="Scrape sources",
        help="Fetches raw postings from the free native scrapers, then the Apify "
             "sources if you've added a token. Nothing is scored yet.",
        kind="python",
        output=A.RAW,
        script=("scripts/apify_scraper.py",),
        max_attempts=3,
        weight=3.0,
        tags=("layer-a",),
    ),
    Phase(
        key="dedupe",
        label="Remove duplicates",
        help="Drops postings you've already seen in an earlier run and collapses the "
             "same job listed on several boards.",
        kind="python",
        depends_on=("scrape",),
        inputs=(A.RAW,),
        output=A.DEDUPED,
        script=("scripts/dedupe.py",),
        weight=0.3,
        tags=("layer-a",),
    ),
    Phase(
        key="filter",
        label="Apply hard filters",
        help="Removes jobs outside your locations, past their deadline, or above your "
             "experience cap. Purely mechanical — no judgement calls.",
        kind="python",
        depends_on=("dedupe",),
        inputs=(A.DEDUPED,),
        output=A.FILTERED,
        script=("scripts/filter.py",),
        weight=0.5,
        tags=("layer-a",),
    ),
    Phase(
        key="discover",
        label="Search for more",
        help="Looks beyond the job boards: company career pages and a few targeted web "
             "searches, for roles the scrapers miss.",
        kind="llm",
        depends_on=("filter",),
        inputs=(A.FILTERED,),
        output=A.DISCOVERED,
        skill="/job-phase-discover",
        optional=True,
        weight=2.0,
    ),
    Phase(
        key="relevance",
        label="Check relevance",
        help="Reads each posting and drops the ones that aren't really your field or "
             "demand far more experience than you have. Fetches missing descriptions.",
        kind="llm",
        depends_on=("discover",),
        inputs=(A.FILTERED, A.DISCOVERED),
        output=A.RELEVANT,
        skill="/job-phase-relevance",
        weight=2.5,
    ),
    Phase(
        key="score",
        label="Score the matches",
        help="Compares every job description against your profile and gives it a match "
             "score out of 100, with the skills you have and the ones you're missing.",
        kind="llm",
        depends_on=("relevance",),
        inputs=(A.RELEVANT,),
        output=A.SCORED,
        skill="/job-phase-score",
        weight=4.0,
    ),
    Phase(
        key="intel",
        label="Company intelligence",
        help="Researches how each company actually interviews — DSA-heavy, system "
             "design, portfolio — and adjusts the ranking to your readiness.",
        kind="llm",
        depends_on=("score",),
        inputs=(A.SCORED,),
        output=A.SCORED,
        skill="/job-phase-intel",
        optional=True,
        weight=2.0,
    ),
    Phase(
        key="salary",
        label="Salary research",
        help="Looks up the real market range for your top matches so you know what to "
             "ask for before you apply.",
        kind="llm",
        depends_on=("intel",),
        inputs=(A.SCORED,),
        output=A.SCORED,
        skill="/job-phase-salary",
        optional=True,
        weight=2.0,
    ),
    Phase(
        key="persist",
        label="Save results",
        help="Writes the scored jobs into your database so they show up on the "
             "dashboard and are remembered next run.",
        kind="python",
        depends_on=("salary",),
        inputs=(A.SCORED,),
        script=("scripts/record_scored.py",),
        always_attempt=True,
        weight=0.3,
        tags=("layer-a",),
    ),
    Phase(
        key="report",
        label="Build the spreadsheet",
        help="Generates the styled XLSX report of your top matches, ready to download "
             "or forward.",
        kind="python",
        depends_on=("persist",),
        inputs=(A.SCORED,),
        script=("scripts/report_generator.py",),
        always_attempt=True,
        weight=0.5,
        tags=("layer-a",),
    ),
    Phase(
        key="notify",
        label="Send the digest",
        help="Delivers the summary, the spreadsheet and any tailored resumes to your "
             "configured channels.",
        kind="python",
        depends_on=("report",),
        output=A.NOTIFY_RECEIPT,
        script=("scripts/notify_run.py",),
        always_attempt=True,
        optional=True,
        weight=0.4,
        tags=("layer-a",),
    ),
)

PHASE_KEYS: tuple[str, ...] = tuple(p.key for p in PHASES)
BY_KEY: dict[str, Phase] = {p.key: p for p in PHASES}
TOTAL_WEIGHT = sum(p.weight for p in PHASES)


def get(key: str) -> Phase:
    try:
        return BY_KEY[key]
    except KeyError:
        raise ValueError(f"unknown phase {key!r}; expected one of {list(PHASE_KEYS)}") from None


def position(key: str) -> int:
    return PHASE_KEYS.index(key)


def downstream_of(key: str, *, inclusive: bool = True) -> list[str]:
    """Phases invalidated by rerunning `key` — itself plus everything after it."""
    idx = position(key)
    start = idx if inclusive else idx + 1
    return list(PHASE_KEYS[start:])


def selection(only: list[str] | None = None, skip: list[str] | None = None) -> list[str]:
    """Resolve a user's phase choice into an ordered, validated key list."""
    keys = list(PHASE_KEYS)
    if only:
        unknown = [k for k in only if k not in BY_KEY]
        if unknown:
            raise ValueError(f"unknown phase(s): {', '.join(unknown)}")
        keys = [k for k in keys if k in set(only)]
    if skip:
        keys = [k for k in keys if k not in set(skip)]
    if not keys:
        raise ValueError("phase selection is empty")
    return keys


def progress(done_keys: list[str]) -> float:
    """0.0–1.0 completion, weighted by expected phase duration."""
    if TOTAL_WEIGHT <= 0:
        return 0.0
    done = sum(BY_KEY[k].weight for k in done_keys if k in BY_KEY)
    return round(min(1.0, done / TOTAL_WEIGHT), 4)


def to_dict(phase: Phase) -> dict:
    return {
        "key": phase.key,
        "label": phase.label,
        "help": phase.help,
        "kind": phase.kind,
        "depends_on": list(phase.depends_on),
        "inputs": list(phase.inputs),
        "output": phase.output,
        "optional": phase.optional,
        "always_attempt": phase.always_attempt,
        "weight": phase.weight,
        "position": position(phase.key),
    }


def catalog() -> list[dict]:
    """The phase list the UI renders before a run starts."""
    return [to_dict(p) for p in PHASES]
