import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import type { Notification } from '@/lib/types'
import { relativeTime } from '@/lib/format'

const NAV = [
  { to: '/', label: 'Overview', icon: '◈', end: true },
  { to: '/projects', label: 'Projects', icon: '◫' },
  { to: '/datasets', label: 'Datasets', icon: '▤' },
  { to: '/connections', label: 'Connections', icon: '⇄' },
  { to: '/explore', label: 'Explore', icon: '◱' },
  { to: '/dashboards', label: 'Dashboards', icon: '▦' },
  { to: '/monitoring', label: 'Monitoring', icon: '◎' },
  { to: '/quality', label: 'Data quality', icon: '✓' },
  { to: '/alerts', label: 'Alerts', icon: '!' },
]

export default function Layout() {
  const { user, signOut, can } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)

  const { data: notifications = [] } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.get<Notification[]>('/system/notifications?unread_only=true&limit=20'),
    refetchInterval: 60_000,
  })

  return (
    <div className="flex min-h-screen bg-ink-100">
      {/* The one dark surface in the interface, as it is in Redash: the
          navigation is furniture, and keeping it out of the paper-white
          working area is what makes a dashboard read as the content. */}
      <aside className="hidden w-56 shrink-0 flex-col bg-sidebar lg:flex">
        <div className="flex h-14 items-center gap-2 px-5">
          <span className="grid h-7 w-7 place-items-center rounded-control bg-brand-500 text-sm font-bold text-white">
            S
          </span>
          <span className="text-[15px] font-semibold text-white">SurveyHQ</span>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-control px-3 py-2 text-[13px] transition-colors ${
                  isActive
                    ? 'bg-sidebar-active text-white'
                    : 'text-sidebar-text hover:bg-sidebar-active hover:text-white'
                }`
              }
            >
              <span className="w-4 text-center text-xs" aria-hidden>
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
          {can('admin') && (
            <NavLink
              to="/admin"
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-control px-3 py-2 text-[13px] transition-colors ${
                  isActive
                    ? 'bg-sidebar-active text-white'
                    : 'text-sidebar-text hover:bg-sidebar-active hover:text-white'
                }`
              }
            >
              <span className="w-4 text-center text-xs" aria-hidden>
                ⚙
              </span>
              Administration
            </NavLink>
          )}
        </nav>
        <div className="p-3 text-xs text-sidebar-text/60">SurveyHQ v1.0</div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-ink-200 bg-white/95 px-4 backdrop-blur lg:px-6">
          <div className="flex items-center gap-2 lg:hidden">
            <button className="btn-ghost btn-sm" onClick={() => setMenuOpen(!menuOpen)}>
              ☰
            </button>
            <span className="font-semibold">SurveyHQ</span>
          </div>
          <div className="hidden lg:block" />

          <div className="flex items-center gap-2">
            <div className="relative">
              <button
                className="btn-ghost btn-sm relative"
                onClick={() => setNotificationsOpen(!notificationsOpen)}
                aria-label="Notifications"
              >
                🔔
                {notifications.length > 0 && (
                  <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white">
                    {notifications.length}
                  </span>
                )}
              </button>
              {notificationsOpen && (
                <div className="absolute right-0 top-10 z-40 w-80 rounded-card border border-ink-200 bg-white shadow-pop">
                  <div className="flex items-center justify-between border-b border-ink-200 px-4 py-2.5">
                    <span className="text-sm font-semibold">Notifications</span>
                    <button
                      className="text-xs text-brand-500 hover:underline"
                      onClick={async () => {
                        await api.post('/system/notifications/read-all')
                        setNotificationsOpen(false)
                      }}
                    >
                      Mark all read
                    </button>
                  </div>
                  <div className="max-h-80 overflow-y-auto">
                    {notifications.length === 0 ? (
                      <p className="px-4 py-6 text-center text-sm text-ink-500">
                        Nothing new right now.
                      </p>
                    ) : (
                      notifications.map((notification) => (
                        <button
                          key={notification.id}
                          className="block w-full border-b border-ink-100 px-4 py-3 text-left hover:bg-ink-50"
                          onClick={() => {
                            setNotificationsOpen(false)
                            if (notification.link) navigate(notification.link)
                          }}
                        >
                          <p className="text-sm font-medium text-ink-800">{notification.title}</p>
                          <p className="mt-0.5 line-clamp-2 text-xs text-ink-500">
                            {notification.body}
                          </p>
                          <p className="mt-1 text-[11px] text-ink-400">
                            {relativeTime(notification.created_at)}
                          </p>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 border-l border-ink-200 pl-3">
              <div className="hidden text-right sm:block">
                <p className="text-sm font-medium leading-tight text-ink-800">
                  {user?.full_name || user?.email}
                </p>
                <p className="text-[11px] capitalize leading-tight text-ink-500">{user?.role}</p>
              </div>
              <button className="btn-secondary btn-sm" onClick={signOut}>
                Sign out
              </button>
            </div>
          </div>
        </header>

        {menuOpen && (
          <nav className="border-b border-ink-200 bg-white p-3 lg:hidden">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) =>
                  `block rounded-card px-3 py-2 text-sm ${
                    isActive ? 'bg-brand-50 text-brand-700' : 'text-ink-700'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        )}

        <main className="mx-auto w-full max-w-[1500px] flex-1 p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
