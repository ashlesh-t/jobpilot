/** Job Hunt — start a run, then watch it step by step.
 *
 *  Each phase is a card you can expand for its logs, and re-run on its own. Stopping is
 *  graceful: the current step finishes, everything done is kept, and Resume picks up from
 *  exactly there. */
import clsx from 'clsx'
import {
  ChevronRight,
  Download,
  ExternalLink,
  Play,
  RotateCcw,
  Square,
  StepForward,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { PageHeader } from '@/components/layout/PageHeader'
import { ResumeManager } from '@/components/resumes/ResumeManager'
import { SetupGate } from '@/components/setup/SetupGate'
import { HelpTip, PageHelp } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import {
  Card,
  EmptyState,
  ErrorState,
  Loading,
  ProgressBar,
  StatusChip,
} from '@/components/ui/primitives'
import { helpFor } from '@/content/help'
import { ApiError } from '@/lib/api'
import { formatDuration, formatTokens, formatUsd, relativeTime } from '@/lib/format'
import {
  usePhaseCatalog,
  useRun,
  useRunControl,
  useRunEvents,
  useRuns,
  useStartRun,
} from '@/lib/hooks'
import type { RunEvent, RunPhase } from '@/lib/hooks'

const MODES = [
  { value: 'auto', label: 'Auto', hint: 'Alternates paid and free sources' },
  { value: 'full', label: 'Full', hint: 'Includes LinkedIn, Naukri, Glassdoor' },
  { value: 'native', label: 'Native', hint: 'Free sources only' },
]

/* -------------------------------------------------------------------------- */
/* Start panel                                                                 */
/* -------------------------------------------------------------------------- */
function StartPanel({ busy }: { busy: boolean }) {
  const [mode, setMode] = useState('auto')
  const start = useStartRun()
  const toast = useToast()
  const navigate = useNavigate()

  const onStart = async () => {
    try {
      const result = await start.mutateAsync({ mode })
      navigate(`/hunt/${result.run_id}`)
    } catch (error) {
      toast.error(
        error instanceof ApiError ? error.detail : 'Could not start the run.',
      )
    }
  }

  return (
    <Card title="Start a hunt" subtitle="Scrapes every source, then scores what it finds">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <span className="label">
            Sources
            <HelpTip id="run.mode" />
          </span>
          <div className="flex rounded-lg border border-line p-0.5">
            {MODES.map((option) => (
              <button
                key={option.value}
                type="button"
                title={option.hint}
                onClick={() => setMode(option.value)}
                className={clsx(
                  'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                  mode === option.value
                    ? 'bg-accent text-accent-ink'
                    : 'text-muted hover:text-ink',
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <button
          type="button"
          className="btn-primary"
          onClick={onStart}
          disabled={busy || start.isPending}
        >
          <Play className="h-4 w-4" />
          {start.isPending ? 'Starting…' : 'Start hunt'}
        </button>

        {busy && (
          <p className="text-sm text-muted">
            A run is already in progress — stop it first, or watch it below.
          </p>
        )}
      </div>
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* Phase card                                                                  */
/* -------------------------------------------------------------------------- */
function PhaseCard({
  phase,
  label,
  helpText,
  logs,
  expanded,
  onToggle,
  onRerun,
  rerunDisabled,
  runId,
}: {
  phase: RunPhase
  label: string
  helpText?: string
  logs: RunEvent[]
  expanded: boolean
  onToggle: () => void
  onRerun: () => void
  rerunDisabled: boolean
  runId: string
}) {
  const artifactName = (phase.artifact as { artifact?: string })?.artifact
  const count = (phase.artifact as { count?: number })?.count

  return (
    <li
      className={clsx(
        'rounded-xl border bg-surface transition-colors',
        phase.status === 'running' ? 'border-accent/50' : 'border-line',
      )}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          type="button"
          onClick={onToggle}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
          aria-expanded={expanded}
        >
          <ChevronRight
            className={clsx(
              'h-4 w-4 shrink-0 text-faint transition-transform',
              expanded && 'rotate-90',
            )}
          />
          <span className="min-w-0">
            <span className="flex items-center gap-1.5">
              <span className="truncate text-sm font-medium text-ink">{label}</span>
              {helpText && <HelpTip text={helpText} />}
            </span>
            <span className="mt-0.5 block text-xs text-faint">
              {count != null ? `${count} jobs · ` : ''}
              {phase.duration_s != null ? formatDuration(phase.duration_s) : '—'}
              {phase.attempt > 1 ? ` · attempt ${phase.attempt}` : ''}
              {phase.cost_usd > 0 ? ` · ${formatUsd(phase.cost_usd)}` : ''}
              {phase.tokens_in + phase.tokens_out > 0
                ? ` · ${formatTokens(phase.tokens_in + phase.tokens_out)} tok`
                : ''}
            </span>
          </span>
        </button>

        <StatusChip status={phase.status} />

        <button
          type="button"
          className="btn-icon"
          title={helpFor('run.rerun')}
          aria-label={`Re-run ${label}`}
          onClick={onRerun}
          disabled={rerunDisabled}
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      </div>

      {expanded && (
        <div className="border-t border-line px-4 py-3">
          {phase.error && (
            <p className="mb-3 rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
              {phase.error}
            </p>
          )}

          {artifactName && (
            <a
              href={`/runs/${runId}/artifacts/${artifactName}`}
              className="btn-secondary btn-sm mb-3"
              download
            >
              <Download className="h-3.5 w-3.5" />
              {artifactName}.json
              <HelpTip id="run.artifact" />
            </a>
          )}

          {logs.length === 0 ? (
            <p className="text-xs text-faint">No output from this step yet.</p>
          ) : (
            <pre className="max-h-72 overflow-auto rounded-lg bg-raised p-3 font-mono text-[11px] leading-relaxed text-muted">
              {logs.map((event) => `${event.msg}`).join('\n')}
            </pre>
          )}
        </div>
      )}
    </li>
  )
}

/* -------------------------------------------------------------------------- */
/* Live run                                                                    */
/* -------------------------------------------------------------------------- */
function RunView({ runId }: { runId: string }) {
  const run = useRun(runId)
  const catalog = usePhaseCatalog()
  const { events } = useRunEvents(runId)
  const control = useRunControl(runId)
  const toast = useToast()
  const [expanded, setExpanded] = useState<string | null>(null)

  const labels = useMemo(() => {
    const map = new Map<string, { label: string; help: string }>()
    for (const phase of catalog.data ?? []) {
      map.set(phase.key, { label: phase.label, help: phase.help })
    }
    return map
  }, [catalog.data])

  // Follow whichever step is currently running, so the user doesn't have to click.
  const running = run.data?.phases.find((p) => p.status === 'running')?.key
  useEffect(() => {
    if (running) setExpanded(running)
  }, [running])

  const logsByPhase = useMemo(() => {
    const map = new Map<string, RunEvent[]>()
    for (const event of events) {
      const key = event.phase_key || event.stage
      if (!key) continue
      const list = map.get(key) ?? []
      list.push(event)
      map.set(key, list)
    }
    return map
  }, [events])

  if (run.isLoading) return <Loading label="Loading run…" />
  if (run.isError) return <ErrorState error={run.error} onRetry={() => run.refetch()} />
  if (!run.data) return null

  const data = run.data
  const isActive = ['running', 'pending', 'waiting_network'].includes(data.status)
  const canResume = ['cancelled', 'error'].includes(data.status)
  const totalTokens = data.tokens_in + data.tokens_out

  const act = async (fn: () => Promise<unknown>, failure: string) => {
    try {
      await fn()
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : failure)
    }
  }

  return (
    <>
      <Card
        className="mb-5"
        title={`Run ${data.id}`}
        subtitle={`${data.mode} · ${data.engine} · started ${relativeTime(data.started_at)}`}
        actions={
          <>
            <StatusChip status={data.status} />
            {isActive && (
              <button
                type="button"
                className="btn-secondary btn-sm"
                title={helpFor('run.stop')}
                onClick={() => act(() => control.stop.mutateAsync(), 'Could not stop the run.')}
                disabled={control.stop.isPending}
              >
                <Square className="h-3.5 w-3.5" />
                Stop
              </button>
            )}
            {canResume && (
              <button
                type="button"
                className="btn-primary btn-sm"
                title={helpFor('run.resume')}
                onClick={() =>
                  act(() => control.resume.mutateAsync(), 'Could not resume the run.')
                }
                disabled={control.resume.isPending}
              >
                <StepForward className="h-3.5 w-3.5" />
                Resume
              </button>
            )}
          </>
        }
      >
        <ProgressBar
          value={data.progress ?? 0}
          tone={data.status === 'error' ? 'danger' : data.status === 'done' ? 'ok' : 'accent'}
        />
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
          <span>{data.summary || 'No results yet'}</span>
          {totalTokens > 0 && <span>{formatTokens(totalTokens)} tokens</span>}
          {data.cost_usd > 0 && <span>{formatUsd(data.cost_usd)}</span>}
        </div>
        {data.error && (
          <p className="mt-3 rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
            {data.error}
          </p>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h3 className="mb-2.5 flex items-center gap-1.5 text-sm font-semibold text-ink">
            Steps
            <HelpTip id="run.phases" />
          </h3>
          <ul className="space-y-2">
            {data.phases.map((phase) => (
              <PhaseCard
                key={phase.key}
                runId={data.id}
                phase={phase}
                label={labels.get(phase.key)?.label ?? phase.key}
                helpText={labels.get(phase.key)?.help}
                logs={logsByPhase.get(phase.key) ?? []}
                expanded={expanded === phase.key}
                onToggle={() =>
                  setExpanded((current) => (current === phase.key ? null : phase.key))
                }
                rerunDisabled={isActive || control.rerun.isPending}
                onRerun={() =>
                  act(
                    () => control.rerun.mutateAsync(phase.key),
                    'Could not re-run that step.',
                  )
                }
              />
            ))}
          </ul>
        </div>

        <Card title="Top matches" subtitle="Best results from this run">
          {!data.top_jobs?.length ? (
            <p className="text-sm text-muted">
              Nothing scored yet — matches appear once the scoring step finishes.
            </p>
          ) : (
            <ul className="space-y-3">
              {data.top_jobs.slice(0, 8).map((job) => (
                <li key={job.job_id} className="min-w-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="truncate text-sm font-medium text-ink">{job.role}</p>
                    <span className="shrink-0 text-xs tabular-nums text-muted">
                      {Math.round(job.score)}
                    </span>
                  </div>
                  <p className="truncate text-xs text-muted">
                    {job.company}
                    {job.location ? ` · ${job.location}` : ''}
                    {job.salary ? ` · ${job.salary}` : ''}
                  </p>
                  {job.url && (
                    <a
                      href={job.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="mt-0.5 inline-flex items-center gap-1 text-xs text-accent hover:underline"
                    >
                      Open posting
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  )
}

/* -------------------------------------------------------------------------- */
export function JobHuntPage() {
  const { runId } = useParams<{ runId: string }>()
  const runs = useRuns(10)
  const navigate = useNavigate()

  const active = runs.data?.active
  const shown = runId ?? active?.id ?? runs.data?.history?.[0]?.id

  return (
    <>
      <PageHeader
        title="Job Hunt"
        description="Start a run and follow it step by step."
      >
        <PageHelp title="Stopping and re-running">
          <p>
            <strong>Stop</strong> lets the current step finish cleanly and keeps everything
            already done. <strong>Resume</strong> continues from the first unfinished step —
            it never re-scrapes work that succeeded.
          </p>
          <p>
            <strong>Re-run</strong> on a single step redoes just that step and the ones that
            depend on it. Re-running scoring, for example, also redoes the salary research
            and the spreadsheet, because their old output no longer matches.
          </p>
        </PageHelp>
      </PageHeader>

      <SetupGate>
        <div className="mb-5">
          <StartPanel busy={Boolean(active)} />
        </div>
      </SetupGate>

      <details className="mb-5 rounded-xl border border-line bg-surface">
        <summary className="cursor-pointer px-5 py-3 text-sm font-medium text-ink">
          Resumes
        </summary>
        <div className="border-t border-line p-5">
          <ResumeManager />
        </div>
      </details>

      {runs.data && (runs.data.history.length > 1 || runId) && (
        <div className="mb-5 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted">Recent:</span>
          {runs.data.history.slice(0, 6).map((run) => (
            <button
              key={run.id}
              type="button"
              onClick={() => navigate(`/hunt/${run.id}`)}
              className={clsx(
                'rounded-full px-2.5 py-1 text-xs font-medium transition-colors',
                run.id === shown
                  ? 'bg-accent-soft text-accent'
                  : 'bg-raised text-muted hover:text-ink',
              )}
            >
              {relativeTime(run.started_at)}
            </button>
          ))}
        </div>
      )}

      {runs.isLoading ? (
        <Loading />
      ) : shown ? (
        <RunView runId={shown} />
      ) : (
        <Card>
          <EmptyState
            title="No runs yet"
            description="Start your first hunt above. It usually takes a few minutes, and you can watch every step as it happens."
          />
        </Card>
      )}
    </>
  )
}
