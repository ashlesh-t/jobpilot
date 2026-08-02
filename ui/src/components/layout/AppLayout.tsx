/** The shell every page renders inside. */
import { Outlet, useLocation } from 'react-router-dom'

import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { useLocalStorage } from '@/lib/hooks'

const TITLES: Record<string, string> = {
  '/': 'Home',
  '/hunt': 'Job Hunt',
  '/applications': 'Applications',
  '/resumes': 'Tailored Resumes',
  '/scheduler': 'Scheduler',
  '/me': 'My Info',
  '/assistant': 'Assistant',
  '/settings': 'Settings',
}

function titleFor(pathname: string): string {
  if (TITLES[pathname]) return TITLES[pathname]
  const base = `/${pathname.split('/')[1] ?? ''}`
  return TITLES[base] ?? 'JobPilot'
}

export function AppLayout() {
  const [collapsed, setCollapsed] = useLocalStorage('jobpilot.sidebar.collapsed', false)
  const { pathname } = useLocation()

  return (
    <div className="flex h-full">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar title={titleFor(pathname)} />
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1400px] px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
