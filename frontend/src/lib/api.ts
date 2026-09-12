// Thin fetch wrapper: attaches the token, unwraps JSON and normalises errors.

import { getProjectScope } from '@/hooks/useProjectScope'

const TOKEN_KEY = 'surveyhq.token'
const GRANT_PREFIX = 'surveyhq.share.'

/**
 * The proof that a reader knew a shared link's password.
 *
 * Kept per link and only for this tab. A grant is not a login - everybody
 * holding one is the same anonymous reader - so it has no business outliving
 * the tab it was typed into, and a shared computer in a field office is
 * exactly where that matters.
 */
export const shareGrants = {
  get: (token: string) => {
    try {
      return sessionStorage.getItem(GRANT_PREFIX + token) ?? ''
    } catch {
      return ''
    }
  },
  set: (token: string, grant: string) => {
    try {
      sessionStorage.setItem(GRANT_PREFIX + token, grant)
    } catch {
      /* a browser refusing storage still works, it just asks again */
    }
  },
}

/** The share token in the path of a public request, if this is one. */
function shareTokenOf(path: string): string {
  const match = /^\/public\/dashboards\/([^/?]+)/.exec(path)
  return match ? decodeURIComponent(match[1]) : ''
}

export class ApiError extends Error {
  status: number
  fields: { field: string; message: string }[]

  constructor(status: number, message: string, fields: { field: string; message: string }[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fields = fields
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

type Options = Omit<RequestInit, 'body'> & { body?: unknown; raw?: boolean }

/**
 * Lists that understand project_id themselves. Most dataset-owned resources use
 * an empty value for the shared area; dataset/dashboard-style lists use `none`
 * because an empty project_id means "no filter" on those endpoints.
 */
const NONE_FOR_SHARED = new Set([
  '/datasets',
  '/dashboards',
  '/dashboards/charts',
  '/dashboards/chart-library',
  '/boundaries',
  '/relationships',
])
const EMPTY_FOR_SHARED = new Set([
  '/monitoring/summary',
  '/monitoring/indicators',
  '/monitoring/indicators/values',
  '/monitoring/alerts',
  '/monitoring/alert-rules',
  '/monitoring/quality-rules',
])

function parsed(path: string) {
  return new URL(path, 'https://surveyhq.local')
}

/** Add/replace project_id on the list calls that have a server-side filter. */
function scopedGetPath(path: string): string {
  const project = getProjectScope()
  if (project === null || path.startsWith('/public/')) return path

  const url = parsed(path)
  if (NONE_FOR_SHARED.has(url.pathname)) {
    url.searchParams.set('project_id', project || 'none')
  } else if (EMPTY_FOR_SHARED.has(url.pathname)) {
    url.searchParams.set('project_id', project)
  } else {
    return path
  }
  return `${url.pathname}${url.search}${url.hash}`
}

/**
 * Two older collection endpoints do not expose a project_id query parameter.
 * They already return only resources the caller may see, so filtering that
 * authorised response in the browser is both safe and avoids a backend API
 * change just for presentation scope.
 *
 * `/projects?scope=all` is the deliberate escape hatch used by the workspace
 * switcher: it must always be able to list the projects the user can switch to.
 */
function filterScopedCollection<T>(requestedPath: string, value: T): T {
  const project = getProjectScope()
  if (project === null || !Array.isArray(value)) return value

  const url = parsed(requestedPath)
  if (url.pathname === '/connections') {
    return value.filter((item: any) => (item.project_id ?? '') === project) as T
  }
  if (url.pathname === '/projects' && url.searchParams.get('scope') !== 'all') {
    if (project === '') return [] as T
    return value.filter((item: any) => item.id === project) as T
  }
  return value
}

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { body, raw, headers, ...rest } = options
  const token = tokenStore.get()

  // A password-protected shared link carries its grant on every request, since
  // every route behind the password checks it. Attached here rather than at
  // each call site so nothing can be forgotten and left readable.
  const grant = shareGrants.get(shareTokenOf(path))

  const init: RequestInit = {
    ...rest,
    headers: {
      ...(body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(grant ? { 'X-Share-Grant': grant } : {}),
      ...(headers as Record<string, string>),
    },
  }
  if (body !== undefined) {
    init.body = body instanceof FormData ? body : JSON.stringify(body)
  }

  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, init)
  } catch {
    throw new ApiError(0, 'Could not reach the server. Check that the platform is running.')
  }

  // A locked shared link answers 401 until its password is given. That is not
  // an expired session and must not clear the signed-in user's token or bounce
  // them to the sign-in page: the page above handles it by asking.
  if (response.status === 401 && path.startsWith('/public/')) {
    throw new ApiError(401, await detailOf(response))
  }

  if (response.status === 401 && !path.startsWith('/auth/login')) {
    tokenStore.clear()
    if (!location.pathname.startsWith('/login') && !location.pathname.startsWith('/shared')) {
      location.href = '/login'
    }
    throw new ApiError(401, 'Your session has expired. Please sign in again.')
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`
    let fields: { field: string; message: string }[] = []
    try {
      const payload = await response.json()
      if (typeof payload.detail === 'string') message = payload.detail
      else if (Array.isArray(payload.detail)) message = payload.detail[0]?.msg ?? message
      if (Array.isArray(payload.errors)) fields = payload.errors
    } catch {
      /* keep the default message */
    }
    throw new ApiError(response.status, message, fields)
  }

  if (raw) return (await response.blob()) as T
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function detailOf(response: Response): Promise<string> {
  try {
    const payload = await response.json()
    if (typeof payload.detail === 'string') return payload.detail
  } catch {
    /* fall through to the generic message */
  }
  return `Request failed with status ${response.status}`
}

export const api = {
  get: async <T>(path: string) => {
    const value = await request<T>(scopedGetPath(path))
    return filterScopedCollection(path, value)
  },
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form }),
  blob: (path: string, body?: unknown) =>
    request<Blob>(path, { method: 'POST', body, raw: true }),
  // A GET that returns bytes rather than JSON. An <img src> cannot carry the
  // Authorization header, so an authenticated image is fetched and shown from
  // an object URL instead.
  getBlob: (path: string) => request<Blob>(path, { raw: true }),
}

/** Trigger a browser download for an export endpoint.
 *
 * Most exports are a POST carrying the query being exported; a stored file -
 * an import's own archive - is a plain GET, hence the method.
 */
export async function downloadFile(
  path: string,
  body: unknown,
  filename: string,
  method: 'POST' | 'GET' = 'POST',
) {
  const blob = method === 'GET' ? await api.getBlob(path) : await api.blob(path, body)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
