/** The credential vault.
 *
 *  Values are masked by default and only ever revealed on an explicit, confirmed click —
 *  the API is built the same way, so a screenshot of this page can't leak a key. */
import clsx from 'clsx'
import { Check, Eye, EyeOff, KeyRound, Loader2, Pencil, X } from 'lucide-react'
import { useState } from 'react'

import { HelpTip } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import { Card, Chip, SkeletonRows } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import {
  useRevealSecret,
  useSaveSecret,
  useSecrets,
  useTestSecret,
} from '@/lib/settings'
import type { SecretEntry } from '@/lib/settings'

const GROUP_TITLES: Record<string, string> = {
  engine: 'AI backend',
  scraping: 'Job sources',
  notify: 'Delivery',
}

const GROUP_ORDER = ['engine', 'scraping', 'notify']

function SecretRow({ secret }: { secret: SecretEntry }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [revealed, setRevealed] = useState<string | null>(null)
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null)

  const save = useSaveSecret()
  const reveal = useRevealSecret()
  const test = useTestSecret()
  const toast = useToast()

  const onSave = async () => {
    if (!draft.trim()) return
    try {
      await save.mutateAsync({ key: secret.key, value: draft })
      toast.success(`${secret.label} saved to your system keyring.`)
      setEditing(false)
      setDraft('')
      setRevealed(null)
      setResult(null)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not save that.')
    }
  }

  const onReveal = async () => {
    if (revealed) {
      setRevealed(null)
      return
    }
    if (!window.confirm(`Show the full ${secret.label} on screen?`)) return
    try {
      const body = await reveal.mutateAsync(secret.key)
      setRevealed(body.value)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not reveal that.')
    }
  }

  const onTest = async () => {
    setResult(null)
    try {
      const body = await test.mutateAsync(secret.key)
      setResult({ ok: body.ok, detail: body.detail })
    } catch (e) {
      setResult({ ok: false, detail: e instanceof ApiError ? e.detail : 'Test failed.' })
    }
  }

  return (
    <li className="border-t border-line py-3 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 text-sm font-medium text-ink">
            {secret.label}
            <HelpTip text={secret.help} />
          </p>
          {editing ? (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <input
                type="password"
                autoFocus
                className="input max-w-md"
                placeholder={`Paste your ${secret.label.toLowerCase()}`}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') onSave()
                  if (e.key === 'Escape') {
                    setEditing(false)
                    setDraft('')
                  }
                }}
              />
              <button
                type="button"
                className="btn-primary btn-sm"
                onClick={onSave}
                disabled={save.isPending || !draft.trim()}
              >
                {save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                Save
              </button>
              <button
                type="button"
                className="btn-ghost btn-sm"
                onClick={() => {
                  setEditing(false)
                  setDraft('')
                }}
              >
                Cancel
              </button>
            </div>
          ) : (
            <p className="mt-0.5 font-mono text-xs text-muted">
              {revealed ?? (secret.set ? secret.masked : 'Not set')}
            </p>
          )}
        </div>

        {!editing && (
          <div className="flex shrink-0 items-center gap-1">
            {secret.set && (
              <>
                <button
                  type="button"
                  className="btn-icon"
                  onClick={onReveal}
                  title={revealed ? 'Hide' : 'Show the full value'}
                  disabled={reveal.isPending}
                >
                  {revealed ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                </button>
                <button
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={onTest}
                  disabled={test.isPending}
                >
                  {test.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                  Test
                </button>
              </>
            )}
            <button
              type="button"
              className="btn-secondary btn-sm"
              onClick={() => setEditing(true)}
            >
              <Pencil className="h-3.5 w-3.5" />
              {secret.set ? 'Replace' : 'Add'}
            </button>
          </div>
        )}
      </div>

      {result && (
        <p
          className={clsx(
            'mt-2 flex items-center gap-1.5 text-xs',
            result.ok ? 'text-ok' : 'text-danger',
          )}
        >
          {result.ok ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}
          {result.detail}
        </p>
      )}
    </li>
  )
}

export function SecretsVault() {
  const { data: secrets, isLoading } = useSecrets()

  const grouped = (secrets ?? []).reduce<Record<string, SecretEntry[]>>((acc, secret) => {
    ;(acc[secret.group] ??= []).push(secret)
    return acc
  }, {})

  return (
    <Card
      title="Keys and tokens"
      subtitle="Stored in your operating system keyring — never in the database, never in a log"
      actions={
        <Chip tone="neutral" icon={<KeyRound className="h-3 w-3" />}>
          <span className="flex items-center gap-1">
            Keyring
            <HelpTip id="secrets.storage" />
          </span>
        </Chip>
      }
    >
      {isLoading ? (
        <SkeletonRows rows={5} />
      ) : (
        <div className="space-y-6">
          {GROUP_ORDER.filter((g) => grouped[g]?.length).map((group) => (
            <section key={group}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                {GROUP_TITLES[group] ?? group}
              </h3>
              <ul>
                {grouped[group].map((secret) => (
                  <SecretRow key={secret.key} secret={secret} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </Card>
  )
}
