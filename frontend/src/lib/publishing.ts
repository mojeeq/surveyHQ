/**
 * Dashboards published to a web server somewhere else: GitHub Pages, a
 * server reached over SFTP, an FTP host.
 *
 * What goes there is the HTML export - the board as one file, its filters
 * still working, the numbers behind every widget and none of the rows - so
 * this platform can sit on an office network while the board is read on a
 * public website.
 */

export type PublishKind = 'github' | 'sftp' | 'ftp'

export interface PublishTarget {
  id: string
  name: string
  kind: PublishKind
  settings: Record<string, unknown>
  /** Which secrets are kept - "token", "password", "private_key" - never the secrets. */
  secrets: string[]
  host_key_fingerprint: string
  /** Where the destination's folder is served, as far as is known. */
  folder_url: string
  publications: number
  created_at: string | null
}

export interface TargetCheck {
  message: string
  url: string
  notes: string[]
  host_key_fingerprint: string
}

export interface Publication {
  id: string
  dashboard_id: string
  target_id: string
  target_name: string
  target_kind: string
  path: string
  view_id: string
  view_name: string
  auto_republish: boolean
  status: 'published' | 'failed'
  url: string
  last_published_at: string | null
  last_error: string
  size_bytes: number
  notes: string[]
  created_at: string | null
}

export const KIND_LABEL: Record<PublishKind, string> = {
  github: 'GitHub Pages',
  sftp: 'SFTP',
  ftp: 'FTP',
}

const text = (value: unknown) => (typeof value === 'string' ? value : value == null ? '' : String(value))

/** Where a destination puts pages, in a line. */
export function whereTo(target: Pick<PublishTarget, 'kind' | 'settings'>): string {
  const settings = target.settings
  if (target.kind === 'github') {
    const folder = text(settings.folder)
    return `${text(settings.owner)}/${text(settings.repo)} · ${text(settings.branch) || 'gh-pages'}${
      folder ? ` · ${folder}/` : ''
    }`
  }
  const standard = target.kind === 'sftp' ? 22 : 21
  const port = Number(settings.port) || standard
  const folder = text(settings.folder)
  return `${text(settings.username)}@${text(settings.host)}${port === standard ? '' : `:${port}`}${
    folder ? `:${folder}` : ''
  }`
}

/**
 * The folder a board goes to unless somebody says otherwise: its name, and
 * its view's after it. Letters and digits with dashes between, which is what
 * the server accepts and what survives being pasted into an email.
 */
export function suggestPath(name: string, viewName = ''): string {
  const slug = (value: string, limit: number) =>
    value
      .normalize('NFKD')
      .replace(/[̀-ͯ]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, limit)
      .replace(/-+$/g, '')
  const board = slug(name, 80) || 'dashboard'
  return viewName ? `${board}-${slug(viewName, 60) || 'view'}` : board
}

/** What is wrong with an address, in the server's words, before it is sent. */
export function pathProblem(path: string): string | null {
  const parts = path.trim().split('/').filter(Boolean)
  for (const part of parts) {
    if (part === '.' || part === '..') return "An address cannot contain '.' or '..'"
    if (!/^[A-Za-z0-9._-]+$/.test(part)) {
      return 'Use letters, digits, dots, dashes and underscores, with / between folders'
    }
  }
  if (parts.join('/').length > 200) return 'An address can be 200 characters at most'
  return null
}

/** The web address a page at `path` will have on this destination. */
export function pageUrl(target: Pick<PublishTarget, 'folder_url'>, path: string): string {
  if (!target.folder_url) return ''
  const cleaned = path.trim().split('/').filter(Boolean).join('/')
  return `${target.folder_url.replace(/\/+$/, '')}/${cleaned ? `${cleaned}/` : ''}`
}
