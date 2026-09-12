import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Spinner } from '@/components/ui'

export default function Login() {
  const { user, signIn, signUp, loading } = useAuth()
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [identifier, setIdentifier] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (loading) return null
  if (user) return <Navigate to="/" replace />

  const changeMode = (next: 'signin' | 'signup') => {
    setMode(next)
    setError('')
    setPassword('')
    setConfirmPassword('')
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    if (mode === 'signup' && password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    setBusy(true)
    try {
      if (mode === 'signup') {
        await signUp({
          username: username.trim().toLowerCase(),
          email: email.trim().toLowerCase(),
          full_name: fullName.trim(),
          password,
        })
      } else {
        await signIn(identifier.trim().toLowerCase(), password)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : mode === 'signup' ? 'Sign up failed' : 'Sign in failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 lg:grid lg:grid-cols-[1.15fr_0.85fr]">
      <section className="relative hidden overflow-hidden border-r border-white/10 lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(33,150,243,0.22),transparent_30%),radial-gradient(circle_at_80%_70%,rgba(14,165,233,0.12),transparent_28%)]" />
        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="grid h-11 w-11 place-items-center rounded-2xl bg-brand-500 shadow-xl shadow-brand-500/25">
              <img src="/logo.svg" alt="" className="h-7 w-7" />
            </div>
            <div>
              <div className="text-xl font-bold tracking-tight text-white">SurveyHQ</div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Survey operations platform</div>
            </div>
          </div>
        </div>

        <div className="relative max-w-xl">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-brand-400">Your survey workspace</p>
          <h1 className="mt-4 text-4xl font-bold leading-tight tracking-[-0.03em] text-white xl:text-5xl">
            Build your own projects, then bring in the people you choose.
          </h1>
          <p className="mt-5 max-w-lg text-base leading-7 text-slate-400">
            Every account starts with a private workspace. Create survey and census projects,
            analyse data, publish dashboards, and share a project with another SurveyHQ user
            simply by adding their username.
          </p>
          <div className="mt-8 grid grid-cols-3 gap-3">
            {[
              ['Create', 'Your own private projects'],
              ['Collaborate', 'Add members by username'],
              ['Publish', 'Dashboards and shared views'],
            ].map(([title, text]) => (
              <div key={title} className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                <div className="text-sm font-semibold text-white">{title}</div>
                <div className="mt-1 text-xs leading-5 text-slate-500">{text}</div>
              </div>
            ))}
          </div>
        </div>

        <p className="relative text-xs text-slate-600">SurveyHQ · Self-hosted survey operations and analytics</p>
      </section>

      <section className="flex min-h-screen items-center justify-center bg-white px-5 py-10 dark:bg-slate-950 lg:min-h-0">
        <div className="w-full max-w-[440px]">
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500">
                <img src="/logo.svg" alt="" className="h-6 w-6" />
              </div>
              <span className="text-xl font-bold tracking-tight text-slate-950 dark:text-white">SurveyHQ</span>
            </div>
          </div>

          <div className="mb-7 grid grid-cols-2 rounded-xl bg-slate-100 p-1 dark:bg-slate-900">
            <button
              type="button"
              className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                mode === 'signin'
                  ? 'bg-white text-slate-950 shadow-sm dark:bg-slate-800 dark:text-white'
                  : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
              }`}
              onClick={() => changeMode('signin')}
            >
              Sign in
            </button>
            <button
              type="button"
              className={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                mode === 'signup'
                  ? 'bg-white text-slate-950 shadow-sm dark:bg-slate-800 dark:text-white'
                  : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
              }`}
              onClick={() => changeMode('signup')}
            >
              Create account
            </button>
          </div>

          <div>
            <p className="text-sm font-semibold text-brand-600 dark:text-brand-400">
              {mode === 'signup' ? 'Start your workspace' : 'Welcome back'}
            </p>
            <h2 className="mt-2 text-3xl font-bold tracking-[-0.025em] text-slate-950 dark:text-white">
              {mode === 'signup' ? 'Create your SurveyHQ account' : 'Sign in to your workspace'}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              {mode === 'signup'
                ? 'Your projects are private until you add another user as a member.'
                : 'Use your username or email address to continue.'}
            </p>
          </div>

          <form onSubmit={submit} className="mt-8 space-y-5">
            {error && (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
                {error}
              </div>
            )}

            {mode === 'signup' ? (
              <>
                <div>
                  <label className="label" htmlFor="username">Username</label>
                  <input
                    id="username"
                    type="text"
                    className="input mt-1.5"
                    autoComplete="username"
                    minLength={3}
                    maxLength={32}
                    pattern="[A-Za-z0-9][A-Za-z0-9._-]{2,31}"
                    placeholder="mosese"
                    required
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                  />
                  <p className="mt-1.5 text-xs text-slate-400">
                    3-32 characters. This is what other people use to add you to a project.
                  </p>
                </div>

                <div>
                  <label className="label" htmlFor="full-name">Name</label>
                  <input
                    id="full-name"
                    type="text"
                    className="input mt-1.5"
                    autoComplete="name"
                    maxLength={200}
                    placeholder="Your name"
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                  />
                </div>

                <div>
                  <label className="label" htmlFor="signup-email">Email address</label>
                  <input
                    id="signup-email"
                    type="email"
                    className="input mt-1.5"
                    autoComplete="email"
                    placeholder="you@example.org"
                    required
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                  />
                </div>
              </>
            ) : (
              <div>
                <label className="label" htmlFor="identifier">Username or email</label>
                <input
                  id="identifier"
                  type="text"
                  className="input mt-1.5"
                  autoComplete="username"
                  placeholder="mosese or you@example.org"
                  required
                  value={identifier}
                  onChange={(event) => setIdentifier(event.target.value)}
                />
              </div>
            )}

            <div>
              <label className="label" htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                className="input mt-1.5"
                autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                minLength={mode === 'signup' ? 8 : undefined}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>

            {mode === 'signup' && (
              <div>
                <label className="label" htmlFor="confirm-password">Confirm password</label>
                <input
                  id="confirm-password"
                  type="password"
                  className="input mt-1.5"
                  autoComplete="new-password"
                  minLength={8}
                  required
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                />
              </div>
            )}

            <button className="btn-primary h-11 w-full" disabled={busy}>
              {busy && <Spinner className="h-4 w-4 text-white" />}
              {mode === 'signup' ? 'Create account' : 'Sign in'}
            </button>
          </form>

          <p className="mt-6 text-center text-xs leading-5 text-slate-400">
            {mode === 'signup'
              ? 'Already have an account? Use Sign in above.'
              : 'New to SurveyHQ? Create an account and start your own projects.'}
          </p>
        </div>
      </section>
    </div>
  )
}
