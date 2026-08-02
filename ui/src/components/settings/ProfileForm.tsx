/** The candidate profile — what every job is scored against.
 *
 *  Confirming is deliberate and separate from saving: an unconfirmed profile still
 *  scores, but the UI says so, because a wrong profile silently degrades every score. */
import { AlertCircle, BadgeCheck, Plus, Save, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { HelpTip } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import { Card, Chip, Field, SkeletonRows } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { useProfile, useSaveProfile, useVerifyProfile } from '@/lib/settings'
import type { Profile } from '@/lib/settings'

const READINESS_LEVELS = [
  { value: 'unknown', label: "Haven't assessed" },
  { value: 'none', label: 'None' },
  { value: 'basic', label: 'Basic' },
  { value: 'intermediate', label: 'Intermediate' },
  { value: 'strong', label: 'Strong' },
]

/** Editable list of short strings — skills, locations, stacks. */
export function TagInput({
  values,
  onChange,
  placeholder,
}: {
  values: string[]
  onChange: (next: string[]) => void
  placeholder: string
}) {
  const [draft, setDraft] = useState('')

  const add = () => {
    const value = draft.trim()
    if (!value || values.includes(value)) {
      setDraft('')
      return
    }
    onChange([...values, value])
    setDraft('')
  }

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-1.5">
        {values.map((value) => (
          <span key={value} className="chip-neutral">
            {value}
            <button
              type="button"
              onClick={() => onChange(values.filter((v) => v !== value))}
              className="text-faint hover:text-danger"
              aria-label={`Remove ${value}`}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        {!values.length && <span className="text-xs text-faint">None yet</span>}
      </div>
      <div className="flex gap-2">
        <input
          className="input"
          placeholder={placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              add()
            }
          }}
        />
        <button type="button" className="btn-secondary" onClick={add} disabled={!draft.trim()}>
          <Plus className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

export function ProfileForm() {
  const { data, isLoading } = useProfile()
  const save = useSaveProfile()
  const verify = useVerifyProfile()
  const toast = useToast()

  const [draft, setDraft] = useState<Profile | null>(null)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (data?.profile && !dirty) setDraft(data.profile)
  }, [data, dirty])

  // Leaving with unsaved edits loses them silently otherwise.
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  if (isLoading || !draft) {
    return (
      <Card title="Your profile">
        <SkeletonRows rows={6} />
      </Card>
    )
  }

  const update = <K extends keyof Profile>(key: K, value: Profile[K]) => {
    setDraft({ ...draft, [key]: value })
    setDirty(true)
  }

  const onSave = async () => {
    try {
      await save.mutateAsync({ data: draft })
      setDirty(false)
      toast.success('Profile saved.')
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not save your profile.')
    }
  }

  const verified = data?.verified ?? false

  return (
    <Card
      title="Your profile"
      subtitle="What every job is scored against"
      actions={
        <>
          {verified ? (
            <Chip tone="ok" icon={<BadgeCheck className="h-3 w-3" />}>
              <span className="flex items-center gap-1">
                Confirmed <HelpTip id="profile.verified" />
              </span>
            </Chip>
          ) : (
            <button
              type="button"
              className="btn-secondary btn-sm"
              onClick={async () => {
                await verify.mutateAsync(true)
                toast.success('Profile confirmed — scoring will use it as-is.')
              }}
            >
              <BadgeCheck className="h-3.5 w-3.5" />
              Confirm it's correct
            </button>
          )}
          <button
            type="button"
            className="btn-primary btn-sm"
            onClick={onSave}
            disabled={!dirty || save.isPending}
          >
            <Save className="h-3.5 w-3.5" />
            {save.isPending ? 'Saving…' : dirty ? 'Save changes' : 'Saved'}
          </button>
        </>
      }
    >
      {!verified && (
        <p className="mb-4 flex items-start gap-2 rounded-lg bg-warn/10 px-3 py-2 text-xs text-warn">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          This profile was extracted from your resume but you haven't confirmed it. Scoring
          uses it either way — check it's right, then confirm.
        </p>
      )}

      <div className="grid gap-5 md:grid-cols-2">
        <Field label="Full name">
          <input
            className="input"
            value={draft.name ?? ''}
            onChange={(e) => update('name', e.target.value)}
          />
        </Field>
        <Field label="Email">
          <input
            className="input"
            type="email"
            value={draft.email ?? ''}
            onChange={(e) => update('email', e.target.value)}
          />
        </Field>
        <Field
          label={
            <>
              Years of experience <HelpTip id="profile.experience_years" />
            </>
          }
          hint="Jobs asking for more than this plus two are dropped automatically"
        >
          <input
            className="input"
            type="number"
            min={0}
            value={draft.experience_years ?? 0}
            onChange={(e) => update('experience_years', Number(e.target.value))}
          />
        </Field>
        <Field label="Graduation">
          <input
            className="input"
            placeholder="e.g. July 2026"
            value={draft.graduation_date ?? ''}
            onChange={(e) => update('graduation_date', e.target.value)}
          />
        </Field>
        <Field label="GitHub">
          <input
            className="input"
            value={draft.github_url ?? ''}
            onChange={(e) => update('github_url', e.target.value)}
          />
        </Field>
        <Field label="Portfolio or LinkedIn">
          <input
            className="input"
            value={draft.portfolio_url ?? ''}
            onChange={(e) => update('portfolio_url', e.target.value)}
          />
        </Field>
      </div>

      <div className="mt-5 border-t border-line pt-5">
        <Field
          label={
            <>
              Skills <HelpTip id="profile.skills" />
            </>
          }
          hint="Only skills listed here can count as a match against a job description"
        >
          <TagInput
            values={draft.skills ?? []}
            onChange={(next) => update('skills', next)}
            placeholder="Add a skill and press Enter"
          />
        </Field>
      </div>

      <div className="mt-5 border-t border-line pt-5">
        <h3 className="mb-3 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
          Interview readiness
          <HelpTip id="profile.interview_readiness" />
        </h3>
        <div className="grid gap-5 md:grid-cols-3">
          <Field label="Data structures & algorithms">
            <select
              className="input"
              value={draft.interview_readiness?.dsa_level ?? 'unknown'}
              onChange={(e) =>
                update('interview_readiness', {
                  ...draft.interview_readiness,
                  dsa_level: e.target.value,
                })
              }
            >
              {READINESS_LEVELS.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="System design">
            <select
              className="input"
              value={draft.interview_readiness?.system_design ?? 'unknown'}
              onChange={(e) =>
                update('interview_readiness', {
                  ...draft.interview_readiness,
                  system_design: e.target.value,
                })
              }
            >
              {READINESS_LEVELS.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="LeetCode profile" hint="Optional">
            <input
              className="input"
              value={draft.interview_readiness?.leetcode_url ?? ''}
              onChange={(e) =>
                update('interview_readiness', {
                  ...draft.interview_readiness,
                  leetcode_url: e.target.value,
                })
              }
            />
          </Field>
        </div>
      </div>
    </Card>
  )
}
