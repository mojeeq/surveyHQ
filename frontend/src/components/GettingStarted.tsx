/**
 * What to do first, on the Overview of an install nobody has set up yet.
 *
 * A new install opened on noughts in every box and four empty cards, and
 * nothing said where to begin. This lists the six things that make the
 * platform useful, in the order they are worth doing, each ticking itself
 * once what it asks for exists. It goes away when they are all done, or for
 * good when somebody puts it away - remembered against the account, like the
 * pinned side pane, because it is about the person rather than the screen.
 */
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import {
  gettingStarted,
  nextStep,
  showGettingStarted,
  type StepState,
} from '@/lib/getting-started'
import { Card } from '@/components/ui'

export default function GettingStarted() {
  const { user, can, refresh } = useAuth()
  const [putAway, setPutAway] = useState(false)
  // Only those who can do the steps are given any; for anyone else the server
  // answers with none, and not asking saves the request.
  const states = useQuery({
    queryKey: ['getting-started'],
    queryFn: () => api.get<StepState[]>('/monitoring/getting-started'),
    enabled: can('manager'),
    // Asked again every time the Overview opens. The steps are done on other
    // pages, and somebody back from creating their first project within the
    // half minute the app otherwise trusts a result was still told to create
    // one. It is a few existence checks; asking costs next to nothing.
    refetchOnMount: 'always',
  })

  const steps = gettingStarted(states.data ?? [])
  if (!showGettingStarted(steps, putAway || user?.preferences?.getting_started_hidden)) {
    return null
  }
  const next = nextStep(steps)
  const done = steps.filter((step) => step.done).length

  const hide = async () => {
    setPutAway(true)
    try {
      await api.patch('/auth/me/preferences', { getting_started_hidden: true })
      await refresh()
    } catch {
      // Put away in this tab regardless; it comes back next time if the
      // account could not be told.
    }
  }

  return (
    <Card
      className="mb-6"
      title="Getting started"
      subtitle={`${done} of ${steps.length} done. Each step ticks itself once it has been done.`}
      actions={
        <button
          className="btn-ghost btn-sm"
          onClick={hide}
          title="Put this list away for good on your account"
        >
          Hide this list
        </button>
      }
    >
      <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {steps.map((step, index) => {
          const current = step === next
          return (
            <li
              key={step.key}
              className={`flex gap-3 rounded-card border px-3 py-3 ${
                current
                  ? 'border-brand-300 bg-brand-50 dark:border-brand-500/50 dark:bg-brand-500/10'
                  : 'border-ink-200 dark:border-dark-200'
              }`}
            >
              <span
                aria-hidden
                className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                  step.done
                    ? 'bg-emerald-600 text-white'
                    : 'border border-ink-300 text-ink-600 dark:border-dark-300 dark:text-dark-600'
                }`}
              >
                {step.done ? '✓' : index + 1}
              </span>
              <div className="min-w-0">
                <p
                  className={`text-sm font-medium ${
                    step.done
                      ? 'text-ink-600 dark:text-dark-600'
                      : 'text-ink-800 dark:text-dark-800'
                  }`}
                >
                  {step.done ? (
                    step.title
                  ) : (
                    <Link to={step.to} className="hover:underline">
                      {step.title}
                    </Link>
                  )}
                  {step.done && <span className="sr-only"> (done)</span>}
                </p>
                <p className="mt-0.5 text-xs text-ink-600 dark:text-dark-600">{step.detail}</p>
                {current && (
                  <Link to={step.to} className="btn-primary btn-sm mt-2">
                    Start here
                  </Link>
                )}
              </div>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}
