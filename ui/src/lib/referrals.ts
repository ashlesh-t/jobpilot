/** Referral-message drafting — draft-only, always. Generating one persists a
 *  `drafted` row; nothing here ever sends anything anywhere. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'

export interface Referral {
  id: number
  job_id: string
  contact_id: number
  message: string
  status: string
  status_history: { status: string; at: string; note: string }[]
  engine: string
  cost_usd: number
  created_at: string | null
  updated_at: string | null
  company: string
  role: string
  contact_name: string
  contact_email: string
}

export function useReferralsForJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ['referrals', 'job', jobId],
    queryFn: () => api.get<{ items: Referral[] }>(`/api/referrals/jobs/${jobId}`),
    select: (data) => data.items,
    enabled: Boolean(jobId),
  })
}

export function useGenerateReferral() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ jobId, contactId }: { jobId: string; contactId: number }) =>
      api.post<Referral>(`/api/referrals/jobs/${jobId}`, { contact_id: contactId }),
    onSuccess: (_d, { jobId }) => {
      qc.invalidateQueries({ queryKey: ['referrals', 'job', jobId] })
      qc.invalidateQueries({ queryKey: ['job', jobId] })
      qc.invalidateQueries({ queryKey: ['cost', 'month'] })
    },
  })
}

export function useSetReferralStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status, jobId }: { id: number; status: string; jobId: string }) =>
      api.patch<Referral>(`/api/referrals/${id}/status`, { status }).then((r) => ({ ...r, jobId })),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['referrals', 'job', result.jobId] })
      qc.invalidateQueries({ queryKey: ['job', result.jobId] })
    },
  })
}
