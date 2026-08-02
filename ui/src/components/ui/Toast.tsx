/** Toasts. Supports an action button, which is what makes "Mark applied · Undo" work. */
import clsx from 'clsx'
import { AlertCircle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

type ToastKind = 'success' | 'error' | 'info' | 'warn'

interface Toast {
  id: number
  kind: ToastKind
  message: string
  actionLabel?: string
  onAction?: () => void
}

interface ToastApi {
  show: (message: string, options?: Partial<Omit<Toast, 'id' | 'message'>> & { duration?: number }) => number
  success: (message: string, options?: { actionLabel?: string; onAction?: () => void; duration?: number }) => number
  error: (message: string) => number
  info: (message: string) => number
  dismiss: (id: number) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const ICONS: Record<ToastKind, ReactNode> = {
  success: <CheckCircle2 className="h-4 w-4 text-ok" />,
  error: <XCircle className="h-4 w-4 text-danger" />,
  warn: <AlertCircle className="h-4 w-4 text-warn" />,
  info: <Info className="h-4 w-4 text-info" />,
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())

  const dismiss = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id))
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const show = useCallback<ToastApi['show']>(
    (message, options = {}) => {
      const { duration, ...rest } = options
      const id = nextId.current++
      const toast: Toast = { id, kind: 'info', message, ...rest }
      setToasts((list) => [...list, toast])
      // Errors stay until dismissed; an action gets long enough to actually click.
      const ms = duration ?? (toast.kind === 'error' ? 0 : toast.onAction ? 10_000 : 4_000)
      if (ms > 0) timers.current.set(id, setTimeout(() => dismiss(id), ms))
      return id
    },
    [dismiss],
  )

  const api = useMemo<ToastApi>(
    () => ({
      show,
      dismiss,
      success: (message, options) => show(message, { kind: 'success', ...options }),
      error: (message) => show(message, { kind: 'error' }),
      info: (message) => show(message, { kind: 'info' }),
    }),
    [show, dismiss],
  )

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className={clsx(
              'pointer-events-auto flex items-start gap-3 rounded-xl border border-line',
              'bg-surface px-4 py-3 shadow-pop animate-slide-up',
            )}
          >
            <span className="mt-0.5 shrink-0">{ICONS[toast.kind]}</span>
            <p className="min-w-0 flex-1 text-sm text-ink">{toast.message}</p>
            {toast.onAction && toast.actionLabel && (
              <button
                type="button"
                className="shrink-0 text-sm font-medium text-accent hover:underline"
                onClick={() => {
                  toast.onAction?.()
                  dismiss(toast.id)
                }}
              >
                {toast.actionLabel}
              </button>
            )}
            <button
              type="button"
              className="shrink-0 text-faint hover:text-ink"
              onClick={() => dismiss(toast.id)}
              aria-label="Dismiss"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}
