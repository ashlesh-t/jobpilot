/** The setup gate and the in-app wizard that clears it.
 *
 *  Form-first by design: the questionnaire is deterministic, validated and free, and the
 *  agent is used only where judgement is actually needed — reading the resume. */
import clsx from 'clsx'
import { ArrowLeft, ArrowRight, Check, CircleAlert, Rocket } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ResumeManager } from '@/components/resumes/ResumeManager'
import { BackendStep } from '@/components/setup/BackendStep'
import { DeliveryStep } from '@/components/setup/DeliveryStep'
import { SourcesStep } from '@/components/setup/SourcesStep'
import { ProfileForm } from '@/components/settings/ProfileForm'
import { TagInput } from '@/components/settings/ProfileForm'
import { HelpTip } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import { Card, Chip, Dialog, Field, Spinner } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import {
  usePreferences,
  useProfile,
  useSavePreferences,
  useSetupStatus,
  useVerifyProfile,
} from '@/lib/settings'

const STEPS = [
  { id: 'you', label: 'You' },
  { id: 'resume', label: 'Resume' },
  { id: 'profile', label: 'Profile' },
  { id: 'backend', label: 'AI backend' },
  { id: 'sources', label: 'Job sources' },
  { id: 'delivery', label: 'Delivery' },
  { id: 'search', label: 'What to look for' },
  { id: 'done', label: 'Done' },
] as const

/* -------------------------------------------------------------------------- */
/* The gate                                                                    */
/* -------------------------------------------------------------------------- */
export function SetupGate({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useSetupStatus()
  const [wizardOpen, setWizardOpen] = useState(false)

  if (isLoading) return null
  if (data?.ready) return <>{children}</>

  const blocking = data?.blocking ?? []

  return (
    <>
      <Card className="mb-5 border-warn/40">
        <div className="flex flex-wrap items-start gap-4">
          <CircleAlert className="mt-0.5 h-5 w-5 shrink-0 text-warn" />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold text-ink">
              Finish setup to start hunting
            </h2>
            <p className="mt-1 text-sm text-muted">
              JobPilot needs a few things before it can score jobs properly.
            </p>
            <ul className="mt-3 space-y-1.5">
              {Object.entries(data?.checks ?? {}).map(([key, check]) => (
                <li key={key} className="flex items-center gap-2 text-sm">
                  {check.ok ? (
                    <Check className="h-3.5 w-3.5 shrink-0 text-ok" />
                  ) : (
                    <span
                      className={clsx(
                        'h-1.5 w-1.5 shrink-0 rounded-full',
                        check.optional ? 'bg-faint' : 'bg-warn',
                      )}
                    />
                  )}
                  <span className={check.ok ? 'text-muted' : 'text-ink'}>
                    {check.label}
                  </span>
                  <span className="text-faint">— {check.detail}</span>
                  {check.optional && !check.ok && <Chip tone="neutral">Optional</Chip>}
                </li>
              ))}
            </ul>
          </div>
          <button
            type="button"
            className="btn-primary btn-sm shrink-0"
            onClick={() => setWizardOpen(true)}
          >
            <Rocket className="h-3.5 w-3.5" />
            Set up now
          </button>
        </div>
      </Card>

      <SetupWizard
        open={wizardOpen}
        onClose={() => setWizardOpen(false)}
        startAt={blocking[0]}
      />

      <div className="pointer-events-none select-none opacity-40">{children}</div>
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* The wizard                                                                  */
/* -------------------------------------------------------------------------- */
const BLOCKER_TO_STEP: Record<string, (typeof STEPS)[number]['id']> = {
  resume: 'resume',
  profile: 'profile',
  backend: 'backend',
  preferences: 'search',
  notifications: 'delivery',
}

function stepForBlocker(blocker?: string): number {
  const id = BLOCKER_TO_STEP[blocker ?? '']
  const idx = STEPS.findIndex((s) => s.id === id)
  return idx >= 0 ? idx : 0
}

export function SetupWizard({
  open,
  onClose,
  startAt,
}: {
  open: boolean
  onClose: () => void
  startAt?: string
}) {
  const [step, setStep] = useState(() => stepForBlocker(startAt))
  const prefs = usePreferences()
  const profile = useProfile()
  const savePrefs = useSavePreferences()
  const verify = useVerifyProfile()
  const status = useSetupStatus()
  const toast = useToast()

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [locations, setLocations] = useState<string[]>([])
  const [roles, setRoles] = useState<string[]>([])
  const [ctc, setCtc] = useState('')

  // Seed the form from whatever is already saved, so re-entering isn't a blank slate.
  const preferences = prefs.data?.preferences
  if (preferences && !name && preferences.name) setName(preferences.name)
  if (preferences && !locations.length && preferences.locations?.length) {
    setLocations(preferences.locations)
  }
  if (preferences && !roles.length && preferences.role_types?.length) {
    setRoles(preferences.role_types)
  }

  const save = async (patch: Record<string, unknown>) => {
    try {
      await savePrefs.mutateAsync(patch)
      return true
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not save that.')
      return false
    }
  }

  const current = STEPS[step]

  const next = async () => {
    if (current.id === 'you') {
      if (!name.trim()) {
        toast.error('Your name goes on every tailored resume — it can’t be blank.')
        return
      }
      if (!(await save({ name: name.trim(), email: email.trim() }))) return
    }
    if (current.id === 'search') {
      if (!locations.length || !roles.length) {
        toast.error('Add at least one location and one role.')
        return
      }
      const patch: Record<string, unknown> = { locations, role_types: roles }
      if (ctc) patch.target_ctc_min_lpa = Number(ctc)
      if (!(await save(patch))) return
    }
    // backend / sources / delivery are self-saving (each field persists on its own
    // Save click) and optional, so Continue just advances — same as leaving them blank.
    setStep((s) => Math.min(STEPS.length - 1, s + 1))
    status.refetch()
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="Set up JobPilot"
      subtitle="Each step saves as you go — you can close this and come back."
      footer={
        <>
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </button>
          {current.id === 'done' ? (
            <button type="button" className="btn-primary btn-sm" onClick={onClose}>
              Start hunting
            </button>
          ) : (
            <button
              type="button"
              className="btn-primary btn-sm"
              onClick={next}
              disabled={savePrefs.isPending}
            >
              {savePrefs.isPending ? <Spinner className="h-3.5 w-3.5" /> : null}
              Continue
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          )}
        </>
      }
    >
      {/* Progress rail */}
      <ol className="mb-6 flex flex-wrap items-center gap-2 text-xs">
        {STEPS.map((s, i) => (
          <li key={s.id} className="flex items-center gap-2">
            <span
              className={clsx(
                'flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold',
                i < step
                  ? 'bg-ok/15 text-ok'
                  : i === step
                    ? 'bg-accent text-accent-ink'
                    : 'bg-raised text-faint',
              )}
            >
              {i < step ? <Check className="h-3 w-3" /> : i + 1}
            </span>
            <span className={i === step ? 'font-medium text-ink' : 'text-faint'}>
              {s.label}
            </span>
            {i < STEPS.length - 1 && <span className="text-faint">›</span>}
          </li>
        ))}
      </ol>

      {current.id === 'you' && (
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Your full name" hint="Appears on every tailored resume">
            <input
              className="input"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Email" hint="Optional">
            <input
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
        </div>
      )}

      {current.id === 'resume' && (
        <div className="space-y-4">
          <p className="text-sm text-muted">
            Upload your resume, then press <strong>Read it</strong>. JobPilot extracts a
            profile you'll check on the next step.
          </p>
          <ResumeManager onExtracted={() => setStep(2)} />
        </div>
      )}

      {current.id === 'profile' && (
        <div className="space-y-4">
          <p className="text-sm text-muted">
            This is what every job gets scored against. Fix anything that's wrong, then
            confirm it.
          </p>
          <ProfileForm />
          {!profile.data?.verified && (
            <button
              type="button"
              className="btn-primary btn-sm"
              onClick={async () => {
                await verify.mutateAsync(true)
                toast.success('Profile confirmed.')
                setStep(3)
              }}
            >
              <Check className="h-3.5 w-3.5" />
              Looks right — confirm and continue
            </button>
          )}
        </div>
      )}

      {current.id === 'backend' && <BackendStep />}

      {current.id === 'sources' && <SourcesStep />}

      {current.id === 'delivery' && <DeliveryStep />}

      {current.id === 'search' && (
        <div className="space-y-5">
          <Field
            label={
              <>
                Where would you work? <HelpTip id="prefs.locations" />
              </>
            }
            hint="The first is treated as your first choice"
          >
            <TagInput
              values={locations}
              onChange={setLocations}
              placeholder="e.g. Bengaluru, Remote"
            />
          </Field>
          <Field
            label={
              <>
                What kind of role? <HelpTip id="prefs.role_types" />
              </>
            }
          >
            <TagInput values={roles} onChange={setRoles} placeholder="e.g. Backend, SWE" />
          </Field>
          <Field
            label={
              <>
                Minimum package <HelpTip id="prefs.target_ctc" />
              </>
            }
            hint="LPA. Optional — JobPilot never suggests asking for less."
          >
            <input
              className="input max-w-[12rem]"
              type="number"
              min={0}
              value={ctc}
              onChange={(e) => setCtc(e.target.value)}
            />
          </Field>
        </div>
      )}

      {current.id === 'done' && (
        <div className="space-y-4 py-4 text-center">
          <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-ok/15">
            <Check className="h-6 w-6 text-ok" />
          </div>
          <div>
            <p className="text-base font-semibold text-ink">You're set up.</p>
            <p className="mx-auto mt-1 max-w-md text-sm text-muted">
              Start a hunt whenever you like, or set run times on the Scheduler page and
              let JobPilot do it on its own.
            </p>
          </div>
          <div className="flex justify-center gap-2">
            <Link to="/scheduler" className="btn-secondary btn-sm" onClick={onClose}>
              Set run times
            </Link>
            <Link to="/me" className="btn-ghost btn-sm" onClick={onClose}>
              Add delivery channels
            </Link>
          </div>
        </div>
      )}
    </Dialog>
  )
}
