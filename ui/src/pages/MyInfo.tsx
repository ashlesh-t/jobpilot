/** My Info — profile, preferences, credentials, and whether everything actually works. */
import clsx from 'clsx'
import { CheckCircle2, CircleAlert, RefreshCw, Stethoscope, XCircle } from 'lucide-react'
import { useState } from 'react'

import { PageHeader } from '@/components/layout/PageHeader'
import { PreferencesForm } from '@/components/settings/PreferencesForm'
import { ProfileForm } from '@/components/settings/ProfileForm'
import { SecretsVault } from '@/components/settings/SecretsVault'
import { HelpTip, PageHelp } from '@/components/ui/Help'
import { Card, Chip, SkeletonRows, Spinner } from '@/components/ui/primitives'
import { useDoctor } from '@/lib/hooks'
import type { DoctorRow } from '@/lib/hooks'

const TABS = [
  { id: 'profile', label: 'Profile' },
  { id: 'preferences', label: 'Preferences' },
  { id: 'credentials', label: 'Keys & tokens' },
  { id: 'health', label: 'Health' },
] as const

type TabId = (typeof TABS)[number]['id']

const ICONS: Record<DoctorRow['status'], JSX.Element> = {
  ok: <CheckCircle2 className="h-4 w-4 text-ok" />,
  warn: <CircleAlert className="h-4 w-4 text-warn" />,
  fail: <XCircle className="h-4 w-4 text-danger" />,
}

function HealthTable({ rows }: { rows: DoctorRow[] }) {
  const byCategory = rows.reduce<Record<string, DoctorRow[]>>((acc, row) => {
    ;(acc[row.category] ??= []).push(row)
    return acc
  }, {})

  return (
    <div className="space-y-6">
      {Object.entries(byCategory).map(([category, items]) => (
        <section key={category}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
            {category}
          </h3>
          <ul className="space-y-2">
            {items.map((row) => (
              <li key={row.name} className="flex items-start gap-2.5 text-sm">
                <span className="mt-0.5 shrink-0">{ICONS[row.status]}</span>
                <span className="min-w-0">
                  <span className="font-medium text-ink">{row.name}</span>
                  <span className="text-muted"> — {row.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

function HealthPanel() {
  const [live, setLive] = useState(false)
  const doctor = useDoctor(live)
  const summary = doctor.data?.summary

  return (
    <Card
      title="Health checks"
      subtitle={
        live
          ? 'Deep check — verifies your AI backend login and fetches real jobs from every source'
          : 'Quick check — configuration only'
      }
      actions={
        <>
          {summary && (
            <div className="flex gap-1.5">
              <Chip tone="ok">{summary.ok} ok</Chip>
              {summary.warn > 0 && <Chip tone="warn">{summary.warn}</Chip>}
              {summary.fail > 0 && <Chip tone="danger">{summary.fail}</Chip>}
            </div>
          )}
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => {
              setLive(false)
              doctor.refetch()
            }}
            disabled={doctor.isFetching}
          >
            <RefreshCw className={clsx('h-3.5 w-3.5', doctor.isFetching && 'animate-spin')} />
            Quick
            <HelpTip id="doctor.quick" />
          </button>
          <button
            type="button"
            className="btn-primary btn-sm"
            onClick={() => setLive(true)}
            disabled={doctor.isFetching}
          >
            <Stethoscope className="h-3.5 w-3.5" />
            Run everything
            <HelpTip id="doctor.live" />
          </button>
        </>
      }
    >
      {doctor.isFetching && live && (
        <p className="mb-4 flex items-center gap-2 text-sm text-muted">
          <Spinner />
          Probing every source — this takes up to a minute.
        </p>
      )}
      {doctor.isLoading ? (
        <SkeletonRows rows={8} />
      ) : (
        <HealthTable rows={doctor.data?.rows ?? []} />
      )}
    </Card>
  )
}

export function MyInfoPage() {
  const [tab, setTab] = useState<TabId>('profile')

  return (
    <>
      <PageHeader
        title="My Info"
        description="Everything JobPilot knows about you, and everything it connects to."
      >
        <PageHelp title="Where all this is stored">
          <p>
            Your profile, preferences and job history live in a database on this machine.
            Keys and tokens go into your operating system's keyring — never the database,
            and never a file JobPilot syncs anywhere.
          </p>
          <p>
            The profile is what every job gets scored against, so it's worth reading through
            once and confirming.
          </p>
        </PageHelp>
      </PageHeader>

      <div className="mb-5 flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={clsx(
              '-mb-px border-b-2 px-3.5 py-2 text-sm font-medium transition-colors',
              tab === t.id
                ? 'border-accent text-accent'
                : 'border-transparent text-muted hover:text-ink',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'profile' && <ProfileForm />}
      {tab === 'preferences' && <PreferencesForm />}
      {tab === 'credentials' && <SecretsVault />}
      {tab === 'health' && <HealthPanel />}
    </>
  )
}
