/** Delivery step of the setup wizard — Telegram (with automatic chat linking) and
 *  Discord, both optional. Ported from the old CLI's notify setup, which drove the
 *  same Telegram getUpdates poll server-side in one long-lived request; here it's a
 *  client-side poll against the stateless `/link-chat` endpoint instead. */
import clsx from 'clsx'
import { Check, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useToast } from '@/components/ui/Toast'
import { Spinner } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import {
  useLinkTelegramChat,
  useSaveSecret,
  useSecrets,
  useTestSecret,
} from '@/lib/settings'

const BOTFATHER_URL = 'https://t.me/BotFather'
const POLL_SECONDS = 180

function Qr({ data }: { data: string }) {
  return (
    <img
      src={`/api/qr?data=${encodeURIComponent(data)}`}
      alt="QR code"
      width={112}
      height={112}
      className="rounded-lg border border-line bg-white p-1.5"
    />
  )
}

function TelegramPanel() {
  const { data: secrets } = useSecrets()
  const toast = useToast()

  const tokenSet = secrets?.some((s) => s.key === 'TELEGRAM_BOT_TOKEN' && s.set) ?? false
  const chatSet = secrets?.some((s) => s.key === 'TELEGRAM_CHAT_ID' && s.set) ?? false

  const [tokenDraft, setTokenDraft] = useState('')
  const [botUsername, setBotUsername] = useState<string | null>(null)
  const [tokenOk, setTokenOk] = useState(false)
  // The secrets list can already have a verified token from a previous visit — pick
  // that up once it loads instead of only trusting this session's own save+test.
  useEffect(() => {
    if (tokenSet) setTokenOk(true)
  }, [tokenSet])
  const saveToken = useSaveSecret()
  const testToken = useTestSecret()

  const [polling, setPolling] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(POLL_SECONDS)
  const [manualMode, setManualMode] = useState(false)
  const [manualChatId, setManualChatId] = useState('')
  const linkChat = useLinkTelegramChat()
  const saveChatId = useSaveSecret()
  const testChatId = useTestSecret()
  const [testResult, setTestResult] = useState<{ ok: boolean; detail: string } | null>(null)

  const onSaveToken = async () => {
    if (!tokenDraft.trim()) return
    try {
      await saveToken.mutateAsync({ key: 'TELEGRAM_BOT_TOKEN', value: tokenDraft })
      const body = await testToken.mutateAsync('TELEGRAM_BOT_TOKEN')
      setTokenOk(body.ok)
      if (body.ok) {
        const m = body.detail.match(/@(\w+)/)
        setBotUsername(m ? m[1] : null)
        setPolling(true)
        setSecondsLeft(POLL_SECONDS)
      } else {
        toast.error(body.detail)
      }
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not save the bot token.')
    }
  }

  // Self-scheduling poll: each tick either finds the chat or reschedules 2s later,
  // until the 180s budget runs out and we fall back to manual entry.
  useEffect(() => {
    if (!polling) return
    if (secondsLeft <= 0) {
      setPolling(false)
      setManualMode(true)
      return
    }
    const timer = setTimeout(async () => {
      try {
        const res = await linkChat.mutateAsync()
        if (res.found) {
          setPolling(false)
          toast.success('Chat linked — nothing more to do.')
        } else {
          setSecondsLeft((s) => s - 2)
        }
      } catch {
        setSecondsLeft((s) => s - 2)
      }
    }, 2000)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [polling, secondsLeft])

  const onSaveManualChatId = async () => {
    if (!/^-?\d+$/.test(manualChatId.trim())) {
      toast.error('Chat ID should be digits only (a leading - is fine).')
      return
    }
    try {
      await saveChatId.mutateAsync({ key: 'TELEGRAM_CHAT_ID', value: manualChatId.trim() })
      setManualMode(false)
      toast.success('Chat ID saved.')
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not save that.')
    }
  }

  const onSendTest = async () => {
    setTestResult(null)
    try {
      const body = await testChatId.mutateAsync('TELEGRAM_CHAT_ID')
      setTestResult({ ok: body.ok, detail: body.detail })
    } catch (e) {
      setTestResult({
        ok: false,
        detail: e instanceof ApiError ? e.detail : 'Could not send that.',
      })
    }
  }

  return (
    <div className="space-y-4 rounded-xl border border-line p-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">Create your bot</h3>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-muted">
          <li>
            Open{' '}
            <a
              className="text-accent hover:underline"
              href={BOTFATHER_URL}
              target="_blank"
              rel="noreferrer"
            >
              @BotFather
            </a>{' '}
            in Telegram (link or QR below)
          </li>
          <li>Send /newbot and follow the two prompts</li>
          <li>
            It replies with "Use this token to access the HTTP API:" followed by the
            token
          </li>
          <li>
            Paste the whole token here — digits, colon and letters together, like
            123456789:AAH…
          </li>
        </ol>
        <p className="mt-2 text-sm text-muted">
          Not just the numbers, not just the letters, and none of the words around it.
        </p>
        <div className="mt-3">
          <Qr data={BOTFATHER_URL} />
        </div>
      </div>

      {!tokenOk && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="password"
            className="input max-w-md"
            placeholder="123456789:AAH..."
            value={tokenDraft}
            onChange={(e) => setTokenDraft(e.target.value)}
          />
          <button
            type="button"
            className="btn-primary btn-sm"
            onClick={onSaveToken}
            disabled={!tokenDraft.trim() || saveToken.isPending || testToken.isPending}
          >
            {saveToken.isPending || testToken.isPending ? (
              <Spinner className="h-3.5 w-3.5" />
            ) : null}
            Save & verify
          </button>
        </div>
      )}

      {tokenOk && !chatSet && (
        <div className="space-y-3 border-t border-line pt-4">
          <h3 className="text-sm font-semibold text-ink">Link your chat</h3>
          <p className="text-sm text-muted">
            Open your bot and press Start (or send it any message). JobPilot will pick
            up the chat automatically — nothing to copy.
          </p>
          {botUsername ? (
            <div className="mt-2 flex items-center gap-3">
              <Qr data={`https://t.me/${botUsername}`} />
              <a
                className="text-sm text-accent hover:underline"
                href={`https://t.me/${botUsername}`}
                target="_blank"
                rel="noreferrer"
              >
                t.me/{botUsername}
              </a>
            </div>
          ) : (
            <p className="text-xs text-faint">
              Couldn't read the bot's username from the token test — open the bot
              directly from Telegram instead.
            </p>
          )}

          {polling && (
            <p className="flex items-center gap-2 text-sm text-muted">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Waiting for a message from your bot… ({secondsLeft}s)
            </p>
          )}

          {manualMode && (
            <div className="space-y-2 border-t border-line pt-3">
              <p className="text-sm text-muted">
                Didn't catch it in time — paste your numeric chat ID instead.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  className="input max-w-xs"
                  placeholder="e.g. 123456789 or -100123456789"
                  value={manualChatId}
                  onChange={(e) => setManualChatId(e.target.value)}
                />
                <button
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={onSaveManualChatId}
                  disabled={!manualChatId.trim() || saveChatId.isPending}
                >
                  {saveChatId.isPending ? <Spinner className="h-3.5 w-3.5" /> : null}
                  Save chat ID
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {chatSet && (
        <div className="space-y-2 border-t border-line pt-4">
          <p className="flex items-center gap-1.5 text-sm text-ok">
            <Check className="h-3.5 w-3.5" />
            Chat linked.
          </p>
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={onSendTest}
            disabled={testChatId.isPending}
          >
            {testChatId.isPending ? <Spinner className="h-3.5 w-3.5" /> : null}
            Send test message
          </button>
          {testResult && (
            <p className={clsx('text-xs', testResult.ok ? 'text-ok' : 'text-danger')}>
              {testResult.detail}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function DiscordPanel() {
  const { data: secrets } = useSecrets()
  const webhookSet = secrets?.some((s) => s.key === 'DISCORD_WEBHOOK_URL' && s.set) ?? false

  const [value, setValue] = useState('')
  const save = useSaveSecret()
  const toast = useToast()
  const valid = value.includes('discord.com/api/webhooks/')

  const onSave = async () => {
    if (!valid) return
    try {
      await save.mutateAsync({ key: 'DISCORD_WEBHOOK_URL', value })
      toast.success('Discord webhook saved.')
      setValue('')
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not save that.')
    }
  }

  return (
    <div className="space-y-2 rounded-xl border border-line p-4">
      <h3 className="text-sm font-semibold text-ink">Discord webhook</h3>
      <p className="text-sm text-muted">
        Channel Settings → Integrations → Webhooks → New Webhook → Copy URL
      </p>
      {webhookSet && (
        <p className="flex items-center gap-1.5 text-sm text-ok">
          <Check className="h-3.5 w-3.5" />
          Webhook saved.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="password"
          className="input max-w-md"
          placeholder="https://discord.com/api/webhooks/..."
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button
          type="button"
          className="btn-secondary btn-sm"
          onClick={onSave}
          disabled={!value.trim() || save.isPending}
        >
          {save.isPending ? <Spinner className="h-3.5 w-3.5" /> : null}
          Save
        </button>
      </div>
      {value && !valid && (
        <p className="text-xs text-danger">That doesn't look like a Discord webhook URL.</p>
      )}
    </div>
  )
}

export function DeliveryStep() {
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">
        Every run sends a digest, the full spreadsheet, and any tailored resumes. You
        can always read them in the web UI too.
      </p>
      <TelegramPanel />
      <DiscordPanel />
    </div>
  )
}
