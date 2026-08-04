import { createBrowserRouter } from 'react-router-dom'

import { RequireAuth } from '@/components/auth/RequireAuth'
import { AppLayout } from '@/components/layout/AppLayout'
import { ApplicationsPage } from '@/pages/Applications'
import { AssistantPage } from '@/pages/Assistant'
import { HomePage } from '@/pages/Home'
import { JobHuntPage } from '@/pages/JobHunt'
import { LoginPage } from '@/pages/Login'
import { MyInfoPage } from '@/pages/MyInfo'
import { NotFoundPage } from '@/pages/NotFound'
import { ResumesPage } from '@/pages/Resumes'
import { SchedulerPage } from '@/pages/Scheduler'
import { SettingsPage } from '@/pages/Settings'
import { SignupPage } from '@/pages/Signup'
import { WhoAmI } from '@/pages/WhoAmI'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/signup', element: <SignupPage /> },
  {
    path: '/',
    element: <RequireAuth />,
    children: [
      {
        path: '/',
        element: <AppLayout />,
        children: [
          { index: true, element: <HomePage /> },
          { path: 'hunt', element: <JobHuntPage /> },
          { path: 'hunt/:runId', element: <JobHuntPage /> },
          { path: 'applications', element: <ApplicationsPage /> },
          { path: 'resumes', element: <ResumesPage /> },
          { path: 'scheduler', element: <SchedulerPage /> },
          { path: 'me', element: <MyInfoPage /> },
          { path: 'assistant', element: <AssistantPage /> },
          { path: 'settings', element: <SettingsPage /> },
          { path: 'whoami', element: <WhoAmI /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
])
