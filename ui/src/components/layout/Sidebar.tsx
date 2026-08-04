/** Collapsible left navigation. Collapsed state persists, because a user who chose the
 *  icon rail should not have to choose it again on every load. */
import clsx from 'clsx'
import {
  Briefcase,
  CalendarClock,
  ClipboardList,
  FileText,
  LayoutDashboard,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Sparkles,
  UserRound,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
}

const NAV: NavItem[] = [
  { to: '/', label: 'Home', icon: LayoutDashboard, end: true },
  { to: '/hunt', label: 'Job Hunt', icon: Briefcase },
  { to: '/applications', label: 'Applications', icon: ClipboardList },
  { to: '/resumes', label: 'Tailored Resumes', icon: FileText },
  { to: '/scheduler', label: 'Scheduler', icon: CalendarClock },
  { to: '/me', label: 'My Info', icon: UserRound },
  { to: '/assistant', label: 'Assistant', icon: MessageSquare },
  { to: '/settings', label: 'Settings', icon: Settings },
  { to: '/whoami', label: 'About JobPilot', icon: Sparkles },
]

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  return (
    <aside
      className={clsx(
        'flex shrink-0 flex-col border-r border-line bg-surface transition-[width] duration-200',
        collapsed ? 'w-[4.25rem]' : 'w-60',
      )}
    >
      <div
        className={clsx(
          'flex h-14 items-center gap-2.5 border-b border-line px-4',
          collapsed && 'justify-center px-0',
        )}
      >
        <span
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-sm font-bold text-accent-ink shadow-[0_1px_0_0_rgb(255_255_255/0.2)_inset,0_2px_8px_-2px_rgb(var(--accent)/0.55)]"
          style={{
            backgroundImage: 'linear-gradient(135deg, rgb(var(--accent)), rgb(var(--accent-2)))',
          }}
        >
          JP
        </span>
        {!collapsed && (
          <span className="truncate text-sm font-semibold tracking-tight text-ink">
            JobPilot
          </span>
        )}
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2.5">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            title={collapsed ? label : undefined}
            className={({ isActive }) =>
              clsx('nav-item', collapsed && 'justify-center px-0', isActive && 'nav-item-active')
            }
          >
            {({ isActive }) => (
              <>
                <Icon
                  className={clsx(
                    'h-[18px] w-[18px] shrink-0 transition-transform duration-150',
                    isActive && 'scale-105',
                  )}
                />
                {!collapsed && <span className="truncate">{label}</span>}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-line p-2.5">
        <button
          type="button"
          onClick={onToggle}
          className={clsx('btn-ghost w-full', collapsed && 'justify-center px-0')}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-[18px] w-[18px]" />
          ) : (
            <>
              <PanelLeftClose className="h-[18px] w-[18px]" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
