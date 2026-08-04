/** Telegram job-channel management hooks. Every add is validated live server-side
 *  (see server/routes_telegram_channels.py) — a bad channel is rejected with a 422,
 *  never silently stored. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'

export interface TelegramChannel {
  username: string
  name: string
  members: number
}

const KEY = ['telegram-channels'] as const

export function useTelegramChannels() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => api.get<{ channels: TelegramChannel[] }>('/api/telegram-channels'),
    select: (data) => data.channels,
  })
}

export function useAddTelegramChannel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (username: string) =>
      api.post<{ username: string; valid: boolean }>('/api/telegram-channels', { username }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useRemoveTelegramChannel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (username: string) => api.del(`/api/telegram-channels/${username}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useRevalidateTelegramChannels() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ channels: unknown[] }>('/api/telegram-channels/revalidate'),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}
