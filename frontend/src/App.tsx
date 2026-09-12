import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, tokenStore } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { Loading } from '@/components/ui'
import Layout from '@/components/Layout'
import Login from '@/pages/Login'
import ChangePassword from '@/pages/ChangePassword'
import NotFound from '@/pages/NotFound'

// Keep only the authentication shell in the startup bundle.  DashboardView and
// Explore are large analytical workspaces; downloading/parsing them before a
// user even signs in makes every first load pay for code they may never open.
const Overview = lazy(() => import('@/pages/Overview'))
const Projects = lazy(() => import('@/pages/Projects'))
const ProjectDetail = lazy(() => import('@/pages/ProjectDetail'))
const Datasets = lazy(() => import('@/pages/Datasets'))
const DatasetDetail = lazy(() => import('@/pages/DatasetDetail'))
const Connections = lazy(() => import('@/pages/Connections'))
const Explore = lazy(() => import('@/pages/Explore'))
const Dashboards = lazy(() => import('@/pages/Dashboards'))
const DashboardView = lazy(() => import('@/pages/DashboardView'))
const Monitoring = lazy(() => import('@/pages/Monitoring'))
const Quality = lazy(() => import('@/pages/Quality'))
const Alerts = lazy(() => import('@/pages/Alerts'))
const Admin = lazy(() => import('@/pages/Admin'))
const SharedDashboard = lazy(() => import('@/pages/SharedDashboard'))

function RouteLoading() {
  return <Loading label="Loading workspace" />
}

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
  if (host.token) {
    return (
      <Suspense fallback={<RouteLoading />}>
        <SharedDashboard token={host.token} />
      </Suspense>
    )
  }

  return (
    <Suspense fallback={<RouteLoading />}>
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
    </Suspense>
  )
}
