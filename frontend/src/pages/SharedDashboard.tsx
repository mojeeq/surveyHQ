import { useParams } from 'react-router-dom'
import DashboardView from './DashboardView'

/** Read-only view served from a public share token, with no sign-in. */
export default function SharedDashboard() {
  const { token = '' } = useParams()
  return (
    <div className="min-h-screen bg-ink-50">
      <header className="border-b border-ink-200 bg-white px-6 py-3">
        <div className="mx-auto flex max-w-[1500px] items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-control bg-brand-600 text-sm font-bold text-white">
            S
          </span>
          <span className="text-sm font-semibold text-ink-900">SurveyHQ</span>
          <span className="ml-2 rounded-full bg-ink-100 px-2 py-0.5 text-xs text-ink-600">
            Shared dashboard
          </span>
        </div>
      </header>
      <main className="mx-auto max-w-[1500px] p-6">
        <DashboardView publicToken={token} />
      </main>
    </div>
  )
}
