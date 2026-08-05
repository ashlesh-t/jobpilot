/** Account-creation screen. Not wrapped in AppLayout, same reasoning as Login. */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Card } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { useSignup } from '@/lib/auth'

export function SignupPage() {
  const navigate = useNavigate()
  const signup = useSignup()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
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
    try {
      await signup.mutateAsync({
        username: username.trim(),
        password,
        email: email.trim() || undefined,
      })
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Could not create that account.')
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

        <Card title="Create an account" subtitle="Takes a minute — set up comes after." className="shadow-pop">
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
              <span className="label">Email</span>
              <input
                className="input"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <span className="mt-1 block text-xs text-faint">Optional</span>
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

            {error && <p className="text-sm text-danger">{error}</p>}

            <button
              type="submit"
              className="btn-primary btn-sm w-full justify-center"
              disabled={signup.isPending}
            >
              {signup.isPending ? 'Creating account…' : 'Sign up'}
            </button>
          </form>
        </Card>

        <p className="mt-4 text-center text-sm text-muted">
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-accent hover:underline">
            Log in
          </Link>
        </p>
      </div>
    </div>
  )
}
