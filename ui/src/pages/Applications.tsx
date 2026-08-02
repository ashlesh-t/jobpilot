/** Applications — every job you've applied to, from first application to an offer.
 *
 *  Board and table are two views of the same rows. Every status change is dated and
 *  appended to a history, so "how long did that take?" is always answerable. */
import clsx from 'clsx'
import {
  Clock,
  ExternalLink,
  LayoutGrid,
  ListOrdered,
  Rows3,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { ApplicationFunnel } from '@/components/charts/Charts'
import { PageHeader } from '@/components/layout/PageHeader'
import { HelpTip, PageHelp } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import {
  Card,
  Chip,
  Dialog,
  EmptyState,
  SkeletonRows,
  StatusChip,
} from '@/components/ui/primitives'
import { ApiError, api } from '@/lib/api'
import { formatDate, relativeTime } from '@/lib/format'
import { useLocalStorage } from '@/lib/hooks'
import { useSetApplicationStatus, useUnmarkApplied } from '@/lib/jobs'
import type { Application } from '@/lib/jobs'

const PIPELINE = ['applied', 'selected', 'interview', 'final_round', 'placed'] as const
const TERMINAL = ['rejected', 'ghosted'] as const

const LABELS: Record<string, string> = {
  applied: 'Applied',
  selected: 'Shortlisted',
  interview: 'Interview',
  final_round: 'Final round',
  placed: 'Offer',
  rejected: 'Rejected',
  ghosted: 'No reply',
}

interface BoardPayload {
  columns: Record<string, Application[]>
  funnel: {
    total: number
    stages: { stage: string; count: number }[]
    terminal: { stage: string; count: number }[]
    in_flight: number
  }
}

function useBoard() {
  return useQuery({
    queryKey: ['applications', 'board'],
    queryFn: () => api.get<BoardPayload>('/api/applications/board'),
  })
}

function useStale(days = 14) {
  return useQuery({
    queryKey: ['applications', 'stale', days],
    queryFn: () => api.get<{ items: Application[]; days: number }>(
      `/api/applications/stale?days=${days}`),
  })
}

/* -------------------------------------------------------------------------- */
function ApplicationCard({
  application,
  onOpen,
  onMove,
  compact,
}: {
  application: Application
  onOpen: () => void
  onMove: (status: string) => void
  compact?: boolean
}) {
  return (
    <div
      draggable
      onDragStart={(e) => e.dataTransfer.setData('text/plain', application.job_id)}
      onClick={onOpen}
      className="cursor-pointer rounded-lg border border-line bg-surface p-3 transition-colors hover:border-accent/50"
    >
      <p className="truncate text-sm font-medium text-ink">{application.role}</p>
      <p className="truncate text-xs text-muted">
        {application.company}
        {application.location ? ` · ${application.location}` : ''}
      </p>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="text-xs text-faint">
          {application.days_since_update > 13 ? (
            <span className="flex items-center gap-1 text-warn">
              <Clock className="h-3 w-3" />
              {application.days_since_update}d quiet
            </span>
          ) : (
            relativeTime(application.updated_at)
          )}
        </span>
        {!compact && (
          <select
            className="rounded border border-line bg-surface px-1.5 py-0.5 text-[11px] text-muted"
            value={application.status}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => {
              e.stopPropagation()
              onMove(e.target.value)
            }}
            aria-label="Change status"
          >
            {[...PIPELINE, ...TERMINAL].map((s) => (
              <option key={s} value={s}>
                {LABELS[s]}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  )
}

function BoardView({
  columns,
  onOpen,
  onMove,
}: {
  columns: Record<string, Application[]>
  onOpen: (a: Application) => void
  onMove: (jobId: string, status: string) => void
}) {
  const [over, setOver] = useState<string | null>(null)

  return (
    <div className="table-wrap border-0">
      <div className="flex min-w-[60rem] gap-3">
        {[...PIPELINE, ...TERMINAL].map((status) => {
          const items = columns[status] ?? []
          return (
            <div
              key={status}
              onDragOver={(e) => {
                e.preventDefault()
                setOver(status)
              }}
              onDragLeave={() => setOver(null)}
              onDrop={(e) => {
                e.preventDefault()
                setOver(null)
                const jobId = e.dataTransfer.getData('text/plain')
                if (jobId) onMove(jobId, status)
              }}
              className={clsx(
                'w-56 shrink-0 rounded-xl border p-2.5 transition-colors',
                over === status ? 'border-accent bg-accent-soft/40' : 'border-line bg-raised/40',
              )}
            >
              <div className="mb-2.5 flex items-center justify-between px-1">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">
                  {LABELS[status]}
                </span>
                <span className="text-xs tabular-nums text-faint">{items.length}</span>
              </div>
              <div className="space-y-2">
                {items.map((application) => (
                  <ApplicationCard
                    key={application.job_id}
                    application={application}
                    compact
                    onOpen={() => onOpen(application)}
                    onMove={(next) => onMove(application.job_id, next)}
                  />
                ))}
                {!items.length && (
                  <p className="px-1 py-3 text-xs text-faint">Nothing here</p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function TableView({
  applications,
  onOpen,
  onMove,
}: {
  applications: Application[]
  onOpen: (a: Application) => void
  onMove: (jobId: string, status: string) => void
}) {
  return (
    <div className="table-wrap">
      <table className="w-full">
        <thead>
          <tr>
            <th className="th">Role</th>
            <th className="th">Company</th>
            <th className="th">Status</th>
            <th className="th">Applied</th>
            <th className="th">Last change</th>
            <th className="th text-right">Move to</th>
          </tr>
        </thead>
        <tbody>
          {applications.map((a) => (
            <tr
              key={a.job_id}
              className="cursor-pointer hover:bg-raised"
              onClick={() => onOpen(a)}
            >
              <td className="td font-medium">{a.role}</td>
              <td className="td text-muted">{a.company}</td>
              <td className="td">
                <StatusChip status={a.status} />
              </td>
              <td className="td text-muted">{formatDate(a.applied_at)}</td>
              <td className="td text-faint">
                {a.days_since_update > 13 ? (
                  <span className="text-warn">{a.days_since_update} days quiet</span>
                ) : (
                  relativeTime(a.updated_at)
                )}
              </td>
              <td className="td text-right" onClick={(e) => e.stopPropagation()}>
                <select
                  className="input w-auto py-1 text-xs"
                  value={a.status}
                  onChange={(e) => onMove(a.job_id, e.target.value)}
                  aria-label={`Status for ${a.role}`}
                >
                  {[...PIPELINE, ...TERMINAL].map((s) => (
                    <option key={s} value={s}>
                      {LABELS[s]}
                    </option>
                  ))}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ApplicationDetail({
  application,
  onClose,
  onMove,
  onRemove,
}: {
  application: Application | null
  onClose: () => void
  onMove: (status: string) => void
  onRemove: () => void
}) {
  if (!application) return null
  return (
    <Dialog
      open
      onClose={onClose}
      title={application.role}
      subtitle={[application.company, application.location].filter(Boolean).join(' · ')}
      footer={
        <>
          {application.application_url && (
            <a
              href={application.application_url}
              target="_blank"
              rel="noreferrer noopener"
              className="btn-secondary btn-sm"
            >
              Open posting
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => {
              if (window.confirm('Remove this application record? The job stays in your list.')) {
                onRemove()
                onClose()
              }
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Remove
          </button>
        </>
      }
    >
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <StatusChip status={application.status} />
        <select
          className="input w-auto"
          value={application.status}
          onChange={(e) => onMove(e.target.value)}
        >
          {[...PIPELINE, ...TERMINAL].map((s) => (
            <option key={s} value={s}>
              {LABELS[s]}
            </option>
          ))}
        </select>
        <Chip tone="neutral">Match {Math.round(application.score)}</Chip>
      </div>

      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
        History
        <HelpTip id="applications.status" />
      </h3>
      <ol className="space-y-2 border-l border-line pl-4">
        {(application.status_history ?? []).map((entry, i) => (
          <li key={`${entry.at}-${i}`} className="relative text-sm">
            <span className="absolute -left-[1.3rem] top-1.5 h-2 w-2 rounded-full bg-accent" />
            <p className="text-ink">{LABELS[entry.status] ?? entry.status}</p>
            <p className="text-xs text-faint">
              {formatDate(entry.at)}
              {entry.note ? ` — ${entry.note}` : ''}
            </p>
          </li>
        ))}
        {!application.status_history?.length && (
          <li className="text-sm text-faint">No changes recorded yet.</li>
        )}
      </ol>

      {application.notes && (
        <>
          <h3 className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wide text-muted">
            Notes
          </h3>
          <p className="whitespace-pre-wrap text-sm text-muted">{application.notes}</p>
        </>
      )}
    </Dialog>
  )
}

/* -------------------------------------------------------------------------- */
export function ApplicationsPage() {
  const board = useBoard()
  const stale = useStale()
  const setStatus = useSetApplicationStatus()
  const unmark = useUnmarkApplied()
  const toast = useToast()

  const [view, setView] = useLocalStorage<'board' | 'table'>(
    'jobpilot.applications.view',
    'board',
  )
  const [open, setOpen] = useState<Application | null>(null)

  const columns = board.data?.columns ?? {}
  const all = Object.values(columns).flat()
  const funnel = board.data?.funnel

  const move = async (jobId: string, status: string) => {
    try {
      await setStatus.mutateAsync({ jobId, status })
      board.refetch()
      setOpen(null)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not update that.')
    }
  }

  const remove = async (jobId: string) => {
    try {
      await unmark.mutateAsync(jobId)
      board.refetch()
      toast.info('Application removed — the job is back in your unapplied list.')
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not remove that.')
    }
  }

  return (
    <>
      <PageHeader
        title="Applications"
        description="Every job you've applied to, and where each one actually stands."
        actions={
          <div className="flex rounded-lg border border-line p-0.5">
            <button
              type="button"
              onClick={() => setView('board')}
              className={clsx(
                'rounded-md px-2.5 py-1.5 text-xs font-medium',
                view === 'board' ? 'bg-accent text-accent-ink' : 'text-muted hover:text-ink',
              )}
            >
              <LayoutGrid className="mr-1 inline h-3.5 w-3.5" />
              Board
            </button>
            <button
              type="button"
              onClick={() => setView('table')}
              className={clsx(
                'rounded-md px-2.5 py-1.5 text-xs font-medium',
                view === 'table' ? 'bg-accent text-accent-ink' : 'text-muted hover:text-ink',
              )}
            >
              <Rows3 className="mr-1 inline h-3.5 w-3.5" />
              Table
            </button>
          </div>
        }
      >
        <PageHelp title="How this works">
          <p>
            Mark a job applied from Home, and it appears here. Drag a card between columns
            (or use the dropdown) as things progress — every change is dated, so you can
            see how long each stage took.
          </p>
          <p>
            Removing an application deletes only the record; the job goes back to your
            unapplied list.
          </p>
        </PageHelp>
      </PageHeader>

      {funnel && funnel.total > 0 && (
        <div className="mb-5 grid gap-5 lg:grid-cols-3">
          <Card
            title="Funnel"
            subtitle="Reaching a stage counts for every earlier one"
            className="lg:col-span-2"
            bodyClassName="px-3 pb-3 pt-1"
          >
            <ApplicationFunnel stages={funnel.stages} />
          </Card>
          <Card title="At a glance">
            <dl className="space-y-3 text-sm">
              <div className="flex justify-between">
                <dt className="text-muted">Applications</dt>
                <dd className="tabular-nums text-ink">{funnel.total}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-muted">Still live</dt>
                <dd className="tabular-nums text-ink">{funnel.in_flight}</dd>
              </div>
              {funnel.terminal.map((t) => (
                <div key={t.stage} className="flex justify-between">
                  <dt className="text-muted">{LABELS[t.stage]}</dt>
                  <dd className="tabular-nums text-ink">{t.count}</dd>
                </div>
              ))}
              {stale.data?.items.length ? (
                <div className="flex items-center justify-between border-t border-line pt-3">
                  <dt className="flex items-center gap-1.5 text-warn">
                    Gone quiet <HelpTip id="applications.stale" />
                  </dt>
                  <dd className="tabular-nums text-warn">{stale.data.items.length}</dd>
                </div>
              ) : null}
            </dl>
          </Card>
        </div>
      )}

      <Card bodyClassName={view === 'board' ? 'p-3' : 'p-0'}>
        {board.isLoading ? (
          <div className="p-3">
            <SkeletonRows rows={5} />
          </div>
        ) : !all.length ? (
          <EmptyState
            icon={<ListOrdered className="h-5 w-5" />}
            title="No applications yet"
            description="Mark a job applied from Home and it'll show up here."
          />
        ) : view === 'board' ? (
          <BoardView columns={columns} onOpen={setOpen} onMove={move} />
        ) : (
          <TableView
            applications={[...all].sort((a, b) =>
              (b.updated_at ?? '').localeCompare(a.updated_at ?? ''),
            )}
            onOpen={setOpen}
            onMove={move}
          />
        )}
      </Card>

      <ApplicationDetail
        application={open}
        onClose={() => setOpen(null)}
        onMove={(status) => open && move(open.job_id, status)}
        onRemove={() => open && remove(open.job_id)}
      />
    </>
  )
}
