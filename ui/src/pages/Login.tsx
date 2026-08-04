/** Sign-in screen. Not wrapped in AppLayout — it's reachable before there's a session
 *  to build a sidebar/topbar out of. */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Card } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { useLogin } from '@/lib/auth'

export function LoginPage() {
  const navigate = useNavigate()
  const login = useLogin()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password) {
      setError('Enter your username and password.')
      return
    }
    try {
      await login.mutateAsync({ username: username.trim(), password })
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not sign in.')
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

        <Card title="Log in" subtitle="Welcome back.">
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
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>

            {error && <p className="text-sm text-danger">{error}</p>}

            <button
              type="submit"
              className="btn-primary btn-sm w-full justify-center"
              disabled={login.isPending}
            >
              {login.isPending ? 'Signing in…' : 'Log in'}
            </button>
          </form>
        </Card>

        <p className="mt-4 text-center text-sm text-muted">
          Don't have an account?{' '}
          <Link to="/signup" className="font-medium text-accent hover:underline">
            Sign up
          </Link>
        </p>
      </div>
    </div>
  )
}
