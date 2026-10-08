import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { warm } from '@/lib/pages'
import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'
import { DEFAULT_SIDEBAR, inkFor, nameOf, SIDEBAR_PRESETS } from '@/lib/sidebar'
import type { Notification } from '@/lib/types'
import { relativeTime } from '@/lib/format'
import AppIcon, { type AppIconName } from '@/components/AppIcon'
import ProjectFilter from '@/components/ProjectFilter'

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
      { to: '/monitoring', label: 'Indicators', icon: 'monitoring' },
      { to: '/quality', label: 'Data quality', icon: 'quality' },
      { to: '/alerts', label: 'Alerts', icon: 'alerts' },
    ],
  },
]

/**
 * A navigation row.
 *
 * Every colour comes from a custom property the side pane sets, rather than
 * from a fixed slate: the pane can be painted now, and white-on-slate stops
 * being a safe assumption the moment somebody picks a pale one. `lib/sidebar`
 * derives the whole set from the chosen colour.
 *
 * `compact` is the unpinned rail, where there is no room for a label.
 */
const navRow = (isActive: boolean, compact = false) =>
  `group/nav relative flex items-center rounded-lg py-2 text-sm font-medium transition-all duration-150 ${
    compact ? 'justify-center px-0' : 'gap-3 px-3'
  } ${
    isActive
      ? 'bg-[var(--sb-active-bg)] text-[var(--sb-active-ink)] shadow-sm'
      : 'text-[var(--sb-dim)] hover:bg-[var(--sb-hover)] hover:text-[var(--sb-ink)]'
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

function PinIcon({ pinned }: { pinned: boolean }) {
  // Upright when pinned, tipped over when not, so the state reads without the
  // tooltip. Same drawing either way, rotated.
  return (
    <svg
      viewBox="0 0 24 24"
      className={`h-[18px] w-[18px] transition-transform duration-200 ${pinned ? '' : 'rotate-45'}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden
    >
      <path d="M9 4h6l-1 5 3 3v2H7v-2l3-3-1-5Z" strokeLinejoin="round" />
      <path d="M12 14v6" strokeLinecap="round" />
    </svg>
  )
}

function PaletteIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path
        d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.6 1.5-1.3 0-.4-.2-.7-.4-1-.3-.3-.4-.6-.4-1 0-.7.6-1.2 1.3-1.2H16a5 5 0 0 0 5-5c0-4.1-4-8.5-9-8.5Z"
        strokeLinejoin="round"
      />
      <circle cx="7.5" cy="11.5" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="11" cy="7.5" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="15.5" cy="8.5" r="1.1" fill="currentColor" stroke="none" />
    </svg>
  )
}

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand-500 shadow-lg shadow-brand-500/20">
        <img src="/logo.svg" alt="" className="h-6 w-6" />
      </div>
      {/* Ink from the pane, not white: the name was the one thing left
          unreadable when the pane was painted a pale colour. */}
      <div className="min-w-0">
        <div className="text-[15px] font-bold tracking-tight text-[var(--sb-ink)]">SurveyHQ</div>
        <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--sb-faint)]">
          Survey operations
        </div>
      </div>
    </div>
  )
}

/** The Aero tile in miniature, lit when it is on.
 *
 *  Its whole grammar in 16 pixels: a tile, a highlight over the top half
 *  ending on a hard line, a bevel. Flat is the same tile without any of it,
 *  which is the honest picture of what the button does.
 */
function SurfaceIcon({ aero }: { aero: boolean }) {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden className="shrink-0">
      <rect
        x="2.5"
        y="2.5"
        width="11"
        height="11"
        rx="2"
        fill={aero ? 'currentColor' : 'none'}
        fillOpacity={aero ? 0.22 : 0}
        stroke="currentColor"
        strokeWidth="1.3"
      />
      {aero && (
        <>
          <path d="M3.6 4.2h8.8v3.4H3.6z" fill="currentColor" fillOpacity="0.55" />
          <path d="M3.6 7.6h8.8" stroke="currentColor" strokeWidth="0.9" strokeOpacity="0.75" />
        </>
      )}
    </svg>
  )
}

function SidebarNav({
  admin = false,
  onNavigate,
  compact = false,
}: {
  admin?: boolean
  onNavigate?: () => void
  /** The unpinned rail: icons only, with the label as a tooltip. */
  compact?: boolean
}) {
  // The halo under a tile is half of what makes the icons read as Aero. With
  // the flat shell it is noise on a plain background, so it follows the choice
  // rather than being on or off for good.
  const { surface } = useTheme()
  const glow = surface === 'aero'
  return (
    <nav className={`flex-1 overflow-y-auto py-4 ${compact ? 'px-2' : 'px-3'}`}>
      <div className="space-y-5">
        {NAV_GROUPS.map((group) => (
          <section key={group.label}>
            {compact ? (
              <div className="mx-2 mb-1.5 border-t border-[var(--sb-edge)]" />
            ) : (
              <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--sb-faint)]">
                {group.label}
              </p>
            )}
            <div className="space-y-1">
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={onNavigate}
                  // Start fetching the page while the pointer is still on its
                  // way to the click. Dashboards and Analyse pull the charting
                  // library with them, a megabyte that is very visible to wait
                  // for once the click has landed.
                  onMouseEnter={() => warm(item.to)}
                  onFocus={() => warm(item.to)}
                  onTouchStart={() => warm(item.to)}
                  className={({ isActive }) => navRow(isActive, compact)}
                title={compact ? item.label : undefined}
                >
                  <AppIcon name={item.icon} size={19} glow={glow} className="shrink-0" />
                  {!compact && <span className="truncate">{item.label}</span>}
                </NavLink>
              ))}
            </div>
          </section>
        ))}
        <section>
          {compact ? (
            <div className="mx-2 mb-1.5 border-t border-[var(--sb-edge)]" />
          ) : (
            <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--sb-faint)]">
              System
            </p>
          )}
          <div className="space-y-1">
            {/* Help is here for everybody, above Administration, because it is
                the one entry a reader who is lost will look for by name. */}
            <NavLink
              to="/help"
              onClick={onNavigate}
              onMouseEnter={() => warm('/help')}
              onFocus={() => warm('/help')}
              onTouchStart={() => warm('/help')}
              className={({ isActive }) => navRow(isActive, compact)}
            title={compact ? 'Help' : undefined}
            >
              <AppIcon name="help" size={19} glow={glow} className="shrink-0" />
              {!compact && <span className="truncate">Help</span>}
            </NavLink>
            {admin && (
              <NavLink
                to="/admin"
                onClick={onNavigate}
                onMouseEnter={() => warm('/admin')}
                onFocus={() => warm('/admin')}
                onTouchStart={() => warm('/admin')}
                className={({ isActive }) => navRow(isActive, compact)}
              title={compact ? 'Administration' : undefined}
              >
                <AppIcon name="admin" size={19} glow={glow} className="shrink-0" />
                {!compact && <span className="truncate">Administration</span>}
              </NavLink>
            )}
          </div>
        </section>
      </div>
    </nav>
  )
}

export default function Layout() {
  const { user, signOut, can } = useAuth()
  const {
    resolvedTheme,
    toggleTheme,
    surface,
    toggleSurface,
    sidebarPinned,
    setSidebarPinned,
    sidebarColour,
    setSidebarColour,
  } = useTheme()
  const aero = surface === 'aero'
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [railHovered, setRailHovered] = useState(false)
  const notificationsRef = useRef<HTMLDivElement>(null)
  const paletteRef = useRef<HTMLDivElement>(null)
  const mobileNavRef = useRef<HTMLElement>(null)
  const mobileToggleRef = useRef<HTMLButtonElement>(null)

  // Unpinned, the pane is a rail that grows back over the page while the
  // pointer is on it. Over, rather than pushing: a page that reflows every
  // time the pointer crosses the left edge is worse than no rail at all.
  const expanded = sidebarPinned || railHovered
  const ink = inkFor(sidebarColour) as React.CSSProperties

  const { data: notifications = [] } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.get<Notification[]>('/system/notifications?unread_only=true&limit=20'),
    refetchInterval: 60_000,
  })

  useClickOutside([notificationsRef], () => setNotificationsOpen(false))
  useClickOutside([paletteRef], () => setPaletteOpen(false))
  useClickOutside([mobileNavRef, mobileToggleRef], () => setMenuOpen(false))

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-700 dark:bg-slate-950 dark:text-slate-300">
      {/* The aside holds the space; the pane itself is fixed, so growing it
          lays it over the page instead of shoving the page sideways. */}
      <aside
        className="hidden shrink-0 transition-[width] duration-200 lg:block"
        style={{ width: sidebarPinned ? 248 : 64 }}
        aria-hidden
      />
      <div
        className={`fixed inset-y-0 left-0 z-40 hidden flex-col border-r transition-[width] duration-200 lg:flex ${
          aero ? 'aero-sidebar' : ''
        }`}
        style={{
          ...ink,
          width: expanded ? 248 : 64,
          backgroundColor: 'var(--sb-bg)',
          borderColor: 'var(--sb-edge)',
        }}
        onMouseEnter={() => !sidebarPinned && setRailHovered(true)}
        onMouseLeave={() => setRailHovered(false)}
        // Keyboard users never hover. Tabbing into the rail opens it the same
        // way, and leaving it closes it again.
        onFocus={() => !sidebarPinned && setRailHovered(true)}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node)) setRailHovered(false)
        }}
      >
        <div
          className={`flex h-[72px] shrink-0 items-center border-b ${expanded ? 'px-5' : 'justify-center px-0'}`}
          style={{ borderColor: 'var(--sb-edge)' }}
        >
          {expanded ? (
            <>
              <Brand />
              <button
                className="ml-auto rounded-lg p-1.5 text-[var(--sb-dim)] transition-colors hover:bg-[var(--sb-hover)] hover:text-[var(--sb-ink)]"
                onClick={() => setSidebarPinned(!sidebarPinned)}
                aria-pressed={sidebarPinned}
                aria-label={sidebarPinned ? 'Unpin the side pane' : 'Pin the side pane open'}
                title={
                  sidebarPinned
                    ? 'Unpin: collapse to a rail that opens when you point at it'
                    : 'Pin it open'
                }
              >
                <PinIcon pinned={sidebarPinned} />
              </button>
            </>
          ) : (
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand-500 shadow-lg shadow-brand-500/20">
              <img src="/logo.svg" alt="" className="h-6 w-6" />
            </div>
          )}
        </div>
        <SidebarNav admin={can('admin')} compact={!expanded} />
        <div
          className={`shrink-0 border-t py-4 ${expanded ? 'px-5' : 'px-2 text-center'}`}
          style={{ borderColor: 'var(--sb-edge)' }}
        >
          {expanded ? (
            <>
              <div className="text-xs font-medium text-[var(--sb-dim)]">SurveyHQ</div>
              <div className="mt-0.5 text-[11px] text-[var(--sb-faint)]">
                Monitoring · analysis · publishing
              </div>
            </>
          ) : (
            <div className="text-[11px] font-semibold text-[var(--sb-faint)]">HQ</div>
          )}
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className={`sticky top-0 z-30 flex h-[72px] items-center justify-between gap-3 border-b border-slate-200/80 px-4 dark:border-slate-800 lg:px-7 ${
            aero ? 'aero-glass' : 'bg-white/90 backdrop-blur-xl dark:bg-slate-950/90'
          }`}
        >
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

          <div className="ml-auto hidden md:block">
            <ProjectFilter compact />
          </div>

          <div className="flex items-center gap-1.5">
            <div className="relative" ref={paletteRef}>
              <button
                className="icon-button"
                onClick={() => setPaletteOpen((open) => !open)}
                aria-expanded={paletteOpen}
                aria-label="Side pane colour"
                title={`Side pane colour: ${nameOf(sidebarColour)}`}
              >
                <PaletteIcon />
              </button>
              {paletteOpen && (
                <div className="absolute right-0 top-12 z-40 w-[260px] rounded-xl border border-slate-200 bg-white p-3 shadow-2xl shadow-slate-950/10 dark:border-slate-800 dark:bg-slate-900">
                  <p className="mb-2 text-xs font-semibold text-slate-900 dark:text-slate-100">
                    Side pane colour
                  </p>
                  <div className="grid grid-cols-5 gap-2">
                    {SIDEBAR_PRESETS.map((preset) => {
                      const chosen = preset.value === sidebarColour
                      return (
                        <button
                          key={preset.id}
                          onClick={() => setSidebarColour(preset.value)}
                          title={preset.label}
                          aria-label={preset.label}
                          aria-pressed={chosen}
                          className={`h-8 w-full rounded-lg border transition-transform hover:scale-105 ${
                            chosen
                              ? 'border-brand-500 ring-2 ring-brand-500/40'
                              : 'border-slate-300 dark:border-slate-700'
                          }`}
                          style={{ backgroundColor: preset.value ?? DEFAULT_SIDEBAR }}
                        />
                      )
                    })}
                  </div>
                  <label className="mt-3 flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
                    <input
                      type="color"
                      className="h-7 w-10 cursor-pointer rounded border border-slate-300 bg-transparent dark:border-slate-700"
                      value={sidebarColour ?? DEFAULT_SIDEBAR}
                      onChange={(event) => setSidebarColour(event.target.value)}
                      aria-label="A colour of your own"
                    />
                    A colour of your own
                  </label>
                  <p className="mt-2 text-[11px] leading-4 text-slate-500">
                    The text follows the colour, so a pale pane gets dark ink. Kept on this
                    computer, not on your account.
                  </p>
                </div>
              )}
            </div>
            <button
              className="icon-button"
              onClick={toggleSurface}
              aria-pressed={aero}
              aria-label={aero ? 'Use the flat surfaces' : 'Use the Aero surfaces'}
              title={aero ? 'Flat surfaces' : 'Aero surfaces'}
            >
              <SurfaceIcon aero={aero} />
            </button>
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
                  <span className="absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-ink-900 px-1 text-[9px] font-bold text-white ring-2 ring-white dark:bg-dark-800 dark:text-dark-100 dark:ring-slate-950">
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

        {/* The same rows, so it needs the same ink: without it every colour
            in here resolves to nothing. Never a rail - a drawer you opened
            on purpose has no reason to show only icons. */}
        <nav
          ref={mobileNavRef}
          className={`overflow-hidden border-b transition-[max-height,opacity] duration-200 ease-out lg:hidden ${
            menuOpen ? 'max-h-[75vh] opacity-100' : 'pointer-events-none max-h-0 opacity-0'
          }`}
          style={{ ...ink, backgroundColor: 'var(--sb-bg)', borderColor: 'var(--sb-edge)' }}
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
