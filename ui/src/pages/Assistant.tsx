/** Assistant — ask about your own jobs, scores and runs.
 *
 *  Read-only on purpose: it explains, it doesn't act. Anything that changes state stays
 *  behind the button that already does it, where you can see what you're agreeing to. */
import clsx from 'clsx'
import { Eraser, Send, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { PageHeader } from '@/components/layout/PageHeader'
import { PageHelp } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import { Card, EmptyState, Spinner } from '@/components/ui/primitives'
import { ApiError, api } from '@/lib/api'
import { formatUsd, relativeTime } from '@/lib/format'

interface Message {
  role: string
  content: string
  at: string
}

const SUGGESTIONS = [
  'Which of my matches should I apply to first, and why?',
  'What skills keep coming up that my profile is missing?',
  'Why did my last run find fewer jobs than usual?',
  'How is my application funnel actually going?',
]

export function AssistantPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const [draft, setDraft] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  const history = useQuery({
    queryKey: ['chat'],
    queryFn: () => api.get<{ messages: Message[] }>('/api/chat'),
  })

  const ask = useMutation({
    mutationFn: (message: string) =>
      api.post<{ answer: string; usd: number; messages: Message[] }>('/api/chat', { message }),
    onSuccess: (data) => {
      qc.setQueryData(['chat'], { messages: data.messages })
      qc.invalidateQueries({ queryKey: ['cost', 'month'] })
    },
  })

  const clear = useMutation({
    mutationFn: () => api.del('/api/chat'),
    onSuccess: () => qc.setQueryData(['chat'], { messages: [] }),
  })

  const messages = history.data?.messages ?? []

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, ask.isPending])

  const send = async (text: string) => {
    const message = text.trim()
    if (!message || ask.isPending) return
    setDraft('')
    try {
      await ask.mutateAsync(message)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'The assistant could not answer.')
    }
  }

  return (
    <>
      <PageHeader
        title="Assistant"
        description="Ask about your jobs, your scores, or anything a run did."
        actions={
          messages.length > 0 && (
            <button
              type="button"
              className="btn-ghost btn-sm"
              onClick={() => clear.mutate()}
              disabled={clear.isPending}
            >
              <Eraser className="h-3.5 w-3.5" />
              Clear
            </button>
          )
        }
      >
        <PageHelp title="What it can and can't do">
          <p>
            The assistant sees your real data — profile, preferences, top matches, your
            application funnel and recent runs — so it can answer specifically rather than
            generically.
          </p>
          <p>
            It can't change anything. If you want a run started or a resume tailored, it
            will point you at the page that does it. Each answer costs tokens and shows up
            in the cost meter.
          </p>
        </PageHelp>
      </PageHeader>

      <Card bodyClassName="p-0">
        <div className="max-h-[58vh] min-h-[22rem] overflow-y-auto px-5 py-4">
          {messages.length === 0 ? (
            <EmptyState
              icon={<Sparkles className="h-5 w-5" />}
              title="Ask anything about your job hunt"
              description={
                <div className="mt-3 flex flex-col gap-1.5">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="rounded-lg border border-line px-3 py-2 text-left text-sm text-muted transition-colors hover:border-accent/50 hover:text-ink"
                      onClick={() => send(s)}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              }
            />
          ) : (
            <div className="space-y-4">
              {messages.map((m, i) => (
                <div
                  key={`${m.at}-${i}`}
                  className={clsx('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}
                >
                  <div
                    className={clsx(
                      'max-w-[85%] rounded-2xl px-4 py-2.5',
                      m.role === 'user'
                        ? 'bg-accent text-accent-ink'
                        : 'border border-line bg-raised text-ink',
                    )}
                  >
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">{m.content}</p>
                    <p
                      className={clsx(
                        'mt-1 text-[11px]',
                        m.role === 'user' ? 'text-accent-ink/70' : 'text-faint',
                      )}
                    >
                      {relativeTime(m.at)}
                    </p>
                  </div>
                </div>
              ))}
              {ask.isPending && (
                <div className="flex justify-start">
                  <div className="flex items-center gap-2 rounded-2xl border border-line bg-raised px-4 py-2.5 text-sm text-muted">
                    <Spinner />
                    Reading your data…
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>
          )}
        </div>

        <form
          className="flex items-end gap-2 border-t border-line px-4 py-3"
          onSubmit={(e) => {
            e.preventDefault()
            send(draft)
          }}
        >
          <textarea
            className="input min-h-[2.5rem] resize-none"
            rows={1}
            placeholder="Ask about a job, a score, or a run…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send(draft)
              }
            }}
          />
          <button
            type="submit"
            className="btn-primary"
            disabled={!draft.trim() || ask.isPending}
          >
            <Send className="h-4 w-4" />
          </button>
        </form>
        {ask.data?.usd ? (
          <p className="px-4 pb-3 text-right text-[11px] text-faint">
            Last answer: {formatUsd(ask.data.usd)}
          </p>
        ) : null}
      </Card>
    </>
  )
}
