import { useSyncExternalStore } from 'react'

/**
 * One project scope for the whole signed-in workspace.
 *
 * null = all projects
 * ''   = shared area
 * id   = one project
 *
 * This deliberately lives outside React context so the API client can read the
 * same scope when it builds list requests. The small external store also means
 * every project picker updates immediately without prop-drilling through the
 * application shell.
 */
export type ProjectScope = string | null

const STORAGE_KEY = 'surveyhq.project-scope'
let current: ProjectScope = readInitial()
const listeners = new Set<() => void>()

function readInitial(): ProjectScope {
  try {
    const url = new URL(window.location.href)
    if (url.searchParams.has('project')) {
      const value = url.searchParams.get('project') ?? ''
      return value === 'none' ? '' : value
    }
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function syncLegacyProjectParam(project: ProjectScope) {
  // Analyse and Data quality historically kept their project filter in the URL.
  // Keep those deep links useful while the workspace scope becomes global.
  const path = window.location.pathname
  if (path !== '/explore' && path !== '/quality') return

  const url = new URL(window.location.href)
  if (project === null) {
    url.searchParams.delete('project')
  } else if (path === '/explore' && project === '') {
    url.searchParams.set('project', 'none')
  } else {
    url.searchParams.set('project', project)
  }
  history.replaceState(history.state, '', `${url.pathname}${url.search}${url.hash}`)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export function getProjectScope(): ProjectScope {
  return current
}

export function setProjectScope(project: ProjectScope) {
  if (project === current) return
  current = project
  try {
    if (project === null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, project)
  } catch {
    // Storage is a convenience. The current tab still keeps the scope.
  }
  syncLegacyProjectParam(project)
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useProjectScope() {
  const project = useSyncExternalStore(subscribe, getProjectScope, () => null)
  return { project, setProject: setProjectScope }
}
