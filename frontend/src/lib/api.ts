// Thin fetch wrapper: attaches the token, unwraps JSON and normalises errors.

const TOKEN_KEY = 'surveyhq.token'

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

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { body, raw, headers, ...rest } = options
  const token = tokenStore.get()

  const init: RequestInit = {
    ...rest,
    headers: {
      ...(body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
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

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form }),
  blob: (path: string, body?: unknown) =>
    request<Blob>(path, { method: 'POST', body, raw: true }),
}

/** Trigger a browser download for an export endpoint. */
export async function downloadFile(path: string, body: unknown, filename: string) {
  const blob = await api.blob(path, body)
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
