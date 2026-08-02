/** Scheduler — run times, the background service, and what happens after downtime. */
import clsx from 'clsx'
import { CalendarClock, Clock, Plus, Power, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { PageHeader } from '@/components/layout/PageHeader'
import { HelpTip, PageHelp } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import {
  Card,
  Chip,
  EmptyState,
  Field,
  SkeletonRows,
  Toggle,
} from '@/components/ui/primitives'
import { ApiError, api } from '@/lib/api'
import { formatDateTime, relativeTime } from '@/lib/format'

interface Slot {
  id: number
  name: string
  time: string
  timezone: string
  mode: string
  enabled: boolean
  days: string
  last_fired_at: string | null
  last_run_id: string
  last_outcome: string
}

interface SchedulePayload {
  slots: Slot[]
  jobs: { id: string; slot_id: number | null; next_run: string | null }[]
  upcoming: { slot_id: number | null; name: string; at: string }[]
  running: boolean
  catchup_grace_hours: number
  service: { installed: boolean; kind: string; status: string[] }
}

const MODES = [
  { value: 'auto', label: 'Auto' },
  { value: 'full', label: 'Full' },
  { value: 'native', label: 'Native' },
]

function useSchedule() {
  return useQuery({
    queryKey: ['schedule'],
    queryFn: () => api.get<SchedulePayload>('/api/schedule'),
  })
}

function useScheduleMutations() {
  const qc = useQueryClient()
  const done = () => qc.invalidateQueries({ queryKey: ['schedule'] })
  return {
    create: useMutation({
      mutationFn: (body: Partial<Slot>) => api.post('/api/schedule/slots', body),
      onSuccess: done,
    }),
    update: useMutation({
      mutationFn: ({ id, ...body }: Partial<Slot> & { id: number }) =>
        api.put(`/api/schedule/slots/${id}`, body),
      onSuccess: done,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api.del(`/api/schedule/slots/${id}`),
      onSuccess: done,
    }),
    catchup: useMutation({
      mutationFn: (hours: number) => api.put('/api/schedule/catchup', { hours }),
      onSuccess: done,
    }),
    service: useMutation({
      mutationFn: (action: 'install' | 'uninstall') =>
        api.post<{ ok: boolean }>(`/api/schedule/service/${action}`),
      onSuccess: done,
    }),
  }
}

/* -------------------------------------------------------------------------- */
function AddSlot({ onAdd }: { onAdd: (slot: Partial<Slot>) => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [time, setTime] = useState('09:30')
  const [mode, setMode] = useState('auto')

  if (!open) {
    return (
      <button type="button" className="btn-secondary btn-sm" onClick={() => setOpen(true)}>
        <Plus className="h-3.5 w-3.5" />
        Add a time
      </button>
    )
  }

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-xl border border-line bg-raised/50 p-4">
      <Field label="Name" hint="Just for you">
        <input
          className="input w-36"
          placeholder="morning"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <Field label="Time">
        <input
          className="input w-32"
          type="time"
          value={time}
          onChange={(e) => setTime(e.target.value)}
        />
      </Field>
      <Field label="Sources">
        <select className="input w-28" value={mode} onChange={(e) => setMode(e.target.value)}>
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </Field>
      <button
        type="button"
        className="btn-primary"
        onClick={() => {
          onAdd({ name: name.trim() || 'slot', time, mode })
          setOpen(false)
          setName('')
        }}
      >
        Add
      </button>
      <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>
        Cancel
      </button>
    </div>
  )
}

function SlotRow({
  slot,
  nextRun,
  onUpdate,
  onDelete,
}: {
  slot: Slot
  nextRun?: string | null
  onUpdate: (patch: Partial<Slot>) => void
  onDelete: () => void
}) {
  return (
    <li className="flex flex-wrap items-center gap-3 border-t border-line py-3 first:border-t-0 first:pt-0">
      <Clock className="h-4 w-4 shrink-0 text-faint" />
      <input
        className="input w-28"
        type="time"
        value={slot.time}
        onChange={(e) => onUpdate({ time: e.target.value })}
        aria-label={`Time for ${slot.name}`}
      />
      <input
        className="input w-36"
        value={slot.name}
        onChange={(e) => onUpdate({ name: e.target.value })}
        aria-label="Slot name"
      />
      <select
        className="input w-28"
        value={slot.mode}
        onChange={(e) => onUpdate({ mode: e.target.value })}
        aria-label="Sources"
      >
        {MODES.map((m) => (
          <option key={m.value} value={m.value}>
            {m.label}
          </option>
        ))}
      </select>

      <div className="min-w-[10rem] flex-1 text-xs text-muted">
        {slot.enabled ? (
          nextRun ? <>Next: {formatDateTime(nextRun)}</> : <>Scheduled</>
        ) : (
          <span className="text-faint">Paused</span>
        )}
        {slot.last_fired_at && (
          <span className="block text-faint">
            Last ran {relativeTime(slot.last_fired_at)}
            {slot.last_outcome ? ` — ${slot.last_outcome}` : ''}
          </span>
        )}
      </div>

      <Toggle checked={slot.enabled} onChange={(v) => onUpdate({ enabled: v })} />
      <button
        type="button"
        className="btn-icon hover:text-danger"
        onClick={onDelete}
        aria-label={`Delete ${slot.name}`}
      >
        <Trash2 className="h-3.5 w-3.5" />
      </button>
    </li>
  )
}

/* -------------------------------------------------------------------------- */
export function SchedulerPage() {
  const { data, isLoading } = useSchedule()
  const m = useScheduleMutations()
  const toast = useToast()

  const nextBySlot = new Map(
    (data?.jobs ?? []).map((job) => [job.slot_id, job.next_run] as const),
  )

  const guard = async (fn: () => Promise<unknown>, failure: string) => {
    try {
      await fn()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : failure)
    }
  }

  return (
    <>
      <PageHeader
        title="Scheduler"
        description="Run JobPilot automatically, without opening anything."
      >
        <PageHelp title="What happens when your machine is off">
          <p>
            Scheduled runs need something running. Installing the background service means
            JobPilot starts with your machine and stays out of the way.
          </p>
          <p>
            If the machine was off when a run was due, JobPilot runs it{' '}
            <strong>once</strong> when it comes back — not once for every slot it missed,
            and not at all if the miss is older than the grace window. If there's no
            network, it waits and retries rather than recording a failure.
          </p>
        </PageHelp>
      </PageHeader>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card
            title="Run times"
            subtitle="Two a day is plenty — postings don't appear that fast"
            actions={
              <AddSlot
                onAdd={(slot) =>
                  guard(() => m.create.mutateAsync(slot), 'Could not add that time.')
                }
              />
            }
          >
            {isLoading ? (
              <SkeletonRows rows={3} />
            ) : !data?.slots.length ? (
              <EmptyState
                icon={<CalendarClock className="h-5 w-5" />}
                title="No scheduled runs"
                description="Add a time and JobPilot will hunt for you on its own."
              />
            ) : (
              <ul>
                {data.slots.map((slot) => (
                  <SlotRow
                    key={slot.id}
                    slot={slot}
                    nextRun={nextBySlot.get(slot.id)}
                    onUpdate={(patch) =>
                      guard(
                        () => m.update.mutateAsync({ id: slot.id, ...patch }),
                        'Could not update that slot.',
                      )
                    }
                    onDelete={() =>
                      guard(() => m.remove.mutateAsync(slot.id), 'Could not delete that slot.')
                    }
                  />
                ))}
              </ul>
            )}
          </Card>

          <Card title="Coming up" subtitle="The next seven scheduled runs">
            {!data?.upcoming.length ? (
              <p className="text-sm text-muted">Nothing scheduled. Add a run time above.</p>
            ) : (
              <ol className="space-y-2">
                {data.upcoming.map((item, i) => (
                  <li key={`${item.at}-${i}`} className="flex items-center gap-3 text-sm">
                    <span className="w-6 text-xs tabular-nums text-faint">{i + 1}</span>
                    <span className="font-medium text-ink">{item.name}</span>
                    <span className="text-muted">{formatDateTime(item.at)}</span>
                    <span className="ml-auto text-xs text-faint">{relativeTime(item.at)}</span>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>

        <div className="space-y-5">
          <Card
            title="Background service"
            subtitle={data?.service.kind ? `Using ${data.service.kind}` : undefined}
            actions={
              <Chip tone={data?.service.installed ? 'ok' : 'neutral'}>
                {data?.service.installed ? 'Installed' : 'Not installed'}
              </Chip>
            }
          >
            <p className="mb-3 flex items-start gap-1.5 text-sm text-muted">
              Starts JobPilot with your machine so scheduled runs happen on their own.
              <HelpTip id="schedule.daemon" />
            </p>
            <button
              type="button"
              className={clsx(
                data?.service.installed ? 'btn-secondary' : 'btn-primary',
                'btn-sm',
              )}
              disabled={m.service.isPending}
              onClick={() =>
                guard(async () => {
                  const action = data?.service.installed ? 'uninstall' : 'install'
                  const res = await m.service.mutateAsync(action)
                  if (res.ok) {
                    toast.success(
                      action === 'install'
                        ? 'Service installed — JobPilot will start with your machine.'
                        : 'Service removed. Your data is untouched.',
                    )
                  } else {
                    toast.error('That did not work — check the terminal output.')
                  }
                }, 'Could not change the service.')
              }
            >
              <Power className="h-3.5 w-3.5" />
              {data?.service.installed ? 'Remove service' : 'Install service'}
            </button>

            {data?.service.status?.length ? (
              <pre className="mt-3 overflow-x-auto rounded-lg bg-raised p-3 font-mono text-[11px] leading-relaxed text-muted">
                {data.service.status.join('\n')}
              </pre>
            ) : null}
          </Card>

          <Card title="After downtime">
            <Field
              label={
                <>
                  Catch-up window <HelpTip id="schedule.catchup" />
                </>
              }
              hint="Hours. Set to 0 to never catch up."
            >
              <input
                className="input"
                type="number"
                min={0}
                max={72}
                defaultValue={data?.catchup_grace_hours ?? 6}
                onBlur={(e) =>
                  guard(
                    () => m.catchup.mutateAsync(Number(e.target.value)),
                    'Could not save that.',
                  )
                }
              />
            </Field>
            <p className="mt-3 flex items-start gap-1.5 text-xs text-muted">
              No network at run time? JobPilot retries after 1, 5, 15 and 30 minutes before
              giving up.
              <HelpTip id="schedule.retry" />
            </p>
          </Card>
        </div>
      </div>
    </>
  )
}
