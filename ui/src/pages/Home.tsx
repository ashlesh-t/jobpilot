/** Home — the dashboard. What JobPilot found, how it's going, and what needs attention. */
import {
  ArrowRight,
  Briefcase,
  CheckCircle2,
  CircleAlert,
  Coins,
  Download,
  MessageSquare,
  Play,
  Sparkles,
  Stethoscope,
  Target,
  TrendingUp,
  XCircle,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import {
  ApplicationFunnel,
  JobsPerScan,
  ScoreDistribution,
  SourceBreakdown,
} from '@/components/charts/Charts'
import { JobDetail } from '@/components/jobs/JobDetail'
import { JobsTable } from '@/components/jobs/JobsTable'
import { PageHeader } from '@/components/layout/PageHeader'
import { HelpTip, PageHelp } from '@/components/ui/Help'
import {
  Card,
  EmptyState,
  ErrorState,
  ProgressBar,
  SkeletonRows,
  StatusChip,
} from '@/components/ui/primitives'
import { formatTokens, formatUsd, relativeTime } from '@/lib/format'
import { useDoctor, useRuns } from '@/lib/hooks'
import { useJobStats, useScans } from '@/lib/jobs'
import type { DoctorRow } from '@/lib/hooks'

/* -------------------------------------------------------------------------- */
/* KPI row — headline numbers, so stat tiles rather than a chart                */
/* -------------------------------------------------------------------------- */
function StatTile({
  label,
  value,
  hint,
  helpId,
  icon: Icon,
}: {
  label: string
  value: string | number
  hint?: string
  helpId?: string
  icon: LucideIcon
}) {
  return (
    <div className="stat-tile">
      <div className="stat-tile-icon">
        <Icon className="h-5 w-5" />
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <p className="stat-tile-label uppercase tracking-wide">{label}</p>
          {helpId && <HelpTip id={helpId} />}
        </div>
        <p className="stat-tile-value">{value}</p>
        {hint && <p className="mt-0.5 truncate text-xs text-faint">{hint}</p>}
      </div>
    </div>
  )
}

function KpiRow() {
  const { data, isLoading } = useJobStats()

  if (isLoading || !data) {
    return (
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="card flex items-center gap-4 p-4">
            <div className="skeleton h-11 w-11 shrink-0 rounded-xl" />
            <div className="min-w-0 flex-1">
              <div className="skeleton h-3 w-20" />
              <div className="skeleton mt-3 h-7 w-14" />
            </div>
          </div>
        ))}
      </div>
    )
  }

  const cost = data.cost_month
  const spend =
    cost.usd > 0
      ? formatUsd(cost.usd)
      : cost.subscription_tokens > 0
        ? formatTokens(cost.subscription_tokens)
        : '—'

  return (
    <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
      <StatTile
        icon={Briefcase}
        label="Open matches"
        value={data.fresh}
        hint={data.stale ? `${data.stale} closed and hidden` : 'All still open'}
        helpId="jobs.stale"
      />
      <StatTile
        icon={Target}
        label="Strong matches"
        value={data.high_match}
        hint="Scoring 75 or above"
        helpId="score.match"
      />
      <StatTile
        icon={TrendingUp}
        label="Average score"
        value={data.avg_score || '—'}
        hint="Across all scored jobs"
      />
      <StatTile
        icon={Sparkles}
        label="Applied"
        value={data.funnel.in_flight}
        hint={`${data.funnel.total} total, ${data.funnel.in_flight} still live`}
        helpId="applications.funnel"
      />
      <StatTile
        icon={MessageSquare}
        label="Interviews"
        value={
          data.funnel.stages.find((s) => s.stage === 'interview')?.count ?? 0
        }
        hint="Reached interview or beyond"
      />
      <StatTile
        icon={Coins}
        label="Cost this month"
        value={spend}
        hint={cost.usd > 0 ? 'Metered API usage' : 'Subscription — no per-token charge'}
        helpId="cost.meter"
      />
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Health                                                                      */
/* -------------------------------------------------------------------------- */
function HealthSummary({ rows }: { rows: DoctorRow[] }) {
  const problems = rows.filter((r) => r.status !== 'ok')
  if (!problems.length) {
    return (
      <div className="flex items-center gap-2 text-sm text-ok">
        <CheckCircle2 className="h-4 w-4" />
        Everything checks out.
      </div>
    )
  }
  return (
    <ul className="space-y-2">
      {problems
        // Failures first — a warning can wait, a failure is why something isn't working.
        .sort((a, b) => Number(b.status === 'fail') - Number(a.status === 'fail'))
        .slice(0, 5)
        .map((row) => (
          <li key={row.name} className="flex items-start gap-2.5 text-sm">
            {row.status === 'fail' ? (
              <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
            ) : (
              <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
            )}
            <span className="min-w-0">
              <span className="font-medium text-ink">{row.name}</span>
              <span className="text-muted"> — {row.detail}</span>
            </span>
          </li>
        ))}
    </ul>
  )
}

/* -------------------------------------------------------------------------- */
/* Scans                                                                       */
/* -------------------------------------------------------------------------- */
function ScanList({ onFilter }: { onFilter: (scanId: number | undefined) => void }) {
  const { data: scans, isLoading } = useScans(12)
  const [selected, setSelected] = useState<number | undefined>()

  if (isLoading) return <SkeletonRows rows={4} />
  if (!scans?.length) {
    return (
      <p className="text-sm text-muted">
        Each completed run records a scan here, with its own download.
      </p>
    )
  }

  return (
    <ul className="-mx-2 space-y-0.5">
      {scans.map((scan) => (
        <li key={scan.id}>
          <div
            className={`flex items-center gap-2 rounded-lg px-2 py-2 transition-colors ${
              selected === scan.id ? 'bg-accent-soft' : 'hover:bg-raised'
            }`}
          >
            <button
              type="button"
              className="min-w-0 flex-1 text-left"
              onClick={() => {
                const next = selected === scan.id ? undefined : scan.id
                setSelected(next)
                onFilter(next)
              }}
            >
              <p className="truncate text-sm text-ink">
                {scan.jobs_scored} scored
                {scan.jobs_new ? ` · ${scan.jobs_new} new` : ''}
              </p>
              <p className="text-xs text-faint">
                {relativeTime(scan.started_at)} · {scan.mode}
              </p>
            </button>
            <a
              href={`/api/scans/${scan.id}/export?format=xlsx`}
              className="btn-icon shrink-0"
              title="Download this scan as a spreadsheet"
              onClick={(e) => e.stopPropagation()}
            >
              <Download className="h-3.5 w-3.5" />
            </a>
          </div>
        </li>
      ))}
    </ul>
  )
}

/* -------------------------------------------------------------------------- */
export function HomePage() {
  const runs = useRuns(6)
  const doctor = useDoctor(false)
  const stats = useJobStats()
  const scans = useScans(20)
  const [openJob, setOpenJob] = useState<string | null>(null)
  const [scanFilter, setScanFilter] = useState<number | undefined>()

  const active = runs.data?.active ?? null
  const history = runs.data?.history ?? []

  return (
    <>
      <PageHeader
        title="Home"
        description="Everything JobPilot has found, and how your applications are going."
        actions={
          <Link to="/hunt" className="btn-primary btn-sm">
            <Play className="h-3.5 w-3.5" />
            Start a hunt
          </Link>
        }
      >
        <PageHelp title="How JobPilot works">
          <p>
            A <strong>run</strong> scrapes every configured job source, filters out what
            doesn't fit, then reads and scores what's left against your resume. It finishes
            by building a spreadsheet and sending you a digest.
          </p>
          <p>
            Everything below is drawn from your own database — nothing leaves this machine.
            Closed and expired postings are hidden by default so the list stays worth reading.
          </p>
        </PageHelp>
      </PageHeader>

      {active && (
        <Card
          className="mb-6 border-accent/40"
          title="A run is in progress"
          subtitle={`Started ${relativeTime(active.started_at)} · ${active.engine}`}
          actions={
            <Link to={`/hunt/${active.id}`} className="btn-secondary btn-sm">
              Watch it
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          }
        >
          <ProgressBar value={active.progress ?? 0} />
          <p className="mt-2 text-xs text-muted">
            {active.phases.filter((p) => p.status === 'done').length} of{' '}
            {active.phases.length} steps complete
          </p>
        </Card>
      )}

      <KpiRow />

      {stats.isError ? (
        <Card className="mb-6">
          <ErrorState error={stats.error} onRetry={() => stats.refetch()} />
        </Card>
      ) : (
        <div className="mb-6 grid gap-5 lg:grid-cols-2">
          <Card
            title="Match scores"
            subtitle="How many jobs fall in each band"
            bodyClassName="px-3 pb-3 pt-1"
          >
            <ScoreDistribution buckets={stats.data?.score_buckets ?? []} />
          </Card>

          <Card
            title="Jobs scored per run"
            subtitle="Your last two weeks of runs"
            bodyClassName="px-3 pb-3 pt-1"
          >
            <JobsPerScan scans={scans.data ?? []} />
          </Card>

          <Card
            title="Where jobs came from"
            subtitle="Across every scan"
            bodyClassName="px-3 pb-3 pt-1"
          >
            <SourceBreakdown sources={stats.data?.by_source ?? []} />
          </Card>

          <Card
            title="Application funnel"
            subtitle="Reaching a stage counts for every earlier one"
            bodyClassName="px-3 pb-3 pt-1"
            actions={<HelpTip id="applications.funnel" />}
          >
            <ApplicationFunnel stages={stats.data?.funnel.stages ?? []} />
          </Card>
        </div>
      )}

      <div className="mb-6">
        <JobsTable scanId={scanFilter} onOpen={setOpenJob} />
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card
          title="Previous scans"
          subtitle="Click one to filter the table above"
          className="lg:col-span-1"
        >
          <ScanList onFilter={setScanFilter} />
        </Card>

        <Card title="Recent runs" className="lg:col-span-1" bodyClassName="p-2">
          {runs.isLoading ? (
            <div className="p-3">
              <SkeletonRows rows={3} />
            </div>
          ) : !history.length ? (
            <EmptyState
              title="No runs yet"
              description="Start your first hunt to fill this dashboard."
            />
          ) : (
            <div className="space-y-0.5">
              {history.map((run) => (
                <Link
                  key={run.id}
                  to={`/hunt/${run.id}`}
                  className="flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-raised"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-ink">
                      {run.summary || `${run.mode} run`}
                    </p>
                    <p className="text-xs text-faint">{relativeTime(run.started_at)}</p>
                  </div>
                  <StatusChip status={run.status} />
                </Link>
              ))}
            </div>
          )}
        </Card>

        <Card
          title="System health"
          className="lg:col-span-1"
          actions={
            <Link to="/me" className="btn-ghost btn-sm">
              <Stethoscope className="h-3.5 w-3.5" />
              Details
            </Link>
          }
        >
          {doctor.isLoading ? (
            <SkeletonRows rows={3} />
          ) : doctor.isError ? (
            <ErrorState error={doctor.error} onRetry={() => doctor.refetch()} />
          ) : (
            <HealthSummary rows={doctor.data?.rows ?? []} />
          )}
        </Card>
      </div>

      <JobDetail jobId={openJob} onClose={() => setOpenJob(null)} />
    </>
  )
}
