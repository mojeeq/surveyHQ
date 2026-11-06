import { useParams } from 'react-router-dom'
import DashboardView from './DashboardView'

/** Read-only view served from a public share token, with no sign-in.
 *
 *  The token comes from the URL on a /shared/ link, or is handed in when the
 *  hostname itself is the dashboard's.
 *
 *  Nothing of ours appears on it at all. A shared link is the survey team's
 *  page, shown to people who have never heard of this platform, and the whole
 *  of it should be their logo and their title. A credit in the footer is still
 *  our name on their page, so there is no footer.
 */
export default function SharedDashboard({ token: given }: { token?: string } = {}) {
  const { token: fromPath = '' } = useParams()
  const token = given ?? fromPath
  return (
    <div className="app-ground flex min-h-screen flex-col bg-ink-50">
      <main className="mx-auto w-full max-w-[1500px] flex-1 p-6">
        <DashboardView publicToken={token} />
      </main>
    </div>
  )
}
