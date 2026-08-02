/**
 * Dashboard charts.
 *
 * Every chart here answers "how much", not "which one" — so all of them use a single
 * blue hue on an ordinal ramp rather than a categorical palette. That removes
 * colour-vision-deficiency risk entirely and keeps the dashboard visually calm.
 * Consequently none of them needs a legend: there is one series, and the title names it.
 *
 * Ramp steps are read from CSS variables (`--viz-*` in styles/theme.css) so light and
 * dark are separately chosen — a flipped light ramp fails contrast on a dark surface.
 */
import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { TooltipProps } from 'recharts'

import { EmptyState } from '@/components/ui/primitives'
import { useTheme } from '@/lib/theme'

/* -------------------------------------------------------------------------- */
/* Tokens                                                                      */
/* -------------------------------------------------------------------------- */
/** Recharts needs literal colours, so resolve the CSS variables once per theme. */
function useVizTokens() {
  const { resolved } = useTheme()
  const [tokens, setTokens] = useState<Record<string, string>>({})

  useEffect(() => {
    const style = getComputedStyle(document.documentElement)
    const read = (name: string) => style.getPropertyValue(name).trim()
    setTokens({
      solo: read('--viz-solo'),
      ramp1: read('--viz-1'),
      ramp2: read('--viz-2'),
      ramp3: read('--viz-3'),
      ramp4: read('--viz-4'),
      ramp5: read('--viz-5'),
      ramp6: read('--viz-6'),
      grid: read('--viz-grid'),
      axis: read('--viz-axis'),
    })
  }, [resolved])

  return tokens
}

const AXIS_FONT = 11

/* -------------------------------------------------------------------------- */
/* Tooltip                                                                     */
/* -------------------------------------------------------------------------- */
function VizTooltip({
  active,
  payload,
  label,
  unit = '',
}: TooltipProps<number, string> & { unit?: string }) {
  if (!active || !payload?.length) return null
  const point = payload[0]
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 shadow-pop">
      <p className="text-xs font-medium text-ink">{point.payload.tooltipLabel ?? label}</p>
      <p className="mt-0.5 text-xs tabular-nums text-muted">
        {point.value}
        {unit ? ` ${unit}` : ''}
      </p>
      {point.payload.sub && (
        <p className="mt-0.5 text-xs text-faint">{point.payload.sub}</p>
      )}
    </div>
  )
}

function ChartFrame({
  height = 200,
  empty,
  children,
}: {
  height?: number
  empty: boolean
  children: React.ReactElement
}) {
  if (empty) {
    return (
      <EmptyState
        title="Nothing to chart yet"
        description="This fills in after your first completed run."
      />
    )
  }
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Score distribution — ordered buckets, so an ordinal ramp                    */
/* -------------------------------------------------------------------------- */
export function ScoreDistribution({
  buckets,
}: {
  buckets: { range: string; count: number }[]
}) {
  const t = useVizTokens()
  const ramp = [t.ramp1, t.ramp3, t.ramp5, t.ramp6]
  const data = buckets.map((b) => ({
    ...b,
    tooltipLabel: `Match score ${b.range}`,
    sub: b.range === '75-100' ? 'Strong matches' : undefined,
  }))
  const empty = data.every((d) => !d.count)

  return (
    <ChartFrame empty={empty}>
      <BarChart data={data} margin={{ top: 18, right: 8, bottom: 4, left: -18 }}>
        <XAxis
          dataKey="range"
          tickLine={false}
          axisLine={{ stroke: t.grid }}
          tick={{ fill: t.axis, fontSize: AXIS_FONT }}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tick={{ fill: t.axis, fontSize: AXIS_FONT }}
          allowDecimals={false}
          width={44}
        />
        <Tooltip content={<VizTooltip unit="jobs" />} cursor={{ fill: t.grid, opacity: 0.35 }} />
        <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={64}>
          {data.map((entry, i) => (
            <Cell key={entry.range} fill={ramp[i] ?? t.solo} />
          ))}
          <LabelList
            dataKey="count"
            position="top"
            fill={t.axis}
            fontSize={AXIS_FONT}
            formatter={(v: number) => (v ? v : '')}
          />
        </Bar>
      </BarChart>
    </ChartFrame>
  )
}

/* -------------------------------------------------------------------------- */
/* Jobs per scan — one series over time, so one hue                            */
/* -------------------------------------------------------------------------- */
export function JobsPerScan({
  scans,
}: {
  scans: { id: number; started_at: string | null; jobs_scored: number; mode: string; engine: string }[]
}) {
  const t = useVizTokens()
  const data = [...scans]
    .reverse()
    .slice(-14)
    .map((scan) => ({
      label: scan.started_at
        ? new Date(scan.started_at).toLocaleDateString(undefined, {
            day: 'numeric',
            month: 'short',
          })
        : '—',
      count: scan.jobs_scored,
      tooltipLabel: scan.started_at
        ? new Date(scan.started_at).toLocaleString(undefined, {
            day: 'numeric',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit',
          })
        : 'Unknown date',
      sub: `${scan.mode} run · ${scan.engine}`,
    }))

  return (
    <ChartFrame empty={!data.length}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: -18 }}>
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={{ stroke: t.grid }}
          tick={{ fill: t.axis, fontSize: AXIS_FONT }}
          interval="preserveStartEnd"
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          tick={{ fill: t.axis, fontSize: AXIS_FONT }}
          allowDecimals={false}
          width={44}
        />
        <Tooltip content={<VizTooltip unit="jobs scored" />} cursor={{ fill: t.grid, opacity: 0.35 }} />
        <Bar dataKey="count" fill={t.solo} radius={[4, 4, 0, 0]} maxBarSize={28} />
      </BarChart>
    </ChartFrame>
  )
}

/* -------------------------------------------------------------------------- */
/* Sources — magnitude across long names, so horizontal bars in one hue        */
/* -------------------------------------------------------------------------- */
export function SourceBreakdown({
  sources,
}: {
  sources: { source: string; count: number }[]
}) {
  const t = useVizTokens()
  const data = [...sources]
    .sort((a, b) => b.count - a.count)
    .slice(0, 8)
    .map((s) => ({ ...s, tooltipLabel: s.source }))

  return (
    <ChartFrame empty={!data.length} height={Math.max(160, data.length * 30)}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 28, bottom: 4, left: 4 }}
      >
        <XAxis type="number" hide allowDecimals={false} />
        <YAxis
          type="category"
          dataKey="source"
          tickLine={false}
          axisLine={false}
          tick={{ fill: t.axis, fontSize: AXIS_FONT }}
          width={96}
        />
        <Tooltip content={<VizTooltip unit="jobs" />} cursor={{ fill: t.grid, opacity: 0.35 }} />
        <Bar dataKey="count" fill={t.solo} radius={[0, 4, 4, 0]} barSize={14}>
          <LabelList
            dataKey="count"
            position="right"
            fill={t.axis}
            fontSize={AXIS_FONT}
          />
        </Bar>
      </BarChart>
    </ChartFrame>
  )
}

/* -------------------------------------------------------------------------- */
/* Application funnel — ordered stages, so an ordinal ramp                     */
/* -------------------------------------------------------------------------- */
const STAGE_LABELS: Record<string, string> = {
  applied: 'Applied',
  selected: 'Shortlisted',
  interview: 'Interview',
  final_round: 'Final round',
  placed: 'Offer',
}

export function ApplicationFunnel({
  stages,
}: {
  stages: { stage: string; count: number }[]
}) {
  const t = useVizTokens()
  const ramp = [t.ramp1, t.ramp2, t.ramp3, t.ramp5, t.ramp6]
  const total = stages[0]?.count ?? 0
  const data = stages.map((s, i) => ({
    ...s,
    label: STAGE_LABELS[s.stage] ?? s.stage,
    tooltipLabel: STAGE_LABELS[s.stage] ?? s.stage,
    sub:
      total && i > 0
        ? `${Math.round((s.count / total) * 100)}% of everything you applied to`
        : undefined,
    fill: ramp[i] ?? t.solo,
  }))

  return (
    <ChartFrame empty={!total} height={Math.max(160, data.length * 34)}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 28, bottom: 4, left: 4 }}
      >
        <XAxis type="number" hide allowDecimals={false} />
        <YAxis
          type="category"
          dataKey="label"
          tickLine={false}
          axisLine={false}
          tick={{ fill: t.axis, fontSize: AXIS_FONT }}
          width={92}
        />
        <Tooltip content={<VizTooltip unit="applications" />} cursor={{ fill: t.grid, opacity: 0.35 }} />
        <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={16}>
          {data.map((entry) => (
            <Cell key={entry.stage} fill={entry.fill} />
          ))}
          <LabelList
            dataKey="count"
            position="right"
            fill={t.axis}
            fontSize={AXIS_FONT}
            formatter={(v: number) => (v ? v : '')}
          />
        </Bar>
      </BarChart>
    </ChartFrame>
  )
}
