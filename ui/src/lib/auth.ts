/** Session/account hooks. Mirrors the shape of settings.ts: typed interfaces + a
 *  query-key factory + paired query/mutation hooks over @tanstack/react-query.
 *
 *  `GET /api/auth/me` 401s when nobody is signed in — that's an expected, steady-state
 *  result, not a transient failure, so `useCurrentUser` disables retries and callers
 *  distinguish "loading" / "signed out" / "signed in" off `isLoading` and `isError`
 *  (a 401 surfaces as `ApiError` with `status === 401` via `error`). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'

export interface User {
  id: string | number
  username: string
  email: string | null
  is_admin: boolean
  must_set_password: boolean
  created_at: string
  last_login_at: string | null
}

export const authKeys = {
  me: ['auth', 'me'] as const,
}

export function useCurrentUser() {
  return useQuery({
    queryKey: authKeys.me,
    queryFn: () => api.get<User>('/api/auth/me'),
    // A 401 here just means "not signed in" — retrying it, or treating it the same
    // as a network blip, would make RequireAuth flash a loading state forever.
    retry: false,
  })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      api.post<User>('/api/auth/login', body),
    onSuccess: (user) => {
      qc.setQueryData(authKeys.me, user)
      qc.invalidateQueries({ queryKey: authKeys.me })
    },
  })
}

export function useSignup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { username: string; password: string; email?: string }) =>
      api.post<User>('/api/auth/signup', body),
    onSuccess: (user) => {
      qc.setQueryData(authKeys.me, user)
      qc.invalidateQueries({ queryKey: authKeys.me })
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean }>('/api/auth/logout'),
    onSuccess: () => {
      // Every other cached query belongs to the account that just signed out.
      qc.clear()
    },
  })
}

export function useClaimLegacy() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      api.post<User>('/api/auth/claim', body),
    onSuccess: (user) => {
      qc.setQueryData(authKeys.me, user)
      qc.invalidateQueries({ queryKey: authKeys.me })
    },
  })
}
