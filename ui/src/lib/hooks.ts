/** Shared data hooks. Query keys live here so a mutation elsewhere can invalidate
 *  exactly what it changed rather than blowing away the whole cache. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'

import { api, qs } from './api'

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */
export interface PhaseInfo {
  key: string
  label: string
  help: string
  kind: 'python' | 'llm'
  depends_on: string[]
  inputs: string[]
  output: string | null
  optional: boolean
  always_attempt: boolean
  weight: number
  position: number
  /** Which model tier this phase prefers ("fast" | "reasoning"), null for kind="python". */
  model_tier: string | null
  /** When true, the model dropdown is disabled — this phase always runs on its tier
   *  default regardless of what's configured (see orchestrator.phases). */
  model_locked: boolean
}

export interface ModelOption {
  id: string
  label: string
  tier: string
}

export interface PhaseConfig {
  enabled: boolean
  model: string | null
}

export interface RunPhase {
  key: string
  position: number
  status: string
  attempt: number
  started_at: string | null
  ended_at: string | null
  error: string
  artifact: Record<string, unknown>
  cost_usd: number
  tokens_in: number
  tokens_out: number
  duration_s: number | null
}

export interface Run {
  id: string
  status: string
  mode: string
  engine: string
  trigger: string
  slot_name: string
  started_at: string | null
  ended_at: string | null
  error: string
  summary: string
  cost_usd: number
  tokens_in: number
  tokens_out: number
  phases: RunPhase[]
  progress?: number
  artifacts?: { name: string; path: string; size: number; count: number }[]
  top_jobs?: TopJob[]
  scan?: Scan | null
}

export interface TopJob {
  job_id: string
  company: string
  role: string
  location: string
  score: number
  salary: string
  url: string
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
  tailored_count: number
  report_path: string
  source_counts: Record<string, unknown>
}

export interface RunEvent {
  run_id: string
  seq: number
  ts: string
  phase_key: string
  stage: string
  status: string
  msg: string
  data: Record<string, unknown>
  origin: string
  progress?: number
}

export interface DoctorRow {
  name: string
  category: string
  status: 'ok' | 'warn' | 'fail'
  detail: string
}

/* -------------------------------------------------------------------------- */
/* Query keys                                                                  */
/* -------------------------------------------------------------------------- */
export const keys = {
  phases: ['phases'] as const,
  pipeline: ['pipeline'] as const,
  models: (engine?: string) => ['models', engine ?? 'all'] as const,
  runs: (limit = 50) => ['runs', limit] as const,
  run: (id: string) => ['run', id] as const,
  doctor: (live: boolean) => ['doctor', live] as const,
  config: ['config'] as const,
  engines: ['engines'] as const,
  health: ['health'] as const,
}

/* -------------------------------------------------------------------------- */
/* Hooks                                                                       */
/* -------------------------------------------------------------------------- */
export function usePhaseCatalog() {
  return useQuery({
    queryKey: keys.phases,
    queryFn: () => api.get<{ phases: PhaseInfo[] }>('/phases'),
    staleTime: Infinity, // the catalog only changes when JobPilot itself is upgraded
    select: (data) => data.phases,
  })
}

/** Every phase's saved {enabled, model} — what the next hunt runs with. A phase's
 *  `model: null` means "use this phase's tier default for whichever engine is active". */
export function usePipelineConfig() {
  return useQuery({
    queryKey: keys.pipeline,
    queryFn: () => api.get<{ phases: Record<string, PhaseConfig> }>('/pipeline'),
    select: (data) => data.phases,
  })
}

export function useSavePipelineConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (phases: Record<string, PhaseConfig>) =>
      api.put<{ phases: Record<string, PhaseConfig> }>('/pipeline', { phases }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.pipeline }),
  })
}

/** The selectable models for one engine — dynamic per provider (Claude's
 *  haiku/sonnet/opus vs Gemini's flash/pro), used by the pipeline editor's per-phase
 *  model dropdown. */
export function useModels(engine: string | undefined) {
  return useQuery({
    queryKey: keys.models(engine),
    queryFn: () => api.get<{ models: ModelOption[] }>(`/models${qs({ engine })}`),
    select: (data) => data.models,
    enabled: Boolean(engine),
    staleTime: Infinity,
  })
}

export function useRuns(limit = 25) {
  return useQuery({
    queryKey: keys.runs(limit),
    queryFn: () => api.get<{ active: Run | null; history: Run[] }>(`/runs${qs({ limit })}`),
    // Poll while something is running so the header pill stays honest even on a page
    // that isn't subscribed to the event stream.
    refetchInterval: (query) => (query.state.data?.active ? 3000 : false),
  })
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: keys.run(runId ?? ''),
    queryFn: () => api.get<Run>(`/runs/${runId}`),
    enabled: Boolean(runId),
  })
}

export function useDoctor(live = false, enabled = true) {
  return useQuery({
    queryKey: keys.doctor(live),
    queryFn: () =>
      api.get<{ rows: DoctorRow[]; summary: Record<string, number>; live: boolean }>(
        `/doctor${qs({ live: live || undefined })}`,
      ),
    enabled,
    staleTime: 30_000,
  })
}

export function useConfig() {
  return useQuery({
    queryKey: keys.config,
    queryFn: () => api.get<Record<string, unknown>>('/config'),
  })
}

export function useStartRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { mode?: string; engine?: string; only?: string[]; skip?: string[] }) =>
      api.post<{ run_id: string; status: string }>('/runs', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['runs'] }),
  })
}

export function useRunControl(runId: string | undefined) {
  const qc = useQueryClient()
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['runs'] })
    if (runId) qc.invalidateQueries({ queryKey: keys.run(runId) })
  }
  return {
    stop: useMutation({
      mutationFn: () => api.post<Run>(`/runs/${runId}/stop`),
      onSuccess: invalidate,
    }),
    resume: useMutation({
      mutationFn: () => api.post<Run>(`/runs/${runId}/resume`),
      onSuccess: invalidate,
    }),
    rerun: useMutation({
      mutationFn: (phaseKey: string) =>
        api.post<Run>(`/runs/${runId}/phases/${phaseKey}/rerun`),
      onSuccess: invalidate,
    }),
  }
}

/* -------------------------------------------------------------------------- */
/* Live run events (SSE)                                                       */
/* -------------------------------------------------------------------------- */
export function useRunEvents(runId: string | undefined, { max = 2000 } = {}) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [connected, setConnected] = useState(false)
  const qc = useQueryClient()

  const reset = useCallback(() => setEvents([]), [])

  useEffect(() => {
    if (!runId) return
    setEvents([])
    const source = new EventSource(`/runs/${runId}/events`)

    source.onopen = () => setConnected(true)

    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as RunEvent
        setEvents((list) => {
          const next = [...list, event]
          // Long runs emit thousands of log lines; keeping them all makes the tab
          // sluggish for no benefit.
          return next.length > max ? next.slice(next.length - max) : next
        })
        if (event.stage === 'done' || event.status === 'done') {
          qc.invalidateQueries({ queryKey: keys.run(runId) })
        }
      } catch {
        /* ignore malformed frames */
      }
    }

    source.addEventListener('end', () => {
      setConnected(false)
      source.close()
      qc.invalidateQueries({ queryKey: keys.run(runId) })
      qc.invalidateQueries({ queryKey: ['runs'] })
    })

    source.onerror = () => setConnected(false)

    return () => {
      source.close()
      setConnected(false)
    }
  }, [runId, max, qc])

  return { events, connected, reset }
}

/* -------------------------------------------------------------------------- */
/* Misc                                                                        */
/* -------------------------------------------------------------------------- */
export function useLocalStorage<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value))
    } catch {
      /* storage disabled */
    }
  }, [key, value])

  return [value, setValue] as const
}

export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}
