import { useParams } from 'react-router-dom'
import DashboardView from './DashboardView'

/** Read-only view served from a public share token, with no sign-in.
 *
 *  The token comes from the URL on a /shared/ link, or is handed in when the
 *  hostname itself is the dashboard's.
 *
 *  Nothing of ours sits above the dashboard. A shared link is the survey team's
 *  page, shown to people who have never heard of this platform, so the first
 *  thing on it should be their logo and their title - not a bar with our name
 *  in it. The credit goes underneath, where a footer goes.
 */
export default function SharedDashboard({ token: given }: { token?: string } = {}) {
  const { token: fromPath = '' } = useParams()
  const token = given ?? fromPath
  return (
    <div className="flex min-h-screen flex-col bg-ink-50">
      <main className="mx-auto w-full max-w-[1500px] flex-1 p-6">
        <DashboardView publicToken={token} />
      </main>
      <footer className="px-6 pb-8 pt-2">
        <a
          className="mx-auto flex w-fit items-center gap-2 text-xs text-ink-500 no-underline hover:text-ink-700"
          href="https://github.com/mojeeq/surveyHQ"
          target="_blank"
          rel="noreferrer"
        >
          <img src="/logo.svg" alt="" className="h-4 w-4 opacity-80" />
          <span>
            powered by <span className="font-semibold">suso</span>Dash
          </span>
        </a>
      </footer>
    </div>
  )
}
