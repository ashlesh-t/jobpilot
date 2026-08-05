/** Telegram job-channel management.
 *
 *  Every add is checked live against the public t.me/s/<channel> page before it's
 *  stored — never a guess. There's no automated discovery (t.me/s/ has no public
 *  search), so growing the list is a manual add, one channel at a time. */
import clsx from 'clsx'
import { CircleCheck, Plus, RefreshCw, X } from 'lucide-react'
import { useState } from 'react'

import { HelpTip } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import { Card, SkeletonRows } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import {
  useAddTelegramChannel,
  useRemoveTelegramChannel,
  useRevalidateTelegramChannels,
  useTelegramChannels,
} from '@/lib/telegramChannels'

export function TelegramChannelsPanel() {
  const { data: channels, isLoading } = useTelegramChannels()
  const [draft, setDraft] = useState('')
  const add = useAddTelegramChannel()
  const remove = useRemoveTelegramChannel()
  const revalidate = useRevalidateTelegramChannels()
  const toast = useToast()

  const onAdd = async () => {
    const username = draft.trim().replace(/^@/, '')
    if (!username) return
    try {
      await add.mutateAsync(username)
      toast.success(`@${username} is live — added.`)
      setDraft('')
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not add that channel.')
    }
  }

  const onRemove = async (username: string) => {
    try {
      await remove.mutateAsync(username)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not remove that channel.')
    }
  }

  const onRevalidate = async () => {
    try {
      const result = await revalidate.mutateAsync()
      const deadCount = result.channels.length - (channels?.length ?? 0)
      toast.success(
        deadCount < 0
          ? `Rechecked — dropped ${-deadCount} dead channel${-deadCount === 1 ? '' : 's'}.`
          : 'Rechecked — every channel is still live.',
      )
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not recheck channels.')
    }
  }

  return (
    <Card
      title="Telegram channels"
      subtitle="Public job-posting channels the scraper reads — each one checked live before it's added"
      actions={
        <button
          type="button"
          className="btn-secondary btn-sm"
          onClick={onRevalidate}
          disabled={revalidate.isPending}
        >
          <RefreshCw className={clsx('h-3.5 w-3.5', revalidate.isPending && 'animate-spin')} />
          Recheck all
        </button>
      }
    >
      {isLoading ? (
        <SkeletonRows rows={3} />
      ) : (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {channels?.map((ch) => (
            <span key={ch.username} className="chip-neutral">
              <CircleCheck className="h-3 w-3 text-ok" />
              @{ch.username}
              <button
                type="button"
                onClick={() => onRemove(ch.username)}
                className="text-faint hover:text-danger"
                aria-label={`Remove @${ch.username}`}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          {!channels?.length && (
            <span className="text-xs text-faint">No channels configured yet.</span>
          )}
        </div>
      )}

      <div className="flex gap-2">
        <input
          className="input"
          placeholder="channel username, e.g. getjobss"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              onAdd()
            }
          }}
        />
        <button
          type="button"
          className="btn-secondary"
          onClick={onAdd}
          disabled={!draft.trim() || add.isPending}
        >
          <Plus className="h-4 w-4" />
          {add.isPending ? 'Checking…' : 'Add'}
        </button>
      </div>
      <p className="mt-2 flex items-center gap-1 text-xs text-faint">
        Checked against the public channel page before it's saved — an invalid or
        private channel is rejected immediately, never silently stored.
        <HelpTip text="There's no automated discovery — Telegram has no public search API for this — so add channels you already know about, one at a time." />
      </p>
    </Card>
  )
}
