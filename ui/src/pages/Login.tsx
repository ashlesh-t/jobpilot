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
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm animate-slide-up">
        <div className="mb-7 flex items-center justify-center gap-2.5">
          <span
            className="grid h-10 w-10 place-items-center rounded-xl text-base font-bold text-accent-ink shadow-[0_1px_0_0_rgb(255_255_255/0.2)_inset,0_4px_14px_-3px_rgb(var(--accent)/0.55)]"
            style={{
              backgroundImage: 'linear-gradient(135deg, rgb(var(--accent)), rgb(var(--accent-2)))',
            }}
          >
            JP
          </span>
          <span className="text-lg font-semibold tracking-tight text-ink">JobPilot</span>
        </div>

        <Card title="Log in" subtitle="Welcome back." className="shadow-pop">
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
