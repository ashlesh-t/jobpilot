/** Job / application / scan data hooks. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, qs } from './api'

export interface Job {
  job_id: string
  company: string
  role: string
  location: string
  source_board: string
  application_url: string
  apply_type: string
  jd_full: string
  experience_req: string
  exp_req_years: number | null
  posted_date: string
  last_date: string
  score: number
  keyword_score: number
  semantic_score: number
  effective_score: number
  location_weight: number
  bar_fit: number
  learning_adj: number
  score_confidence: string
  matched_skills: string[]
  missing_skills: string[]
  archetype: string
  prep_focus: string
  gap_signals: string
  market_salary: string
  your_demand: string
  salary_source: string
  salary_min_lpa: number | null
  salary_max_lpa: number | null
  scan_id: number | null
  first_seen: string | null
  last_seen: string | null
  is_stale: boolean
  application_status: string | null
  applied_at: string | null
  tailored_count: number
  tailored_folder: string
  tailored?: {
    id: number
    folder_name: string
    pdf_path: string
    tex_path: string
    created_at: string
    ats_before: number | null
    ats_after: number | null
    status: string
  }[]
  contacts?: {
    id: number
    company: string
    name: string
    email: string
    role: string
  }[]
  referrals?: {
    id: number
    message: string
    status: string
    contact_id: number
    contact_name: string
    created_at: string | null
  }[]
}

export interface JobPage {
  items: Job[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface JobFilters {
  search?: string
  sources?: string[]
  locations?: string[]
  archetypes?: string[]
  min_score?: number
  max_score?: number
  min_salary?: number
  max_salary?: number
  scan_id?: number
  include_stale?: boolean
  unapplied_only?: boolean
  applied_only?: boolean
}

export interface JobQuery extends JobFilters {
  page?: number
  page_size?: number
  sort?: string
  order?: 'asc' | 'desc'
}

export interface Facets {
  sources: string[]
  archetypes: string[]
  locations: string[]
  salary_min: number | null
  salary_max: number | null
  sortable: string[]
}

export interface JobStats {
  total: number
  fresh: number
  stale: number
  avg_score: number
  high_match: number
  by_source: { source: string; count: number }[]
  top_companies: { company: string; count: number; avg_score: number }[]
  score_buckets: { range: string; count: number }[]
  tailored: number
  funnel: {
    total: number
    stages: { stage: string; count: number }[]
    terminal: { stage: string; count: number }[]
    in_flight: number
  }
  cost_month: { usd: number; tokens_in: number; tokens_out: number; subscription_tokens: number }
}

export interface Scan {
  id: number
  run_id: string
  started_at: string | null
  ended_at: string | null
  mode: string
  engine: string
  jobs_raw: number
  jobs_after_filter: number
  jobs_scored: number
  jobs_new: number
  report_path: string
}

export interface Application {
  id: number
  job_id: string
  status: string
  applied_at: string | null
  updated_at: string | null
  status_history: { status: string; at: string; note?: string }[]
  notes: string
  days_since_update: number
  company: string
  role: string
  location: string
  score: number
  application_url: string
}

export const jobKeys = {
  list: (query: JobQuery) => ['jobs', query] as const,
  detail: (id: string) => ['job', id] as const,
  facets: ['job-facets'] as const,
  stats: ['job-stats'] as const,
  scans: ['scans'] as const,
}

export function useJobs(query: JobQuery) {
  return useQuery({
    queryKey: jobKeys.list(query),
    queryFn: () => api.get<JobPage>(`/api/jobs${qs(query as Record<string, unknown>)}`),
    placeholderData: (previous) => previous, // keeps the table steady while paging
  })
}

export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: jobKeys.detail(jobId ?? ''),
    queryFn: () => api.get<Job>(`/api/jobs/${jobId}`),
    enabled: Boolean(jobId),
  })
}

export function useFacets() {
  return useQuery({
    queryKey: jobKeys.facets,
    queryFn: () => api.get<Facets>('/api/jobs/facets'),
    staleTime: 60_000,
  })
}

export function useJobStats() {
  return useQuery({
    queryKey: jobKeys.stats,
    queryFn: () => api.get<JobStats>('/api/jobs/stats'),
  })
}

export function useScans(limit = 30) {
  return useQuery({
    queryKey: jobKeys.scans,
    queryFn: () => api.get<{ scans: Scan[] }>(`/api/scans${qs({ limit })}`),
    select: (data) => data.scans,
  })
}

export function useApplications(status?: string) {
  return useQuery({
    queryKey: ['applications', status ?? 'all'],
    queryFn: () =>
      api.get<{ items: Application[]; statuses: string[]; pipeline: string[]; terminal: string[] }>(
        `/api/applications${qs({ status })}`,
      ),
  })
}

/** Invalidate everything a change to one job can affect. */
function useJobInvalidation() {
  const qc = useQueryClient()
  return (jobId?: string) => {
    qc.invalidateQueries({ queryKey: ['jobs'] })
    qc.invalidateQueries({ queryKey: jobKeys.stats })
    qc.invalidateQueries({ queryKey: ['applications'] })
    if (jobId) qc.invalidateQueries({ queryKey: jobKeys.detail(jobId) })
  }
}

export function useMarkApplied() {
  const invalidate = useJobInvalidation()
  return useMutation({
    mutationFn: ({ jobId, note = '' }: { jobId: string; note?: string }) =>
      api.post<Application>(`/api/jobs/${jobId}/apply`, { note }),
    onSuccess: (_data, vars) => invalidate(vars.jobId),
  })
}

export function useUnmarkApplied() {
  const invalidate = useJobInvalidation()
  return useMutation({
    mutationFn: (jobId: string) => api.del<{ ok: boolean }>(`/api/jobs/${jobId}/apply`),
    onSuccess: (_data, jobId) => invalidate(jobId),
  })
}

export function useSetApplicationStatus() {
  const invalidate = useJobInvalidation()
  return useMutation({
    mutationFn: ({ jobId, status, note = '' }: { jobId: string; status: string; note?: string }) =>
      api.put<Application>(`/api/jobs/${jobId}/application`, { status, note }),
    onSuccess: (_data, vars) => invalidate(vars.jobId),
  })
}

/** Download URL that carries the exact filters currently on screen. */
export function exportUrl(query: JobQuery, format: 'csv' | 'xlsx'): string {
  const { page, page_size, ...rest } = query
  void page
  void page_size
  return `/api/jobs/export${qs({ ...rest, format } as Record<string, unknown>)}`
}
