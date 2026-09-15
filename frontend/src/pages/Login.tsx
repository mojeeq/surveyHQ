import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { Spinner } from '@/components/ui'

/**
 * Whether this deployment lets people create their own accounts.
 *
 * The same query key the application shell uses to resolve the hostname, so on
 * a signed-out load the answer is already in the cache and this costs nothing.
 * Absent - an older server, or a reply that never arrived - counts as off: a
 * form that cannot work is worse than one that is not offered.
 */
function useSignupOffered(): boolean {
  const query = useQuery({
    queryKey: ['host-site'],
    queryFn: () =>
      api.get<{ dashboard: { token: string; name: string } | null; signup_enabled?: boolean }>(
        '/public/site',
      ),
    staleTime: Infinity,
    retry: false,
  })
  return query.data?.signup_enabled === true
}

/**
 * The sign-in page: a name, a form, a button.
 *
 * Nothing here explains the platform. Whoever reaches this page was sent a
 * link by their survey manager and wants to be past it, and a column of
 * marketing copy beside the password box is one more thing between them and
 * the work. Everything the page does is still here - signing in by username
 * or by email, creating an account where the server allows it - only the
 * decoration around it is gone.
 */
export default function Login() {
  const { user, signIn, signUp, loading } = useAuth()
  const signupOffered = useSignupOffered()
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

  // Belt and braces: the link below is not rendered when sign-up is off, so
  // this only matters if the answer arrives after somebody has already used
  // it. Signing in is the mode that always works.
  const showing = signupOffered ? mode : 'signin'

  const changeMode = (next: 'signin' | 'signup') => {
    setMode(next)
    setError('')
    setPassword('')
    setConfirmPassword('')
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    if (showing === 'signup' && password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    setBusy(true)
    try {
      if (showing === 'signup') {
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
      setError(
        err instanceof Error
          ? err.message
          : showing === 'signup'
            ? 'Sign up failed'
            : 'Sign in failed',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    // No background colour of its own: `body` already carries one for each
    // theme, and setting a light one here is what left the page white behind
    // a dark card.
    <div className="app-ground flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <img src="/logo.svg" alt="" className="h-8 w-8" />
          <span className="text-lg font-semibold text-ink-900 dark:text-dark-900">SurveyHQ</span>
        </div>

        <form onSubmit={submit} className="card p-6">
          <h1 className="text-base font-semibold text-ink-900 dark:text-dark-900">
            {showing === 'signup' ? 'Create an account' : 'Sign in'}
          </h1>

          {error && (
            <div className="mt-4 rounded-control border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
              {error}
            </div>
          )}

          <div className="mt-4 space-y-3">
            {showing === 'signup' ? (
              <>
                <div>
                  <label className="label" htmlFor="username">Username</label>
                  <input
                    id="username"
                    type="text"
                    className="input"
                    autoComplete="username"
                    minLength={3}
                    maxLength={32}
                    pattern="[A-Za-z0-9][A-Za-z0-9._-]{2,31}"
                    required
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                  />
                </div>

                <div>
                  <label className="label" htmlFor="full-name">Name</label>
                  <input
                    id="full-name"
                    type="text"
                    className="input"
                    autoComplete="name"
                    maxLength={200}
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                  />
                </div>

                <div>
                  <label className="label" htmlFor="signup-email">Email</label>
                  <input
                    id="signup-email"
                    type="email"
                    className="input"
                    autoComplete="email"
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
                  className="input"
                  autoComplete="username"
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
                className="input"
                autoComplete={showing === 'signup' ? 'new-password' : 'current-password'}
                minLength={showing === 'signup' ? 8 : undefined}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>

            {showing === 'signup' && (
              <div>
                <label className="label" htmlFor="confirm-password">Confirm password</label>
                <input
                  id="confirm-password"
                  type="password"
                  className="input"
                  autoComplete="new-password"
                  minLength={8}
                  required
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                />
              </div>
            )}
          </div>

          <button className="btn-primary mt-5 h-9 w-full" disabled={busy}>
            {busy && <Spinner className="h-4 w-4 text-white" />}
            {showing === 'signup' ? 'Create account' : 'Sign in'}
          </button>

          {/* Nothing to switch to on a server with sign-up off, and a link that
              answers 404 is worse than no link. */}
          {signupOffered && (
            <p className="mt-4 text-center text-xs text-ink-500 dark:text-dark-600">
              {showing === 'signup' ? 'Already have an account?' : 'No account yet?'}{' '}
              <button
                type="button"
                className="font-medium text-brand-600 hover:underline dark:text-brand-400"
                onClick={() => changeMode(showing === 'signup' ? 'signin' : 'signup')}
              >
                {showing === 'signup' ? 'Sign in' : 'Create one'}
              </button>
            </p>
          )}
        </form>
      </div>
    </div>
  )
}
