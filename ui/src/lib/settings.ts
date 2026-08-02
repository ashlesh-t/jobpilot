/** Profile, preferences, credentials, backends and setup-status hooks. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, qs } from './api'

export interface Profile {
  name: string
  email: string
  phone: string
  skills: string[]
  experience_years: number
  roles_held: { title?: string; company?: string; duration?: string }[]
  projects: { name?: string; stack?: string[]; description?: string }[]
  education: { degree?: string; college?: string; year?: string }
  publications: string[]
  graduation_date: string
  github_url: string
  portfolio_url: string
  linkedin_url: string
  interview_readiness: {
    dsa_level: string
    leetcode_url: string
    system_design: string
    spoken_english: string
  }
  locations: string[]
  availability: string
  notice_period_days: number
  profile_verified?: boolean
}

export interface Preferences {
  name: string
  email: string
  locations: string[]
  location_priority: string[]
  remote_ok: boolean
  job_market_focus: string
  target_ctc_min_lpa: number
  role_types: string[]
  experience_years: number
  degree: string
  graduation: string
  availability_date: string
  notice_period_days: number
  preferred_stack: string[]
  linkedin_profile_url: string
  naukri_profile_url: string
  score_threshold: number
  top_n_tailor: number
  top_n_report: number
  stale_after_days: number
  notify_channels: string[]
  engine: { provider: string; model: string; permission_mode: string }
}

export interface SecretEntry {
  key: string
  label: string
  group: string
  help: string
  set: boolean
  masked: string
}

export interface BackendInfo {
  id: string
  label: string
  kind: string
  metered: boolean
  found: boolean
  authenticated: boolean
  ready: boolean
  version: string
  detail: string
  install_hint: string
  auth_hint: string
  experimental: boolean
  checked_deep: boolean
}

export interface SetupCheck {
  ok: boolean
  detail: string
  label: string
  optional?: boolean
}

export interface SetupStatus {
  ready: boolean
  blocking: string[]
  checks: Record<string, SetupCheck>
  setup_complete: boolean
}

export const settingsKeys = {
  profile: ['profile'] as const,
  preferences: ['preferences'] as const,
  secrets: ['secrets'] as const,
  backends: (deep: boolean) => ['backends', deep] as const,
  setup: ['setup-status'] as const,
}

export function useProfile() {
  return useQuery({
    queryKey: settingsKeys.profile,
    queryFn: () =>
      api.get<{ profile: Profile; exists: boolean; verified: boolean }>('/api/profile'),
  })
}

export function useSaveProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { data: Partial<Profile>; verified?: boolean }) =>
      api.put<{ profile: Profile; verified: boolean }>('/api/profile', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: settingsKeys.profile })
      qc.invalidateQueries({ queryKey: settingsKeys.setup })
    },
  })
}

export function useVerifyProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (confirm: boolean) =>
      api.post<{ profile: Profile }>(`/api/profile/verify${qs({ confirm })}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: settingsKeys.profile })
      qc.invalidateQueries({ queryKey: settingsKeys.setup })
    },
  })
}

export function usePreferences() {
  return useQuery({
    queryKey: settingsKeys.preferences,
    queryFn: () =>
      api.get<{ preferences: Preferences; setup_complete: boolean }>('/api/preferences'),
  })
}

export function useSavePreferences() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (preferences: Partial<Preferences>) =>
      api.put<{ preferences: Preferences }>('/api/preferences', { preferences }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: settingsKeys.preferences })
      qc.invalidateQueries({ queryKey: settingsKeys.setup })
    },
  })
}

export function useSecrets() {
  return useQuery({
    queryKey: settingsKeys.secrets,
    queryFn: () => api.get<{ secrets: SecretEntry[] }>('/api/secrets'),
    select: (data) => data.secrets,
  })
}

export function useSaveSecret() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: string }) =>
      api.put<{ key: string; stored_in: string; masked: string }>(
        `/api/secrets/${key}`,
        { value },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: settingsKeys.secrets })
      qc.invalidateQueries({ queryKey: ['doctor'] })
      qc.invalidateQueries({ queryKey: settingsKeys.setup })
    },
  })
}

export function useRevealSecret() {
  return useMutation({
    mutationFn: (key: string) =>
      api.post<{ key: string; value: string }>(`/api/secrets/${key}/reveal`),
  })
}

export function useTestSecret() {
  return useMutation({
    mutationFn: (key: string) =>
      api.post<{ key: string; ok: boolean; detail: string }>(`/api/secrets/${key}/test`),
  })
}

export function useBackends(deep = false) {
  return useQuery({
    queryKey: settingsKeys.backends(deep),
    queryFn: () =>
      api.get<{ backends: BackendInfo[]; selected: string; environment: Record<string, string> }>(
        `/api/backends${qs({ deep: deep || undefined })}`,
      ),
  })
}

export function useSelectBackend() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (backend: string) => api.put('/api/backends', { backend }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['backends'] })
      qc.invalidateQueries({ queryKey: settingsKeys.setup })
      qc.invalidateQueries({ queryKey: ['doctor'] })
    },
  })
}

export function useSetupStatus() {
  return useQuery({
    queryKey: settingsKeys.setup,
    queryFn: () => api.get<SetupStatus>('/api/setup/status'),
  })
}
