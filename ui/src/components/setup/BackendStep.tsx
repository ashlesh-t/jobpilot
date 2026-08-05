/** AI backend step of the setup wizard — ported from the old CLI's backend picker
 *  (`jobpilot/tui/steps.py`, deleted). Lets the user pick which agent runs Layer B,
 *  and inline-configures whatever that backend needs (an API key, a command
 *  template) without leaving the wizard. */
import clsx from 'clsx'
import { Check, RefreshCw } from 'lucide-react'
import { useState } from 'react'

import { useToast } from '@/components/ui/Toast'
import { Chip, Spinner } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import {
  useBackends,
  useSaveSecret,
  useSelectBackend,
  useTestSecret,
} from '@/lib/settings'

/** Pulls the first URL out of a hint string returned by the API (e.g.
 *  "npm install -g @anthropic-ai/claude-code   (or download from https://claude.com/download)")
 *  so we never hardcode a URL the backend already knows. */
function firstUrl(text: string): string | null {
  const m = text.match(/https?:\/\/[^\s)]+/)
  return m ? m[0] : null
}

function Qr({ data, size = 112 }: { data: string; size?: number }) {
  return (
    <img
      src={`/api/qr?data=${encodeURIComponent(data)}`}
      alt="QR code"
      width={size}
      height={size}
      className="rounded-lg border border-line bg-white p-1.5"
    />
  )
}

/** A masked credential field, inline — not the full SecretsVault row, because each
 *  backend needs different affordances around it (verify vs. not, save-anyway vs. not). */
function InlineSecret({
  secretKey,
  label,
  placeholder,
  verify = true,
}: {
  secretKey: string
  label: string
  placeholder: string
  verify?: boolean
}) {
  const [value, setValue] = useState('')
  const [saved, setSaved] = useState(false)
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null)
  const save = useSaveSecret()
  const test = useTestSecret()
  const toast = useToast()

  const onSave = async () => {
    if (!value.trim()) return
    try {
      await save.mutateAsync({ key: secretKey, value })
      setSaved(true)
      toast.success(`${label} saved.`)
      if (verify) {
        const body = await test.mutateAsync(secretKey)
        setResult({ ok: body.ok, detail: body.detail })
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not save that.')
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="password"
          className="input max-w-md"
          placeholder={placeholder}
          value={value}
          onChange={(e) => {
            setValue(e.target.value)
            setResult(null)
          }}
        />
        <button
          type="button"
          className="btn-primary btn-sm"
          onClick={onSave}
          disabled={!value.trim() || save.isPending || test.isPending}
        >
          {save.isPending || test.isPending ? <Spinner className="h-3.5 w-3.5" /> : null}
          {saved ? 'Replace' : 'Save'}
        </button>
      </div>
      {result && (
        <p className={clsx('text-xs', result.ok ? 'text-ok' : 'text-danger')}>
          {result.detail}
          {!result.ok && ' — saved anyway, you can fix this later in My Info.'}
        </p>
      )}
    </div>
  )
}

export function BackendStep() {
  const { data, isLoading, refetch, isFetching } = useBackends(true)
  const selectBackend = useSelectBackend()
  const toast = useToast()

  const backends = data?.backends ?? []
  const selected = data?.selected
  const current = backends.find((b) => b.id === selected)

  const onSelect = async (id: string) => {
    try {
      await selectBackend.mutateAsync(id)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not switch backend.')
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">
        JobPilot needs an AI agent to read job descriptions, score them and tailor your
        resume.
      </p>

      {isLoading ? (
        <Spinner />
      ) : (
        <div className="space-y-2">
          {backends.map((b) => (
            <label
              key={b.id}
              className={clsx(
                'flex cursor-pointer items-start gap-3 rounded-xl border p-3',
                b.id === selected ? 'border-accent bg-accent/5' : 'border-line',
              )}
            >
              <input
                type="radio"
                name="backend"
                className="mt-1"
                checked={b.id === selected}
                onChange={() => onSelect(b.id)}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-ink">{b.label}</span>
                  {b.experimental && <Chip tone="neutral">Experimental</Chip>}
                  {b.metered && <Chip tone="neutral">Metered</Chip>}
                  <Chip tone={b.ready ? 'ok' : b.found ? 'warn' : 'neutral'}>
                    {b.ready ? (
                      <span className="flex items-center gap-1">
                        <Check className="h-3 w-3" />
                        Ready
                      </span>
                    ) : b.found ? (
                      'Needs auth'
                    ) : (
                      'Not found'
                    )}
                  </Chip>
                </div>
                <p className="mt-0.5 text-xs text-faint">{b.detail}</p>
              </div>
            </label>
          ))}
        </div>
      )}

      <button
        type="button"
        className="btn-secondary btn-sm"
        onClick={() => refetch()}
        disabled={isFetching}
      >
        {isFetching ? (
          <Spinner className="h-3.5 w-3.5" />
        ) : (
          <RefreshCw className="h-3.5 w-3.5" />
        )}
        Recheck
      </button>

      {current?.id === 'claude_code' && !current.found && (
        <div className="rounded-xl border border-line p-4">
          <p className="text-sm text-ink">{current.install_hint}</p>
          <p className="mt-1 text-sm text-muted">{current.auth_hint}</p>
          {firstUrl(current.install_hint) && (
            <div className="mt-3">
              <Qr data={firstUrl(current.install_hint)!} />
            </div>
          )}
        </div>
      )}

      {current?.id === 'claude_api' && (
        <div className="space-y-3 rounded-xl border border-line p-4">
          <p className="text-sm text-muted">
            Create a key at{' '}
            <a
              className="text-accent hover:underline"
              href={firstUrl(current.auth_hint) ?? '#'}
              target="_blank"
              rel="noreferrer"
            >
              {firstUrl(current.auth_hint)}
            </a>
          </p>
          {firstUrl(current.auth_hint) && <Qr data={firstUrl(current.auth_hint)!} />}
          <InlineSecret
            secretKey="ANTHROPIC_API_KEY"
            label="Anthropic API key"
            placeholder="sk-ant-..."
          />
        </div>
      )}

      {current?.id === 'gemini' && (
        <div className="space-y-3 rounded-xl border border-line p-4">
          <p className="text-sm text-muted">
            Optional — set a Gemini API key, or sign in with `gemini` in a terminal
            instead.
          </p>
          <InlineSecret
            secretKey="GEMINI_API_KEY"
            label="Gemini API key"
            placeholder="AIza..."
            verify={false}
          />
        </div>
      )}

      {current?.id === 'generic_cli' && <GenericCliPanel installHint={current.install_hint} />}
    </div>
  )
}

/** No settings endpoint persists `command_template` today — `PUT /api/backends` only
 *  carries the backend id, and `core/backends._save_engine_config` is only ever
 *  called from `select()`. This panel shows the requirement and the CLI fallback
 *  rather than inventing a new endpoint. */
function GenericCliPanel({ installHint }: { installHint: string }) {
  const [value, setValue] = useState('')
  const valid = value.includes('{prompt}')

  return (
    <div className="space-y-2 rounded-xl border border-line p-4">
      <p className="text-sm text-muted">{installHint}</p>
      <input
        className="input w-full"
        placeholder="mytool run --prompt {prompt}"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      {value && !valid && (
        <p className="text-xs text-danger">The template must contain {'{prompt}'}.</p>
      )}
      <p className="text-xs text-faint">
        There's no web endpoint yet to save a command template — run{' '}
        <code className="font-mono">jobpilot setup</code> in a terminal to configure a
        custom agent CLI for now.
      </p>
    </div>
  )
}
