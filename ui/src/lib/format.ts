/** Display formatting. Everything the user reads as a number or a date passes through here. */

export function formatDate(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function relativeTime(iso?: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const seconds = Math.round((then - Date.now()) / 1000)
  const abs = Math.abs(seconds)
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  if (abs < 60) return rtf.format(Math.round(seconds), 'second')
  if (abs < 3600) return rtf.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(seconds / 3600), 'hour')
  if (abs < 2592000) return rtf.format(Math.round(seconds / 86400), 'day')
  return rtf.format(Math.round(seconds / 2592000), 'month')
}

export function formatDuration(seconds?: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  if (seconds < 1) return '<1s'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return s ? `${m}m ${s}s` : `${m}m`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

/** Money, with enough precision that a fraction of a cent doesn't render as "$0.00". */
export function formatUsd(usd?: number | null): string {
  if (!usd) return '$0.00'
  if (usd < 0.01) return `<$0.01`
  return `$${usd.toFixed(usd < 1 ? 3 : 2)}`
}

export function formatTokens(n?: number | null): string {
  if (!n) return '0'
  if (n < 1000) return String(n)
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`
  return `${(n / 1_000_000).toFixed(1)}M`
}

export function formatLpa(min?: number | null, max?: number | null, fallback = ''): string {
  if (min == null && max == null) return fallback || '—'
  if (min != null && max != null && min !== max) return `${min}–${max} LPA`
  return `${min ?? max} LPA`
}

export function formatNumber(n?: number | null): string {
  if (n == null) return '—'
  return n.toLocaleString()
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim()
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`
}

/** Score → a semantic tone the whole UI agrees on. */
export function scoreTone(score?: number | null): 'ok' | 'warn' | 'neutral' {
  if (score == null) return 'neutral'
  if (score >= 75) return 'ok'
  if (score >= 60) return 'warn'
  return 'neutral'
}
