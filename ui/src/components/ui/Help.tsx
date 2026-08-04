/** The help affordance used everywhere: an info dot that reveals one sentence.
 *
 *  Copy lives in src/content/help.ts, keyed by id — the component never inlines text,
 *  so the product's whole explanatory voice is reviewable in one file. */
import clsx from 'clsx'
import { HelpCircle } from 'lucide-react'
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { helpFor } from '@/content/help'

export function HelpTip({
  id,
  text,
  className,
  side = 'top',
}: {
  /** Key into src/content/help.ts */
  id?: string
  /** Literal copy, for the rare case that isn't reusable */
  text?: string
  className?: string
  side?: 'top' | 'bottom'
}) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLSpanElement>(null)
  const tipRef = useRef<HTMLSpanElement>(null)
  const [shift, setShift] = useState(0)
  const tipId = useId()
  const body = text ?? (id ? helpFor(id) : undefined)

  // The tooltip is centered under its trigger by default — for a trigger near the
  // edge of the screen (e.g. the last stat tile in a row) that centering pushes half
  // the box off-screen. Nudge it back on-screen once we know its actual position.
  useLayoutEffect(() => {
    if (!open) {
      setShift(0)
      return
    }
    const el = tipRef.current
    if (!el) return
    const margin = 8
    const rect = el.getBoundingClientRect()
    if (rect.right > window.innerWidth - margin) {
      setShift(window.innerWidth - margin - rect.right)
    } else if (rect.left < margin) {
      setShift(margin - rect.left)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // A missing key should be loud in development and invisible in production, never a
  // broken-looking empty bubble.
  if (!body) {
    if (import.meta.env.DEV && id) console.warn(`[help] no copy for "${id}"`)
    return null
  }

  return (
    <span ref={wrapRef} className={clsx('relative inline-flex', className)}>
      <button
        type="button"
        aria-label="What is this?"
        aria-expanded={open}
        aria-describedby={open ? tipId : undefined}
        onClick={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setOpen((v) => !v)
        }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        className="text-faint transition-colors hover:text-accent"
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>
      {open && (
        <span
          ref={tipRef}
          id={tipId}
          role="tooltip"
          style={{ transform: `translateX(calc(-50% + ${shift}px))` }}
          className={clsx(
            'absolute left-1/2 z-40 w-64 max-w-[calc(100vw-1rem)] rounded-lg border border-line',
            'bg-surface px-3 py-2 text-xs font-normal leading-relaxed text-muted shadow-pop',
            side === 'top' ? 'bottom-full mb-2' : 'top-full mt-2',
          )}
        >
          {body}
        </span>
      )}
    </span>
  )
}

/** The per-page "What is this?" drawer — the longer explanation a tooltip can't hold. */
export function PageHelp({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        className="btn-ghost btn-sm"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <HelpCircle className="h-3.5 w-3.5" />
        What is this?
      </button>
      {open && (
        <div className="mt-3 rounded-xl border border-line bg-accent-soft/50 px-4 py-3 animate-slide-up">
          <p className="text-sm font-medium text-ink">{title}</p>
          <div className="mt-1.5 space-y-2 text-sm leading-relaxed text-muted">{children}</div>
        </div>
      )}
    </>
  )
}
