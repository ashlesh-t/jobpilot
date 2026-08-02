/** Job preferences — what JobPilot searches for and how strictly it filters. */
import { Save } from 'lucide-react'
import { useEffect, useState } from 'react'

import { TagInput } from './ProfileForm'
import { HelpTip } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import { Card, Field, SkeletonRows, Toggle } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { usePreferences, useSavePreferences } from '@/lib/settings'
import type { Preferences } from '@/lib/settings'

const MARKETS = [
  { value: 'india', label: 'India-focused boards' },
  { value: 'global', label: 'Global remote boards' },
  { value: 'both', label: 'Both' },
]

const CHANNELS = [
  { value: 'telegram', label: 'Telegram' },
  { value: 'discord', label: 'Discord' },
]

export function PreferencesForm() {
  const { data, isLoading } = usePreferences()
  const save = useSavePreferences()
  const toast = useToast()

  const [draft, setDraft] = useState<Preferences | null>(null)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (data?.preferences && !dirty) setDraft(data.preferences)
  }, [data, dirty])

  if (isLoading || !draft) {
    return (
      <Card title="Job preferences">
        <SkeletonRows rows={5} />
      </Card>
    )
  }

  const update = <K extends keyof Preferences>(key: K, value: Preferences[K]) => {
    setDraft({ ...draft, [key]: value })
    setDirty(true)
  }

  const onSave = async () => {
    try {
      await save.mutateAsync(draft)
      setDirty(false)
      toast.success('Preferences saved.')
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not save your preferences.')
    }
  }

  const toggleChannel = (channel: string, on: boolean) => {
    const next = on
      ? [...(draft.notify_channels ?? []), channel]
      : (draft.notify_channels ?? []).filter((c) => c !== channel)
    update('notify_channels', Array.from(new Set(next)))
  }

  return (
    <Card
      title="Job preferences"
      subtitle="What JobPilot looks for, and how strictly it filters"
      actions={
        <button
          type="button"
          className="btn-primary btn-sm"
          onClick={onSave}
          disabled={!dirty || save.isPending}
        >
          <Save className="h-3.5 w-3.5" />
          {save.isPending ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
        </button>
      }
    >
      <div className="grid gap-5 md:grid-cols-2">
        <Field
          label={
            <>
              Locations <HelpTip id="prefs.locations" />
            </>
          }
          hint="The first one is treated as your first choice"
        >
          <TagInput
            values={draft.locations ?? []}
            onChange={(next) => update('locations', next)}
            placeholder="Add a city and press Enter"
          />
        </Field>

        <Field
          label={
            <>
              Roles <HelpTip id="prefs.role_types" />
            </>
          }
        >
          <TagInput
            values={draft.role_types ?? []}
            onChange={(next) => update('role_types', next)}
            placeholder="e.g. Backend, SWE, ML"
          />
        </Field>

        <Field label="Preferred stack" hint="Used to sharpen the searches">
          <TagInput
            values={draft.preferred_stack ?? []}
            onChange={(next) => update('preferred_stack', next)}
            placeholder="e.g. Go, Kubernetes"
          />
        </Field>

        <div className="space-y-4">
          <Field
            label={
              <>
                Job market <HelpTip id="prefs.market_focus" />
              </>
            }
          >
            <select
              className="input"
              value={draft.job_market_focus}
              onChange={(e) => update('job_market_focus', e.target.value)}
            >
              {MARKETS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>
          <Toggle
            checked={draft.remote_ok}
            onChange={(v) => update('remote_ok', v)}
            label={
              <span className="flex items-center gap-1.5">
                Include remote roles <HelpTip id="prefs.remote_ok" />
              </span>
            }
          />
        </div>
      </div>

      <div className="mt-5 grid gap-5 border-t border-line pt-5 md:grid-cols-4">
        <Field
          label={
            <>
              Minimum package <HelpTip id="prefs.target_ctc" />
            </>
          }
          hint="LPA"
        >
          <input
            className="input"
            type="number"
            min={0}
            value={draft.target_ctc_min_lpa ?? 0}
            onChange={(e) => update('target_ctc_min_lpa', Number(e.target.value))}
          />
        </Field>
        <Field
          label={
            <>
              Tailoring threshold <HelpTip id="prefs.score_threshold" />
            </>
          }
          hint="Score out of 100"
        >
          <input
            className="input"
            type="number"
            min={0}
            max={100}
            value={draft.score_threshold ?? 65}
            onChange={(e) => update('score_threshold', Number(e.target.value))}
          />
        </Field>
        <Field
          label={
            <>
              Notice period <HelpTip id="prefs.notice_period" />
            </>
          }
          hint="Days"
        >
          <input
            className="input"
            type="number"
            min={0}
            value={draft.notice_period_days ?? 0}
            onChange={(e) => update('notice_period_days', Number(e.target.value))}
          />
        </Field>
        <Field
          label={
            <>
              Keep jobs for <HelpTip id="prefs.stale_after_days" />
            </>
          }
          hint="Days since last seen"
        >
          <input
            className="input"
            type="number"
            min={1}
            value={draft.stale_after_days ?? 21}
            onChange={(e) => update('stale_after_days', Number(e.target.value))}
          />
        </Field>
      </div>

      <div className="mt-5 border-t border-line pt-5">
        <span className="label">Send results to</span>
        <div className="flex flex-wrap gap-5">
          {CHANNELS.map((channel) => (
            <Toggle
              key={channel.value}
              checked={(draft.notify_channels ?? []).includes(channel.value)}
              onChange={(v) => toggleChannel(channel.value, v)}
              label={channel.label}
            />
          ))}
        </div>
        <p className="mt-2 text-xs text-faint">
          With none selected, results stay in the web UI — nothing is sent anywhere.
        </p>
      </div>
    </Card>
  )
}
