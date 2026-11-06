/**
 * Where the reader is, in the bar along the top of every page.
 *
 * The bar said "Survey workspace - Monitor collection, analyse data and
 * publish results" on every page of the platform: the same sentence in the
 * best-placed line of the screen, telling nobody anything. It now says which
 * section this is and, on a page about one thing, which thing, with the
 * section a link back to its list.
 *
 * A page about one thing names it with `useBreadcrumbs`; every other page
 * gets its section from the address alone.
 */
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

export interface Crumb {
  label: string
  /** Where it leads; the last crumb, the page itself, has none. */
  to?: string
}

interface CrumbsApi {
  crumbs: Crumb[] | null
  setCrumbs: (crumbs: Crumb[] | null) => void
}

const Context = createContext<CrumbsApi>({ crumbs: null, setCrumbs: () => {} })

export function BreadcrumbProvider({ children }: { children: ReactNode }) {
  const [crumbs, setCrumbs] = useState<Crumb[] | null>(null)
  return <Context.Provider value={{ crumbs, setCrumbs }}>{children}</Context.Provider>
}

export function useCrumbs(): Crumb[] | null {
  return useContext(Context).crumbs
}

/**
 * Name the page's place, past its section. Pass null while what it is about
 * is still loading; the section alone shows meanwhile.
 */
export function useBreadcrumbs(crumbs: Crumb[] | null) {
  const { setCrumbs } = useContext(Context)
  const key = JSON.stringify(crumbs)
  useEffect(() => {
    setCrumbs(crumbs)
    return () => setCrumbs(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, setCrumbs])
}

/** The sections of the platform, by the first part of their address. */
export const SECTIONS: Record<string, Crumb> = {
  '': { label: 'Overview', to: '/' },
  projects: { label: 'Projects', to: '/projects' },
  datasets: { label: 'Datasets', to: '/datasets' },
  connections: { label: 'Connections', to: '/connections' },
  scripts: { label: 'Scripts', to: '/scripts' },
  explore: { label: 'Analyse', to: '/explore' },
  dashboards: { label: 'Dashboards', to: '/dashboards' },
  indicators: { label: 'Indicators', to: '/indicators' },
  quality: { label: 'Data quality', to: '/quality' },
  alerts: { label: 'Alerts', to: '/alerts' },
  help: { label: 'Help', to: '/help' },
  admin: { label: 'Administration', to: '/admin' },
}

/** The whole trail for an address: its section, then whatever the page added. */
export function trail(pathname: string, crumbs: Crumb[] | null): Crumb[] {
  const first = pathname.replace(/^\/+/, '').split('/')[0] ?? ''
  const section = SECTIONS[first]
  const rest = crumbs ?? []
  if (!section) return rest
  // The section is the page itself until something more specific is named.
  return rest.length ? [section, ...rest] : [{ label: section.label }]
}
