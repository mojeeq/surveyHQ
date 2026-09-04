import { useParams } from 'react-router-dom'
import DashboardView from './DashboardView'

/** Read-only view served from a public share token, with no sign-in.
 *
 *  The token comes from the URL on a /shared/ link, or is handed in when the
 *  hostname itself is the dashboard's.
 */
export default function SharedDashboard({ token: given }: { token?: string } = {}) {
  const { token: fromPath = '' } = useParams()
  const token = given ?? fromPath
  return (
    <div className="min-h-screen bg-ink-50">
      <header className="border-b border-ink-200 bg-white px-6 py-3">
        <div className="mx-auto flex max-w-[1500px] items-center gap-2">
          <img src="/logo.svg" alt="" className="h-7 w-7" />
          <span className="text-sm font-semibold text-ink-900">
            suso<span className="font-normal text-ink-500">Dash</span>
          </span>
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
