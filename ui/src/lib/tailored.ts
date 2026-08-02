/** Tailored-resume hooks. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'

export interface TailoredResume {
  id: number
  job_id: string
  folder_name: string
  folder_path: string
  pdf_path: string
  tex_path: string
  has_pdf: boolean
  has_tex: boolean
  ats_before: number | null
  ats_after: number | null
  engine: string
  cost_usd: number
  status: string
  error: string
  meta: Record<string, unknown>
  created_at: string | null
  company: string
  role: string
  score: number
  application_url: string
  message?: string
  files?: { name: string; size: number; suffix: string }[]
  validation?: { ok: boolean; problems: string[]; warnings: string[] }
}

export function useTailored() {
  return useQuery({
    queryKey: ['tailored'],
    queryFn: () =>
      api.get<{ items: TailoredResume[]; count: number; tectonic: boolean }>('/api/tailored'),
  })
}

export function useTailoredDetail(id: number | null) {
  return useQuery({
    queryKey: ['tailored', id],
    queryFn: () => api.get<TailoredResume>(`/api/tailored/${id}`),
    enabled: id != null,
  })
}

export function useTailorJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => api.post<TailoredResume>(`/api/tailored/jobs/${jobId}`),
    onSuccess: (_d, jobId) => {
      qc.invalidateQueries({ queryKey: ['tailored'] })
      qc.invalidateQueries({ queryKey: ['job', jobId] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['cost', 'month'] })
    },
  })
}

export function useDeleteTailored() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.del(`/api/tailored/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tailored'] }),
  })
}
