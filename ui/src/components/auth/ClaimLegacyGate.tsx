/** Blocking screen for an auto-created legacy account (`must_set_password: true`) —
 *  the backfill account created when an existing single-user install upgrades to
 *  multi-user. It has no real credentials yet, so nothing else in the app should be
 *  usable until it does. A dedicated screen (not a modal) because RequireAuth already
 *  renders full-page for the signed-out case, and this state needs the same treatment:
 *  there's nothing behind it worth dimming. */
import { useState } from 'react'
import type { FormEvent } from 'react'

import { Card } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { useClaimLegacy } from '@/lib/auth'

export function ClaimLegacyGate() {
  const claim = useClaimLegacy()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password) {
      setError('Choose a username and password.')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    try {
      await claim.mutateAsync({ username: username.trim(), password })
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not claim this account.')
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-accent text-sm font-bold text-accent-ink">
            JP
          </span>
          <span className="text-base font-semibold tracking-tight text-ink">JobPilot</span>
        </div>

        <Card
          title="Finish upgrading your account"
          subtitle="This install was upgraded to support multiple accounts. Pick a username and password to keep using it."
        >
          <form className="space-y-4" onSubmit={onSubmit}>
            <label className="block">
              <span className="label">Username</span>
              <input
                className="input"
                autoFocus
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="label">Password</span>
              <input
                className="input"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <span className="mt-1 block text-xs text-faint">At least 8 characters</span>
            </label>
            <label className="block">
              <span className="label">Confirm password</span>
              <input
                className="input"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </label>

            {error && <p className="text-sm text-danger">{error}</p>}

            <button
              type="submit"
              className="btn-primary btn-sm w-full justify-center"
              disabled={claim.isPending}
            >
              {claim.isPending ? 'Saving…' : 'Set username and password'}
            </button>
          </form>
        </Card>
      </div>
    </div>
  )
}
