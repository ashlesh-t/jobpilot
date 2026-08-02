/** Header: where you are, what's running, what it's costing, and the theme toggle. */
import clsx from 'clsx'
import { Activity, Coins, Monitor, Moon, Sun } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { HelpTip } from '@/components/ui/Help'
import { Spinner } from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { formatTokens, formatUsd } from '@/lib/format'
import { useRuns } from '@/lib/hooks'
import { useTheme } from '@/lib/theme'
import type { ThemeChoice } from '@/lib/theme'

interface CostSummary {
  window: string
  usd: number
  tokens_in: number
  tokens_out: number
  subscription_tokens: number
}

function useCost() {
  return useQuery({
    queryKey: ['cost', 'month'],
    queryFn: () => api.get<CostSummary>('/api/cost?window=month'),
    staleTime: 60_000,
    retry: false,
  })
}

const THEME_ORDER: ThemeChoice[] = ['light', 'dark', 'system']
const THEME_ICON = { light: Sun, dark: Moon, system: Monitor }
const THEME_LABEL = {
  light: 'Light theme',
  dark: 'Dark theme',
  system: 'Following your system theme',
}

export function TopBar({ title }: { title: string }) {
  const { choice, setChoice } = useTheme()
  const { data: runs } = useRuns()
  const { data: cost } = useCost()
  const active = runs?.active

  const Icon = THEME_ICON[choice]

  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-4 border-b border-line bg-canvas/85 px-6 backdrop-blur">
      <h1 className="truncate text-[15px] font-semibold tracking-tight text-ink">{title}</h1>

      <div className="ml-auto flex items-center gap-2">
        {active && (
          <Link
            to="/hunt"
            className="chip-accent hover:bg-accent-soft/70"
            title={`Run ${active.id} is ${active.status}`}
          >
            <Spinner className="h-3 w-3" />
            <span className="hidden sm:inline">Run in progress</span>
            {typeof active.progress === 'number' && (
              <span className="tabular-nums">{Math.round(active.progress * 100)}%</span>
            )}
          </Link>
        )}

        {cost && (cost.usd > 0 || cost.subscription_tokens > 0) && (
          <span
            className="chip-neutral"
            title={
              cost.usd > 0
                ? `${formatUsd(cost.usd)} in the last 30 days`
                : `${formatTokens(cost.subscription_tokens)} tokens on your subscription — no per-token charge`
            }
          >
            {cost.usd > 0 ? (
              <>
                <Coins className="h-3 w-3" />
                {formatUsd(cost.usd)}
              </>
            ) : (
              <>
                <Activity className="h-3 w-3" />
                {formatTokens(cost.subscription_tokens)} tok
              </>
            )}
            <HelpTip id={cost.usd > 0 ? 'cost.meter' : 'cost.subscription'} />
          </span>
        )}

        <button
          type="button"
          className={clsx('btn-icon')}
          title={THEME_LABEL[choice]}
          aria-label={THEME_LABEL[choice]}
          onClick={() => setChoice(THEME_ORDER[(THEME_ORDER.indexOf(choice) + 1) % 3])}
        >
          <Icon className="h-[18px] w-[18px]" />
        </button>
      </div>
    </header>
  )
}
