/** The jobs table: server-side paged, sorted and filtered, with row actions.
 *
 *  Stale jobs are hidden by default — a list padded with expired postings stops being
 *  worth reading, which is the failure mode this whole page exists to avoid. */
import clsx from 'clsx'
import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Search,
  SlidersHorizontal,
  Undo2,
} from 'lucide-react'
import { useState } from 'react'
import { useEffect } from 'react'

import { HelpTip } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import {
  Card,
  Chip,
  EmptyState,
  ErrorState,
  SkeletonRows,
  Toggle,
} from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { formatLpa, relativeTime, scoreTone, truncate } from '@/lib/format'
import { useDebounced, useLocalStorage } from '@/lib/hooks'
import {
  exportUrl,
  useFacets,
  useJobs,
  useMarkApplied,
  useUnmarkApplied,
} from '@/lib/jobs'
import type { Job, JobQuery } from '@/lib/jobs'

const SORTS = [
  { value: 'effective_score', label: 'Best match' },
  { value: 'score', label: 'Match score' },
  { value: 'package', label: 'Package' },
  { value: 'last_seen', label: 'Recently seen' },
  { value: 'company', label: 'Company' },
]

function ScoreCell({ score }: { score: number }) {
  const tone = scoreTone(score)
  return (
    <Chip tone={tone === 'neutral' ? 'neutral' : tone}>
      <span className="tabular-nums">{Math.round(score)}</span>
    </Chip>
  )
}

export function JobsTable({
  scanId,
  onOpen,
}: {
  scanId?: number
  onOpen: (jobId: string) => void
}) {
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [showFilters, setShowFilters] = useLocalStorage('jobpilot.jobs.filters', false)
  const [sort, setSort] = useLocalStorage('jobpilot.jobs.sort', 'effective_score')
  const [order, setOrder] = useLocalStorage<'asc' | 'desc'>('jobpilot.jobs.order', 'desc')
  const [includeStale, setIncludeStale] = useLocalStorage('jobpilot.jobs.stale', false)
  const [unappliedOnly, setUnappliedOnly] = useLocalStorage('jobpilot.jobs.unapplied', false)
  const [source, setSource] = useState('')
  const [minScore, setMinScore] = useState('')
  const [minSalary, setMinSalary] = useState('')

  const debouncedSearch = useDebounced(search, 300)

  // Any filter change invalidates the current page number — page 7 of a 2-page result
  // renders empty and looks like a bug.
  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, sort, order, includeStale, unappliedOnly, source, minScore, minSalary, scanId])

  const query: JobQuery = {
    page,
    page_size: 25,
    sort,
    order,
    search: debouncedSearch || undefined,
    sources: source ? [source] : undefined,
    min_score: minScore ? Number(minScore) : undefined,
    min_salary: minSalary ? Number(minSalary) : undefined,
    include_stale: includeStale || undefined,
    unapplied_only: unappliedOnly || undefined,
    scan_id: scanId,
  }

  const { data, isLoading, isError, error, refetch, isPlaceholderData } = useJobs(query)
  const facets = useFacets()
  const markApplied = useMarkApplied()
  const unmark = useUnmarkApplied()
  const toast = useToast()

  const onApply = async (job: Job) => {
    try {
      await markApplied.mutateAsync({ jobId: job.job_id })
      toast.success(`Marked applied: ${job.role} at ${job.company}`, {
        actionLabel: 'Undo',
        onAction: () => unmark.mutate(job.job_id),
      })
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not mark that applied.')
    }
  }

  const toggleSort = (value: string) => {
    if (sort === value) setOrder(order === 'desc' ? 'asc' : 'desc')
    else {
      setSort(value)
      setOrder('desc')
    }
  }

  const total = data?.total ?? 0

  return (
    <Card
      title="Matches"
      subtitle={
        isLoading ? 'Loading…' : `${total} job${total === 1 ? '' : 's'}${includeStale ? '' : ' still open'}`
      }
      bodyClassName="p-0"
      actions={
        <>
          <button
            type="button"
            className={clsx('btn-ghost btn-sm', showFilters && 'text-accent')}
            onClick={() => setShowFilters(!showFilters)}
          >
            <SlidersHorizontal className="h-3.5 w-3.5" />
            Filters
          </button>
          <a
            href={exportUrl(query, 'csv')}
            className="btn-secondary btn-sm"
            title="Downloads exactly the rows you're looking at"
          >
            <Download className="h-3.5 w-3.5" />
            CSV
            <HelpTip id="jobs.export" />
          </a>
          <a href={exportUrl(query, 'xlsx')} className="btn-secondary btn-sm">
            XLSX
          </a>
        </>
      }
    >
      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
        <div className="relative min-w-[14rem] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-faint" />
          <input
            className="input pl-8"
            placeholder="Search company, role or location"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select
          className="input w-auto"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          aria-label="Sort by"
        >
          {SORTS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn-icon"
          onClick={() => setOrder(order === 'desc' ? 'asc' : 'desc')}
          aria-label={order === 'desc' ? 'Sort ascending' : 'Sort descending'}
        >
          {order === 'desc' ? <ArrowDown className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
        </button>
      </div>

      {showFilters && (
        <div className="flex flex-wrap items-end gap-4 border-b border-line bg-raised/50 px-4 py-3">
          <label className="min-w-[10rem]">
            <span className="label">
              Source <HelpTip id="jobs.source" />
            </span>
            <select
              className="input"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            >
              <option value="">All sources</option>
              {(facets.data?.sources ?? []).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="w-32">
            <span className="label">Min score</span>
            <input
              type="number"
              min={0}
              max={100}
              className="input"
              placeholder="Any"
              value={minScore}
              onChange={(e) => setMinScore(e.target.value)}
            />
          </label>
          <label className="w-36">
            <span className="label">
              Min package (LPA) <HelpTip id="jobs.package" />
            </span>
            <input
              type="number"
              min={0}
              className="input"
              placeholder="Any"
              value={minSalary}
              onChange={(e) => setMinSalary(e.target.value)}
            />
          </label>
          <div className="flex flex-col gap-2 pb-1">
            <Toggle
              checked={unappliedOnly}
              onChange={setUnappliedOnly}
              label={
                <span className="flex items-center gap-1.5">
                  Not applied yet <HelpTip id="jobs.unapplied" />
                </span>
              }
            />
            <Toggle
              checked={includeStale}
              onChange={setIncludeStale}
              label={
                <span className="flex items-center gap-1.5">
                  Include closed <HelpTip id="jobs.stale" />
                </span>
              }
            />
          </div>
        </div>
      )}

      {/* Table */}
      {isLoading ? (
        <div className="p-4">
          <SkeletonRows rows={6} />
        </div>
      ) : isError ? (
        <ErrorState error={error} onRetry={() => refetch()} />
      ) : !data?.items.length ? (
        <EmptyState
          title="No jobs match"
          description={
            total === 0 && !debouncedSearch
              ? 'Once a run finishes, everything it found and scored appears here.'
              : 'Try widening the filters — or turn on "Include closed" to see expired postings.'
          }
        />
      ) : (
        <>
          <div className={clsx('table-wrap border-0', isPlaceholderData && 'opacity-60')}>
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">Role</th>
                  <th className="th">Company</th>
                  <th className="th">Location</th>
                  <th
                    className="th cursor-pointer select-none"
                    onClick={() => toggleSort('score')}
                  >
                    Match
                  </th>
                  <th
                    className="th cursor-pointer select-none"
                    onClick={() => toggleSort('package')}
                  >
                    Package
                  </th>
                  <th className="th">Seen</th>
                  <th className="th text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((job) => (
                  <tr
                    key={job.job_id}
                    className="cursor-pointer transition-colors hover:bg-raised"
                    onClick={() => onOpen(job.job_id)}
                  >
                    <td className="td">
                      <span className="flex items-center gap-2">
                        <span className="font-medium">{truncate(job.role, 46)}</span>
                        {job.is_stale && <Chip tone="neutral">Closed</Chip>}
                        {job.application_status && (
                          <Chip tone="accent">{job.application_status.replace('_', ' ')}</Chip>
                        )}
                      </span>
                    </td>
                    <td className="td text-muted">{truncate(job.company, 24)}</td>
                    <td className="td text-muted">{truncate(job.location || '—', 22)}</td>
                    <td className="td">
                      <ScoreCell score={job.score} />
                    </td>
                    <td className="td tabular-nums text-muted">
                      {job.market_salary ||
                        formatLpa(job.salary_min_lpa, job.salary_max_lpa, '—')}
                    </td>
                    <td className="td text-faint">{relativeTime(job.last_seen)}</td>
                    <td className="td">
                      <div
                        className="flex items-center justify-end gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {job.application_url && (
                          <a
                            href={job.application_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="btn-icon"
                            title="Open the posting"
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </a>
                        )}
                        {job.application_status ? (
                          <button
                            type="button"
                            className="btn-icon"
                            title="Remove the application record"
                            onClick={() => {
                              unmark.mutate(job.job_id)
                              toast.info('Application removed.')
                            }}
                          >
                            <Undo2 className="h-3.5 w-3.5" />
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="btn-icon"
                            title="Mark applied"
                            onClick={() => onApply(job)}
                          >
                            <Check className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data.pages > 1 && (
            <div className="flex items-center justify-between border-t border-line px-4 py-3">
              <p className="text-xs text-muted">
                Page {data.page} of {data.pages}
              </p>
              <div className="flex gap-1">
                <button
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={data.page <= 1}
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                  Previous
                </button>
                <button
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={() => setPage((p) => Math.min(data.pages, p + 1))}
                  disabled={data.page >= data.pages}
                >
                  Next
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </Card>
  )
}
