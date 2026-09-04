import { Navigate, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, tokenStore } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { Loading } from '@/components/ui'
import Layout from '@/components/Layout'
import Login from '@/pages/Login'
import Overview from '@/pages/Overview'
import Projects from '@/pages/Projects'
import ProjectDetail from '@/pages/ProjectDetail'
import Datasets from '@/pages/Datasets'
import DatasetDetail from '@/pages/DatasetDetail'
import Connections from '@/pages/Connections'
import Explore from '@/pages/Explore'
import Dashboards from '@/pages/Dashboards'
import DashboardView from '@/pages/DashboardView'
import Monitoring from '@/pages/Monitoring'
import Quality from '@/pages/Quality'
import Alerts from '@/pages/Alerts'
import Admin from '@/pages/Admin'
import SharedDashboard from '@/pages/SharedDashboard'
import ChangePassword from '@/pages/ChangePassword'
import NotFound from '@/pages/NotFound'

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth()
  if (loading) return <Loading label="Signing you in" />
  if (!user) return <Navigate to="/login" replace />
  // Placed here rather than on a route so it cannot be walked around by typing
  // a URL: every authenticated page in the app is behind this component.
  if (user.must_change_password) return <ChangePassword />
  return children
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  const { can } = useAuth()
  if (!can('admin')) return <Navigate to="/" replace />
  return children
}

/** Whether this hostname is a published dashboard rather than the platform.
 *
 *  One bundle is served for every hostname, so the URL alone cannot say which
 *  of the two this is. The check is skipped for anyone already signed in -
 *  they are using the app, and making them wait for it would delay every load.
 *  For a visitor with no session it runs first, because otherwise a published
 *  results page would flash a sign-in form before finding itself.
 */
function useHostDashboard() {
  const signedIn = Boolean(tokenStore.get())
  const query = useQuery({
    queryKey: ['host-site'],
    queryFn: () => api.get<{ dashboard: { token: string; name: string } | null }>(
      '/public/site',
    ),
    enabled: !signedIn,
    staleTime: Infinity,
    retry: false,
  })
  if (signedIn) return { loading: false, token: null }
  return { loading: query.isPending, token: query.data?.dashboard?.token ?? null }
}

export default function App() {
  const host = useHostDashboard()

  if (host.loading) return <Loading label="Loading" />
  // A named dashboard answers on its own hostname at any path, so a link deep
  // into it - or a refresh - lands on the dashboard rather than on a 404.
  if (host.token) return <SharedDashboard token={host.token} />

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Public share links bypass authentication by design */}
      <Route path="/shared/:token" element={<SharedDashboard />} />

      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Overview />} />
        <Route path="projects" element={<Projects />} />
        <Route path="projects/:id" element={<ProjectDetail />} />
        <Route path="datasets" element={<Datasets />} />
        <Route path="datasets/:id" element={<DatasetDetail />} />
        <Route path="connections" element={<Connections />} />
        <Route path="explore" element={<Explore />} />
        <Route path="dashboards" element={<Dashboards />} />
        <Route path="dashboards/:id" element={<DashboardView />} />
        <Route path="monitoring" element={<Monitoring />} />
        <Route path="quality" element={<Quality />} />
        <Route path="alerts" element={<Alerts />} />
        <Route
          path="admin"
          element={
            <RequireAdmin>
              <Admin />
            </RequireAdmin>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
