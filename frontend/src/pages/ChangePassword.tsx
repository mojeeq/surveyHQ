import { useState } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { Field, Spinner } from '@/components/ui'

/**
 * Shown in place of the app when the signed-in account is still using a
 * password somebody else chose - the one from .env at first run, or one an
 * administrator set. There is no way past it but to set a new one, which is the
 * point: a shared bootstrap password that nobody is made to change is a
 * password that stays shared.
 */
export default function ChangePassword() {
  const { user, signOut, refresh } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (next.length < 8) {
      setError('Choose a password of at least 8 characters.')
      return
    }
    if (next !== confirm) {
      setError('The two new passwords do not match.')
      return
    }
    if (next === current) {
      setError('Choose a password different from the current one.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await api.post('/auth/change-password', {
        current_password: current,
        new_password: next,
      })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change the password')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-50 p-4">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-md bg-brand-600 text-sm font-bold text-white">
            S
          </span>
          <span className="text-lg font-semibold text-ink-900">SurveyHQ</span>
        </div>

        <form onSubmit={submit} className="card p-6">
          <h1 className="text-lg font-semibold text-ink-900">Set your password</h1>
          <p className="mb-4 mt-1 text-sm text-ink-500">
            {user?.email} is still using the password it was created with. Choose one
            only you know before going on.
          </p>

          {error && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {error}
            </div>
          )}

          <Field label="Current password">
            <input
              type="password"
              className="input"
              autoComplete="current-password"
              required
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          </Field>
          <Field label="New password" hint="At least 8 characters">
            <input
              type="password"
              className="input"
              autoComplete="new-password"
              required
              value={next}
              onChange={(event) => setNext(event.target.value)}
            />
          </Field>
          <Field label="Confirm new password">
            <input
              type="password"
              className="input"
              autoComplete="new-password"
              required
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
            />
          </Field>

          <button className="btn-primary w-full" disabled={busy}>
            {busy && <Spinner className="h-4 w-4 text-white" />}
            Set password and continue
          </button>
        </form>

        <button
          className="mt-4 w-full text-center text-xs text-ink-400 hover:text-ink-600"
          onClick={signOut}
        >
          Sign out instead
        </button>
      </div>
    </div>
  )
}
