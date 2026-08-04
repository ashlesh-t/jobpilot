/** WhoAmI — what JobPilot is, what it has done for you, and what changed lately.
 *
 *  Every number on this page is your own local data, pulled from the endpoints the
 *  dashboard already uses. Nothing is fetched from the internet. */
import clsx from 'clsx'
import {
  Bug,
  Check,
  ChevronRight,
  Copy,
  Cpu,
  Database,
  ExternalLink,
  FolderOpen,
  Github,
  Sparkles,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import {
  ApplicationFunnel,
  JobsPerScan,
  ScoreDistribution,
  SourceBreakdown,
} from '@/components/charts/Charts'
import { PageHeader } from '@/components/layout/PageHeader'
import { useToast } from '@/components/ui/Toast'
import { Card, Chip, EmptyState, SkeletonRows } from '@/components/ui/primitives'
import { formatUsd } from '@/lib/format'
import { useAbout, useChangelog } from '@/lib/about'
import type { About, Release } from '@/lib/about'
import { useRuns } from '@/lib/hooks'
import { useJobStats, useScans } from '@/lib/jobs'
import '@/styles/whoami.css'

/* -------------------------------------------------------------------------- */
/* Scroll reveal                                                              */
/* -------------------------------------------------------------------------- */
function Reveal({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [shown, setShown] = useState(false)

  useEffect(() => {
    const node = ref.current
    if (!node) return
    // No IntersectionObserver (old webview, jsdom) → just show the content.
    if (typeof IntersectionObserver === 'undefined') {
      setShown(true)
      return
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true)
          observer.disconnect()
        }
      },
      { rootMargin: '-40px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return (
    <div ref={ref} className={clsx('wai-reveal', className)} data-shown={shown}>
      {children}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Hero + pipeline                                                            */
/* -------------------------------------------------------------------------- */
const PIPELINE = [
  { name: 'Scrape', note: 'native + Apify sources', layer: 'a' },
  { name: 'Dedupe', note: 'one row per real job', layer: 'a' },
  { name: 'Filter', note: 'location, experience, CTC', layer: 'a' },
  { name: 'Discover', note: 'web search for more', layer: 'b' },
  { name: 'Score', note: 'read the JD, judge the fit', layer: 'b' },
  { name: 'Intel', note: 'the actual hiring bar', layer: 'b' },
  { name: 'Tailor', note: 'rewrite your resume', layer: 'b' },
  { name: 'Notify', note: 'digest, sheet, PDFs', layer: 'a' },
] as const

/** The letters J and P fly in from opposite sides and lock together — plays once per
 *  visit to this page, never on scroll, and is a no-op under reduced motion (CSS only,
 *  see .wai-jp in whoami.css). */
function JPMark() {
  return (
    <div className="wai-jp" aria-hidden="true">
      <span className="wai-jp-letter wai-jp-j">J</span>
      <span className="wai-jp-letter wai-jp-p">P</span>
    </div>
  )
}

function Hero({ about }: { about?: About }) {
  return (
    <div className="wai-hero mb-8">
      <JPMark />
      <Chip tone="accent">
        <span className="flex items-center gap-1">
          <Sparkles className="h-3 w-3" />
          {about ? `v${about.version}` : 'JobPilot'}
        </span>
      </Chip>
      <h1 className="wai-title mt-3">Your job hunt, on autopilot.</h1>
      <p className="mt-4 max-w-2xl text-base text-muted">
        JobPilot scrapes job boards, reads every description against your actual resume,
        scores the fit, rewrites your resume for the ones worth applying to, and sends you
        the shortlist. It runs on your machine, against your own database — no account, no
        upload, no third party holding your résumé.
      </p>

      <div className="wai-pipeline mt-8">
        {PIPELINE.map((step, i) => (
          <div
            key={step.name}
            className="wai-step"
            data-layer={step.layer}
            style={{ ['--wai-delay' as string]: `${i * 0.55}s` }}
          >
            <p className="wai-step-index">Step {i + 1}</p>
            <p className="wai-step-name">{step.name}</p>
            <p className="wai-step-note">{step.note}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-faint">
        Steps with an accent border are the ones an AI agent runs; the rest are plain
        Python, so they're fast, free and cancellable.
      </p>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Personas                                                                    */
/* -------------------------------------------------------------------------- */
const PERSONAS = [
  {
    title: 'The fresher in India',
    body: 'Internshala, Naukri and LinkedIn every morning, filtered to the roles that actually take 0–1 years, with the DSA bar for each company flagged before you apply.',
  },
  {
    title: 'The working engineer',
    body: 'A quiet scheduled run while you keep your current job. Only the strong matches reach your phone, each with a resume already rewritten for it.',
  },
  {
    title: 'The remote-only searcher',
    body: 'RemoteOK, WeWorkRemotely, Remotive, Arbeitnow and Jobicy pooled and deduped, so the same posting on five boards is one line, not five.',
  },
]

/* -------------------------------------------------------------------------- */
/* Stats                                                                       */
/* -------------------------------------------------------------------------- */
function StatTile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="card card-pad">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight text-ink">
        {value}
      </p>
      {hint && <p className="mt-1 text-xs text-faint">{hint}</p>}
    </div>
  )
}

function YourNumbers() {
  const stats = useJobStats()
  const scans = useScans()
  const runs = useRuns(50)

  if (stats.isLoading) return <SkeletonRows rows={4} />

  const data = stats.data
  const history = runs.data?.history ?? []
  const completed = history.filter((r) => r.status === 'done').length

  if (!data || data.total === 0) {
    const hasAttempts = history.length > 0
    return (
      <Card>
        <EmptyState
          icon={<Sparkles className="h-5 w-5" />}
          title={hasAttempts ? 'No scored jobs yet' : 'No runs yet'}
          description={
            hasAttempts
              ? `${history.length} run${history.length === 1 ? '' : 's'} so far, but none scored a job yet — check Job Hunt for step-by-step logs on why.`
              : "Start your first hunt from Job Hunt — this section fills in with your own numbers as soon as there's something to show."
          }
        />
      </Card>
    )
  }

  return (
    <>
      <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <StatTile label="Jobs seen" value={data.total} hint={`${data.fresh} still open`} />
        <StatTile label="Average match" value={`${data.avg_score}`} hint="out of 100" />
        <StatTile label="Strong matches" value={data.high_match} hint="scored 75+" />
        <StatTile label="Resumes tailored" value={data.tailored} />
        <StatTile
          label="Spend this month"
          value={formatUsd(data.cost_month.usd)}
          hint={data.cost_month.usd ? 'metered backend' : 'on a subscription — no per-run cost'}
        />
      </div>

      <div className="wai-bento">
        <Card title="How your matches score" className="wai-wide">
          <ScoreDistribution buckets={data.score_buckets} />
        </Card>
        <Card title="Where they come from">
          <SourceBreakdown sources={data.by_source} />
        </Card>
        <Card title="Applications">
          <ApplicationFunnel stages={data.funnel.stages} />
        </Card>
        <Card
          title="Jobs scored per run"
          subtitle={completed ? `${completed} completed runs` : undefined}
          className="wai-wide"
        >
          <JobsPerScan scans={scans.data ?? []} />
        </Card>
      </div>
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* Under the hood                                                              */
/* -------------------------------------------------------------------------- */
function UnderTheHood({ about }: { about?: About }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="How it's put together">
        <dl className="space-y-3 text-sm">
          <div>
            <dt className="font-medium text-ink">Layer A — plain Python</dt>
            <dd className="text-muted">
              Scraping, deduping and filtering. No AI in the loop, so it's free, fast, and
              stops the moment you cancel.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-ink">Layer B — the agent</dt>
            <dd className="text-muted">
              Every judgement call: is this role relevant, how well do you fit it, what does
              this company actually test for, and how should your resume read for it.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-ink">The orchestrator</dt>
            <dd className="text-muted">
              Drives the phases one at a time and records each one, which is what makes stop,
              resume and re-run-a-single-phase possible.
            </dd>
          </div>
        </dl>
      </Card>

      <div id="tools" className="scroll-mt-24">
      <Card title="This install">
        {!about ? (
          <SkeletonRows rows={3} />
        ) : (
          <>
            <ul className="space-y-2.5">
              {about.tools.map((tool) => (
                <li key={tool.name} className="flex items-start gap-2.5 text-sm">
                  {tool.found ? (
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" />
                  ) : (
                    <X
                      className={clsx(
                        'mt-0.5 h-4 w-4 shrink-0',
                        tool.required ? 'text-danger' : 'text-warn',
                      )}
                    />
                  )}
                  <div className="min-w-0">
                    <p className="text-ink">{tool.name}</p>
                    <p className="text-xs text-muted">{tool.detail}</p>
                    {!tool.found && tool.hint && (
                      <p className="mt-0.5 break-words text-xs text-faint">
                        <code className="rounded bg-raised px-1">{tool.hint}</code>
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>

            <dl className="mt-4 space-y-1.5 border-t border-line pt-4 text-xs text-muted">
              <div className="flex items-start gap-2">
                <Database className="mt-0.5 h-3.5 w-3.5 shrink-0 text-faint" />
                <span>
                  {about.db_backend} — <span className="break-all">{about.db_url}</span>
                </span>
              </div>
              <div className="flex items-start gap-2">
                <FolderOpen className="mt-0.5 h-3.5 w-3.5 shrink-0 text-faint" />
                <span className="break-all">{about.data_dir}</span>
              </div>
              <div className="flex items-start gap-2">
                <Cpu className="mt-0.5 h-3.5 w-3.5 shrink-0 text-faint" />
                <span>
                  {about.platform} · Python {about.python} · installed via{' '}
                  {about.install_source}
                </span>
              </div>
            </dl>
          </>
        )}
      </Card>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Changelog                                                                   */
/* -------------------------------------------------------------------------- */
/** Render the only two inline markdown forms the changelog uses: **bold** and `code`. */
function Markdown({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean)
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('**') && part.endsWith('**')) {
          return (
            <strong key={i} className="font-medium text-ink">
              {part.slice(2, -2)}
            </strong>
          )
        }
        if (part.startsWith('`') && part.endsWith('`')) {
          return (
            <code key={i} className="rounded bg-raised px-1 text-[0.85em]">
              {part.slice(1, -1)}
            </code>
          )
        }
        return <span key={i}>{part}</span>
      })}
    </>
  )
}

function ReleaseEntry({ release, current }: { release: Release; current: string }) {
  const [open, setOpen] = useState(false)
  const isCurrent = release.version === current

  return (
    <div className="border-t border-line first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 py-3 text-left"
        aria-expanded={open}
      >
        <ChevronRight
          className={clsx(
            'h-4 w-4 shrink-0 text-faint transition-transform',
            open && 'rotate-90',
          )}
        />
        <span className="font-medium tabular-nums text-ink">v{release.version}</span>
        {isCurrent && <Chip tone="accent">You're on this</Chip>}
        {release.title && (
          <span className="min-w-0 truncate text-sm text-muted">{release.title}</span>
        )}
        <span className="ml-auto shrink-0 text-xs text-faint">{release.date}</span>
      </button>

      {open && (
        <div className="space-y-4 pb-4 pl-7">
          {release.sections.map((section, i) => (
            <section key={`${section.heading}-${i}`}>
              {section.heading && (
                <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
                  {section.heading}
                </h4>
              )}
              {section.body.map((paragraph, j) => (
                <p key={j} className="mb-1.5 text-sm text-muted">
                  <Markdown text={paragraph} />
                </p>
              ))}
              {!!section.items.length && (
                <ul className="space-y-1.5">
                  {section.items.map((item, j) => (
                    <li key={j} className="flex gap-2 text-sm text-muted">
                      <span className="text-faint">·</span>
                      <span>
                        <Markdown text={item} />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

function WhatsNew() {
  const { data, isLoading } = useChangelog()

  return (
    <Card
      title="What's new"
      subtitle={
        data?.newer.length
          ? `${data.newer.length} newer release${data.newer.length === 1 ? '' : 's'} available — run \`jobpilot upgrade\``
          : 'Every release, newest first'
      }
    >
      {isLoading ? (
        <SkeletonRows rows={4} />
      ) : !data?.bundled ? (
        <p className="text-sm text-muted">
          The changelog isn't bundled with this install. Read it on{' '}
          <a
            className="text-accent hover:underline"
            href="https://github.com/ashlesh-t/jobpilot/blob/main/CHANGELOG.md"
            target="_blank"
            rel="noreferrer"
          >
            GitHub
          </a>
          .
        </p>
      ) : (
        <div>
          {data.releases.map((release) => (
            <ReleaseEntry key={release.version} release={release} current={data.current} />
          ))}
        </div>
      )}
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* Issues                                                                      */
/* -------------------------------------------------------------------------- */
function FoundAProblem({ about }: { about?: About }) {
  const toast = useToast()

  const copyDiagnostics = async () => {
    if (!about) return
    const lines = [
      `JobPilot ${about.version} (${about.install_source})`,
      `Platform: ${about.platform}`,
      `Python: ${about.python}`,
      `Database: ${about.db_backend}`,
      ...about.tools.map((t) => `${t.name}: ${t.found ? 'ok' : 'missing'} — ${t.detail}`),
    ]
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      toast.success('Diagnostics copied — paste them into the issue.')
    } catch {
      toast.error('Could not copy. Select the details on this page instead.')
    }
  }

  return (
    <Card
      title="Found a problem?"
      subtitle="Bugs get picked up in the next release — a good report is the fastest way there"
    >
      <p className="text-sm text-muted">
        Open an issue with what you expected, what happened, and the diagnostics below. If
        it's reproducible, it gets fixed.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <a
          className="btn-primary"
          href={about?.issues_url ?? 'https://github.com/ashlesh-t/jobpilot/issues/new'}
          target="_blank"
          rel="noreferrer"
        >
          <Bug className="h-4 w-4" />
          Raise an issue
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
        <button
          type="button"
          className="btn-secondary"
          onClick={copyDiagnostics}
          disabled={!about}
        >
          <Copy className="h-4 w-4" />
          Copy diagnostics
        </button>
        <a
          className="btn-ghost"
          href={about?.repo_url ?? 'https://github.com/ashlesh-t/jobpilot'}
          target="_blank"
          rel="noreferrer"
        >
          <Github className="h-4 w-4" />
          Source
        </a>
      </div>
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
export function WhoAmI() {
  const { data: about } = useAbout()

  return (
    <>
      <PageHeader title="What JobPilot is" />

      <Hero about={about} />

      <Reveal className="mb-8">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
          Who it's for
        </h3>
        <div className="grid gap-4 md:grid-cols-3">
          {PERSONAS.map((persona) => (
            <Card key={persona.title} title={persona.title}>
              <p className="text-sm text-muted">{persona.body}</p>
            </Card>
          ))}
        </div>
      </Reveal>

      <Reveal className="mb-8">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
          Your JobPilot in numbers
        </h3>
        <YourNumbers />
      </Reveal>

      <Reveal className="mb-8">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
          Under the hood
        </h3>
        <UnderTheHood about={about} />
      </Reveal>

      <Reveal className="mb-8">
        <WhatsNew />
      </Reveal>

      <Reveal className="mb-8">
        <FoundAProblem about={about} />
      </Reveal>
    </>
  )
}
