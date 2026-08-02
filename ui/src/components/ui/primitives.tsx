/** Small shared building blocks. Everything visual in the app is composed from these,
 *  so a spacing or tone decision is made once. */
import clsx from 'clsx'
import { AlertCircle, Inbox, Loader2, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

/* -------------------------------------------------------------------------- */
/* Card                                                                        */
/* -------------------------------------------------------------------------- */
export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={clsx('card', className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <p className="card-sub mt-0.5">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={clsx('card-pad', bodyClassName)}>{children}</div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Status chip                                                                 */
/* -------------------------------------------------------------------------- */
export type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'accent'

const TONE_CLASS: Record<Tone, string> = {
  neutral: 'chip-neutral',
  ok: 'chip-ok',
  warn: 'chip-warn',
  danger: 'chip-danger',
  accent: 'chip-accent',
}

export function Chip({
  tone = 'neutral',
  children,
  className,
  icon,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
  icon?: ReactNode
}) {
  return (
    <span className={clsx(TONE_CLASS[tone], className)}>
      {icon}
      {children}
    </span>
  )
}

/** Maps every run / phase status the backend can emit to a tone and a label. */
const STATUS_MAP: Record<string, { tone: Tone; label: string }> = {
  pending: { tone: 'neutral', label: 'Waiting' },
  running: { tone: 'accent', label: 'Running' },
  done: { tone: 'ok', label: 'Done' },
  error: { tone: 'danger', label: 'Failed' },
  cancelled: { tone: 'warn', label: 'Stopped' },
  skipped: { tone: 'neutral', label: 'Skipped' },
  waiting_network: { tone: 'warn', label: 'Waiting for network' },
  applied: { tone: 'accent', label: 'Applied' },
  selected: { tone: 'accent', label: 'Shortlisted' },
  interview: { tone: 'accent', label: 'Interview' },
  final_round: { tone: 'accent', label: 'Final round' },
  placed: { tone: 'ok', label: 'Offer' },
  rejected: { tone: 'danger', label: 'Rejected' },
  ghosted: { tone: 'neutral', label: 'No reply' },
  ok: { tone: 'ok', label: 'OK' },
  warn: { tone: 'warn', label: 'Warning' },
  fail: { tone: 'danger', label: 'Problem' },
}

export function StatusChip({ status, className }: { status: string; className?: string }) {
  const entry = STATUS_MAP[status] ?? { tone: 'neutral' as Tone, label: status }
  return (
    <Chip tone={entry.tone} className={className}>
      {status === 'running' && <Loader2 className="h-3 w-3 animate-spin" />}
      {entry.label}
    </Chip>
  )
}

/* -------------------------------------------------------------------------- */
/* Async states                                                                */
/* -------------------------------------------------------------------------- */
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx('h-4 w-4 animate-spin', className)} />
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted">
      <Spinner />
      {label}
    </div>
  )
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2.5" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton h-9 w-full" />
      ))}
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode
  title: string
  description?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <div className="rounded-full bg-raised p-3 text-faint">
        {icon ?? <Inbox className="h-5 w-5" />}
      </div>
      <div>
        <p className="text-sm font-medium text-ink">{title}</p>
        {description && (
          <p className="mx-auto mt-1 max-w-md text-sm text-muted">{description}</p>
        )}
      </div>
      {action}
    </div>
  )
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown
  onRetry?: () => void
}) {
  const message =
    error instanceof Error ? error.message : typeof error === 'string' ? error : 'Something went wrong.'
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
      <AlertCircle className="h-5 w-5 text-danger" />
      <p className="max-w-md text-sm text-ink">{message}</p>
      {onRetry && (
        <button type="button" className="btn-secondary btn-sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Dialog                                                                      */
/* -------------------------------------------------------------------------- */
export function Dialog({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  size = 'md',
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg' | 'xl'
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    ref.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
    }
  }, [open, onClose])

  if (!open) return null

  const width = {
    sm: 'max-w-md',
    md: 'max-w-2xl',
    lg: 'max-w-4xl',
    xl: 'max-w-6xl',
  }[size]

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-[6vh] animate-fade-in"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        className={clsx(
          'w-full rounded-2xl border border-line bg-surface shadow-pop outline-none animate-slide-up',
          width,
        )}
      >
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-ink">{title}</h2>
            {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
          </div>
          <button type="button" className="btn-icon shrink-0" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="max-h-[68vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <footer className="flex items-center justify-end gap-2 border-t border-line px-5 py-3.5">
            {footer}
          </footer>
        )}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Misc                                                                        */
/* -------------------------------------------------------------------------- */
export function Field({
  label,
  help,
  hint,
  error,
  children,
}: {
  label: ReactNode
  help?: ReactNode
  hint?: ReactNode
  error?: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="label">
        {label}
        {help}
      </span>
      {children}
      {error ? (
        <span className="mt-1 block text-xs text-danger">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-xs text-faint">{hint}</span>
      ) : null}
    </label>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label?: ReactNode
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="inline-flex items-center gap-2.5 text-sm text-ink disabled:opacity-50"
    >
      <span
        className={clsx(
          'relative h-5 w-9 shrink-0 rounded-full transition-colors',
          checked ? 'bg-accent' : 'bg-line',
        )}
      >
        <span
          className={clsx(
            'absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all',
            checked ? 'left-[1.125rem]' : 'left-0.5',
          )}
        />
      </span>
      {label}
    </button>
  )
}

export function ProgressBar({ value, tone = 'accent' }: { value: number; tone?: Tone }) {
  const pct = Math.max(0, Math.min(100, value * 100))
  const bar = {
    accent: 'bg-accent',
    ok: 'bg-ok',
    warn: 'bg-warn',
    danger: 'bg-danger',
    neutral: 'bg-faint',
  }[tone]
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-line">
      <div className={clsx('h-full rounded-full transition-all duration-500', bar)}
           style={{ width: `${pct}%` }} />
    </div>
  )
}
