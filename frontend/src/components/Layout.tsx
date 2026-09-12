import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import type { Notification } from '@/lib/types'
import { relativeTime } from '@/lib/format'
import AppIcon, { type AppIconName } from '@/components/AppIcon'

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

type NavItem = { to: string; label: string; icon: AppIconName; end?: boolean }
type NavGroup = { label: string; items: NavItem[] }

const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Workspace',
    items: [
      { to: '/', label: 'Overview', icon: 'overview', end: true },
      { to: '/projects', label: 'Projects', icon: 'projects' },
    ],
  },
  {
    label: 'Data',
    items: [
      { to: '/datasets', label: 'Datasets', icon: 'datasets' },
      { to: '/connections', label: 'Connections', icon: 'connections' },
    ],
  },
  {
    label: 'Analyse',
    items: [
      { to: '/explore', label: 'Analyse', icon: 'explore' },
      { to: '/dashboards', label: 'Dashboards', icon: 'dashboards' },
    ],
  },
  {
    label: 'Monitor',
    items: [
      { to: '/monitoring', label: 'Fieldwork', icon: 'monitoring' },
      { to: '/quality', label: 'Data quality', icon: 'quality' },
      { to: '/alerts', label: 'Alerts', icon: 'alerts' },
    ],
  },
]

const navRow = (isActive: boolean) =>
  `group/nav relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150 ${
    isActive
      ? 'bg-white text-slate-950 shadow-sm dark:bg-slate-800 dark:text-white'
      : 'text-slate-400 hover:bg-white/5 hover:text-white'
  }`

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
    </svg>
  )
}

function BellIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10 21h4" strokeLinecap="round" />
    </svg>
  )
}

function ThemeIcon({ dark }: { dark: boolean }) {
  return dark ? (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" strokeLinecap="round" />
    </svg>
  ) : (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M20.3 15.2A8.5 8.5 0 0 1 8.8 3.7 8.5 8.5 0 1 0 20.3 15.2Z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand-500 shadow-lg shadow-brand-500/20">
        <img src="/logo.svg" alt="" className="h-6 w-6" />
      </div>
      <div className="min-w-0">
        <div className="text-[15px] font-bold tracking-tight text-white">SurveyHQ</div>
        <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-slate-500">Survey operations</div>
      </div>
    </div>
  )
}

function SidebarNav({ admin = false, onNavigate }: { admin?: boolean; onNavigate?: () => void }) {
  return (
    <nav className="flex-1 overflow-y-auto px-3 py-4">
      <div className="space-y-5">
        {NAV_GROUPS.map((group) => (
          <section key={group.label}>
            <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">
              {group.label}
            </p>
            <div className="space-y-1">
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={onNavigate}
                  className={({ isActive }) => navRow(isActive)}
                >
                  <AppIcon name={item.icon} size={19} glow={false} className="shrink-0" />
                  <span className="truncate">{item.label}</span>
                </NavLink>
              ))}
            </div>
          </section>
        ))}
        {admin && (
          <section>
            <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">System</p>
            <NavLink to="/admin" onClick={onNavigate} className={({ isActive }) => navRow(isActive)}>
              <AppIcon name="admin" size={19} glow={false} className="shrink-0" />
              Administration
            </NavLink>
          </section>
        )}
      </div>
    </nav>
  )
}

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
    <div className="flex min-h-screen bg-slate-50 text-slate-700 dark:bg-slate-950 dark:text-slate-300">
      <aside className="hidden w-[248px] shrink-0 flex-col border-r border-white/[0.06] bg-slate-950 lg:flex">
        <div className="flex h-[72px] items-center border-b border-white/[0.06] px-5">
          <Brand />
        </div>
        <SidebarNav admin={can('admin')} />
        <div className="border-t border-white/[0.06] px-5 py-4">
          <div className="text-xs font-medium text-slate-400">SurveyHQ</div>
          <div className="mt-0.5 text-[11px] text-slate-600">Monitoring · analysis · publishing</div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-[72px] items-center justify-between gap-3 border-b border-slate-200/80 bg-white/90 px-4 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/90 lg:px-7">
          <div className="flex min-w-0 items-center gap-3 lg:hidden">
            <button
              ref={mobileToggleRef}
              className="icon-button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-label="Toggle navigation menu"
              aria-expanded={menuOpen}
            >
              <MenuIcon />
            </button>
            <div className="flex items-center gap-2.5">
              <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand-500">
                <img src="/logo.svg" alt="" className="h-5 w-5" />
              </div>
              <span className="font-bold tracking-tight text-slate-950 dark:text-white">SurveyHQ</span>
            </div>
          </div>

          <div className="hidden min-w-0 lg:block">
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-slate-400">Survey workspace</p>
            <p className="mt-0.5 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
              Monitor collection, analyse data and publish results
            </p>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              className="icon-button"
              onClick={toggleTheme}
              aria-label={resolvedTheme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              title={resolvedTheme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              <ThemeIcon dark={resolvedTheme === 'dark'} />
            </button>

            <div className="relative" ref={notificationsRef}>
              <button
                className="icon-button relative"
                onClick={() => setNotificationsOpen((open) => !open)}
                aria-label="Notifications"
                aria-expanded={notificationsOpen}
              >
                <BellIcon />
                {notifications.length > 0 && (
                  <span className="absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[9px] font-bold text-white ring-2 ring-white dark:ring-slate-950">
                    {notifications.length > 9 ? '9+' : notifications.length}
                  </span>
                )}
              </button>
              {notificationsOpen && (
                <div className="absolute right-0 top-12 z-40 w-[360px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl shadow-slate-950/10 dark:border-slate-800 dark:bg-slate-900">
                  <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3.5 dark:border-slate-800">
                    <div>
                      <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">Notifications</span>
                      <p className="mt-0.5 text-xs text-slate-500">Recent system and monitoring activity</p>
                    </div>
                    <button
                      className="text-xs font-semibold text-brand-600 hover:text-brand-700 dark:text-brand-400"
                      onClick={async () => {
                        await api.post('/system/notifications/read-all')
                        setNotificationsOpen(false)
                      }}
                    >
                      Mark all read
                    </button>
                  </div>
                  <div className="max-h-96 overflow-y-auto">
                    {notifications.length === 0 ? (
                      <p className="px-4 py-10 text-center text-sm text-slate-500">Nothing new right now.</p>
                    ) : (
                      notifications.map((notification) => (
                        <button
                          key={notification.id}
                          className="block w-full border-b border-slate-100 px-4 py-3.5 text-left transition-colors last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/70"
                          onClick={() => {
                            setNotificationsOpen(false)
                            if (notification.link) navigate(notification.link)
                          }}
                        >
                          <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{notification.title}</p>
                          <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{notification.body}</p>
                          <p className="mt-2 text-[11px] font-medium text-slate-400">{relativeTime(notification.created_at)}</p>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="ml-1 flex items-center gap-3 border-l border-slate-200 pl-3 dark:border-slate-800">
              <div className="hidden text-right sm:block">
                <p className="max-w-[180px] truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {user?.full_name || user?.email}
                </p>
                <p className="mt-0.5 text-[11px] font-medium capitalize text-slate-500">{user?.role}</p>
              </div>
              <button className="btn-secondary btn-sm" onClick={signOut}>Sign out</button>
            </div>
          </div>
        </header>

        <nav
          ref={mobileNavRef}
          className={`overflow-hidden border-b border-slate-800 bg-slate-950 transition-[max-height,opacity] duration-200 ease-out lg:hidden ${
            menuOpen ? 'max-h-[75vh] opacity-100' : 'pointer-events-none max-h-0 opacity-0'
          }`}
        >
          <SidebarNav admin={can('admin')} onNavigate={() => setMenuOpen(false)} />
        </nav>

        <main className="mx-auto w-full max-w-[1560px] flex-1 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
