import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import type { Notification } from '@/lib/types'
import { relativeTime } from '@/lib/format'
import AppIcon, { type AppIconName } from '@/components/AppIcon'

/** Closes a popover when a click lands outside every ref it's given. */
function useClickOutside(refs: React.RefObject<HTMLElement>[], onOutside: () => void) {
  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (refs.some((ref) => ref.current?.contains(event.target as Node))) return
      onOutside()
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [refs, onOutside])
}

const NAV: { to: string; label: string; icon: AppIconName; end?: boolean }[] = [
  { to: '/', label: 'Overview', icon: 'overview', end: true },
  { to: '/projects', label: 'Projects', icon: 'projects' },
  { to: '/datasets', label: 'Datasets', icon: 'datasets' },
  { to: '/connections', label: 'Connections', icon: 'connections' },
  { to: '/explore', label: 'Explore', icon: 'explore' },
  { to: '/dashboards', label: 'Dashboards', icon: 'dashboards' },
  { to: '/monitoring', label: 'Monitoring', icon: 'monitoring' },
  { to: '/quality', label: 'Data quality', icon: 'quality' },
  { to: '/alerts', label: 'Alerts', icon: 'alerts' },
]

/* One row of the sidebar. The selected one is lit from above like everything
   else here, and carries a bright rule down its left edge - which is how Aero
   marked a selection, and reads at a glance better than a change of shade. */
const navRow = (isActive: boolean) =>
  `group/nav relative flex items-center gap-2.5 rounded-control px-3 py-1.5 text-[13px] transition-colors duration-150 ${
    isActive
      ? 'nav-selected text-white'
      : 'text-sidebar-text hover:bg-white/[0.06] hover:text-white'
  }`

export default function Layout() {
  const { user, signOut, can } = useAuth()
  const { resolvedTheme, toggleTheme } = useTheme()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const notificationsRef = useRef<HTMLDivElement>(null)
  const mobileNavRef = useRef<HTMLElement>(null)
  const mobileToggleRef = useRef<HTMLButtonElement>(null)

  const { data: notifications = [] } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.get<Notification[]>('/system/notifications?unread_only=true&limit=20'),
    refetchInterval: 60_000,
  })

  useClickOutside([notificationsRef], () => setNotificationsOpen(false))
  useClickOutside([mobileNavRef, mobileToggleRef], () => setMenuOpen(false))

  return (
    <div className="app-ground flex min-h-screen bg-ink-100 dark:bg-dark-100">
      {/* The one dark surface in the interface, as it is in Redash: the
          navigation is furniture, and keeping it out of the paper-white
          working area is what makes a dashboard read as the content. */}
      <aside className="aero-sidebar hidden w-56 shrink-0 flex-col lg:flex">
        <div className="flex h-14 items-center gap-2.5 border-b border-white/[0.07] px-5">
          <img src="/logo.svg" alt="" className="h-8 w-8 drop-shadow-[0_1px_3px_rgba(77,184,255,0.55)]" />
          <span className="text-[16px] font-semibold text-white [text-shadow:0_1px_2px_rgba(0,0,0,0.5)]">
            suso<span className="font-normal text-sidebar-text">Dash</span>
          </span>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => navRow(isActive)}
            >
              <AppIcon name={item.icon} size={22} className="shrink-0" />
              {item.label}
            </NavLink>
          ))}
          {can('admin') && (
            <NavLink
              to="/admin"
              className={({ isActive }) => navRow(isActive)}
            >
              <AppIcon name="admin" size={22} className="shrink-0" />
              Administration
            </NavLink>
          )}
        </nav>
        <div className="p-3 text-xs text-sidebar-text/60">susoDash v1.0</div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="aero-glass sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-ink-200 px-4 transition-colors dark:border-dark-200 lg:px-6">
          <div className="flex items-center gap-2 lg:hidden">
            <button
              ref={mobileToggleRef}
              className="btn-ghost btn-sm"
              onClick={() => setMenuOpen((open) => !open)}
              aria-label="Toggle navigation menu"
              aria-expanded={menuOpen}
            >
              ☰
            </button>
            <img src="/logo.svg" alt="" className="h-7 w-7 drop-shadow-[0_1px_2px_rgba(77,184,255,0.4)]" />
            <span className="font-semibold">
              suso<span className="font-normal text-ink-500 dark:text-dark-500">Dash</span>
            </span>
          </div>
          <div className="hidden lg:block" />

          <div className="flex items-center gap-2">
            <button
              className="btn-ghost btn-sm"
              onClick={toggleTheme}
              aria-label={resolvedTheme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              title={resolvedTheme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              <span className="text-base leading-none transition-transform duration-200" aria-hidden>
                {resolvedTheme === 'dark' ? '☀' : '☾'}
              </span>
            </button>

            <div className="relative" ref={notificationsRef}>
              <button
                className="btn-ghost btn-sm relative"
                onClick={() => setNotificationsOpen((open) => !open)}
                aria-label="Notifications"
                aria-expanded={notificationsOpen}
              >
                🔔
                {notifications.length > 0 && (
                  <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white">
                    {notifications.length}
                  </span>
                )}
              </button>
              {notificationsOpen && (
                <div className="absolute right-0 top-10 z-40 w-80 origin-top-right animate-[fade-in_150ms_ease-out] rounded-card border border-ink-200 bg-white shadow-pop dark:border-dark-200 dark:bg-dark-50">
                  <div className="flex items-center justify-between border-b border-ink-200 px-4 py-2.5 dark:border-dark-200">
                    <span className="text-sm font-semibold dark:text-dark-900">Notifications</span>
                    <button
                      className="text-xs text-brand-500 hover:underline dark:text-brand-400"
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
                      <p className="px-4 py-6 text-center text-sm text-ink-500 dark:text-dark-500">
                        Nothing new right now.
                      </p>
                    ) : (
                      notifications.map((notification) => (
                        <button
                          key={notification.id}
                          className="block w-full border-b border-ink-100 px-4 py-3 text-left transition-colors hover:bg-ink-50 dark:border-dark-200 dark:hover:bg-dark-200/60"
                          onClick={() => {
                            setNotificationsOpen(false)
                            if (notification.link) navigate(notification.link)
                          }}
                        >
                          <p className="text-sm font-medium text-ink-800 dark:text-dark-800">{notification.title}</p>
                          <p className="mt-0.5 line-clamp-2 text-xs text-ink-500 dark:text-dark-500">
                            {notification.body}
                          </p>
                          <p className="mt-1 text-[11px] text-ink-400 dark:text-dark-400">
                            {relativeTime(notification.created_at)}
                          </p>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 border-l border-ink-200 pl-3 dark:border-dark-200">
              <div className="hidden text-right sm:block">
                <p className="text-sm font-medium leading-tight text-ink-800 dark:text-dark-800">
                  {user?.full_name || user?.email}
                </p>
                <p className="text-[11px] capitalize leading-tight text-ink-500 dark:text-dark-500">{user?.role}</p>
              </div>
              <button className="btn-secondary btn-sm" onClick={signOut}>
                Sign out
              </button>
            </div>
          </div>
        </header>

        <nav
          ref={mobileNavRef}
          className={`overflow-hidden border-b border-ink-200 bg-white transition-[max-height,opacity] duration-200 ease-out dark:border-dark-200 dark:bg-dark-50 lg:hidden ${
            menuOpen ? 'max-h-96 opacity-100' : 'pointer-events-none max-h-0 opacity-0'
          }`}
        >
          <div className="p-3">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-card px-3 py-2 text-sm transition-colors ${
                    isActive
                      ? 'bg-brand-50 text-brand-700 dark:bg-brand-500/10 dark:text-brand-400'
                      : 'text-ink-700 dark:text-dark-700'
                  }`
                }
              >
                <AppIcon name={item.icon} size={20} glow={false} className="shrink-0" />
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>

        <main className="mx-auto w-full max-w-[1500px] flex-1 animate-[fade-in_200ms_ease-out] p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
