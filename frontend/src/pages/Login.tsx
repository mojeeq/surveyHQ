import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Spinner } from '@/components/ui'

export default function Login() {
  const { user, signIn, loading } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (loading) return null
  if (user) return <Navigate to="/" replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await signIn(email.trim().toLowerCase(), password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed')
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
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-brand-400">From fieldwork to publication</p>
          <h1 className="mt-4 text-4xl font-bold leading-tight tracking-[-0.03em] text-white xl:text-5xl">
            Monitor surveys, analyse data and publish results from one workspace.
          </h1>
          <p className="mt-5 max-w-lg text-base leading-7 text-slate-400">
            Built for survey and census teams that need operational visibility, data quality checks,
            reproducible analysis and shareable dashboards without stitching together separate tools.
          </p>
          <div className="mt-8 grid grid-cols-3 gap-3">
            {[
              ['Monitor', 'Field progress and alerts'],
              ['Analyse', 'Tabulations and charts'],
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
        <div className="w-full max-w-[420px]">
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500">
                <img src="/logo.svg" alt="" className="h-6 w-6" />
              </div>
              <span className="text-xl font-bold tracking-tight text-slate-950 dark:text-white">SurveyHQ</span>
            </div>
          </div>

          <div>
            <p className="text-sm font-semibold text-brand-600 dark:text-brand-400">Welcome back</p>
            <h2 className="mt-2 text-3xl font-bold tracking-[-0.025em] text-slate-950 dark:text-white">Sign in to your workspace</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">Use your SurveyHQ account to continue.</p>
          </div>

          <form onSubmit={submit} className="mt-8 space-y-5">
            {error && (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
                {error}
              </div>
            )}

            <div>
              <label className="label" htmlFor="email">Email address</label>
              <input
                id="email"
                type="email"
                className="input mt-1.5"
                autoComplete="username"
                placeholder="you@example.org"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>

            <div>
              <label className="label" htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                className="input mt-1.5"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>

            <button className="btn-primary h-11 w-full" disabled={busy}>
              {busy && <Spinner className="h-4 w-4 text-white" />}
              Sign in
            </button>
          </form>

          <p className="mt-6 text-center text-xs leading-5 text-slate-400">
            First run? Sign in with the administrator account configured for this installation.
          </p>
        </div>
      </section>
    </div>
  )
}
