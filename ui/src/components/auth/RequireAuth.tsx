/** Auth boundary for the protected route tree. Wraps every route that needs a session
 *  (everything except /login and /signup) and resolves `useCurrentUser()` into one of
 *  four states: loading, signed-out (→ /login), legacy account pending claim (→ the
 *  claim gate), or signed in (→ the real app). */
import { Navigate, Outlet } from 'react-router-dom'

import { ClaimLegacyGate } from './ClaimLegacyGate'
import { Loading } from '@/components/ui/primitives'
import { useCurrentUser } from '@/lib/auth'

export function RequireAuth() {
  const { data: user, isLoading, isError } = useCurrentUser()

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <Loading label="Loading JobPilot…" />
      </div>
    )
  }

  if (isError || !user) {
    return <Navigate to="/login" replace />
  }

  if (user.must_set_password) {
    return <ClaimLegacyGate />
  }

  return <Outlet />
}
