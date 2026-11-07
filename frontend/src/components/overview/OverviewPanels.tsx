// The parts of the Overview that say what a panel's requests returned:
// loading, a failure, an honest empty state, or figures kept from before a
// failed refresh. The rules live in lib/panel-state.ts; these only draw them.

import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Loading } from '@/components/ui'
import { relativeTime } from '@/lib/format'
import type { AttentionPanel, PanelState } from '@/lib/panel-state'
import type { Alert } from '@/lib/types'

/** Something that went wrong and is still wrong, from /monitoring/attention. */
export interface AttentionItem {
  kind: string
  severity: string
  title: string
  detail: string
  link: string
  at: string | null
}

const ATTENTION_KIND: Record<string, string> = {
  quality: 'check failing',
  import: 'import failed',
  script: 'script stopped',
  merge: 'not rebuilt',
  linked: 'not brought in',
}

function message(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'The server did not answer.'
}

/** A request that failed, with nothing earlier to fall back on. */
export function PanelError({ title, error, retry }: { title: string; error: unknown; retry: () => void }) {
  return (
    <div
      role="alert"
      className="my-2 rounded-card border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300"
    >
      <p className="font-medium">{title}</p>
      <p className="mt-0.5 text-xs opacity-80">{message(error)}</p>
      <button type="button" className="mt-2 text-xs font-semibold underline" onClick={retry}>
        Try again
      </button>
    </div>
  )
}

/** Figures still on screen from an earlier request, after a refresh failed. */
export function StaleNote({
  what,
  updatedAt,
  retry,
}: {
  what: string
  updatedAt: number
  retry: () => void
}) {
  const when = updatedAt ? relativeTime(new Date(updatedAt).toISOString()) : 'earlier'
  return (
    <div
      role="status"
      className="mb-3 flex items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200"
    >
      <span>
        Couldn't refresh {what}. Showing what was loaded {when}.
      </span>
      <button type="button" className="shrink-0 font-semibold underline" onClick={retry}>
        Try again
      </button>
    </div>
  )
}

/** Loading, failure, empty or the content, for a panel fed by one request. */
export function PanelBody<T>({
  panel,
  what,
  retry,
  empty,
  children,
}: {
  panel: PanelState<T>
  what: string
  retry: () => void
  empty: ReactNode
  children: (data: T) => ReactNode
}) {
  switch (panel.state) {
    case 'loading':
      return <Loading />
    case 'error':
      return <PanelError title={`Couldn't load ${what}.`} error={panel.error} retry={retry} />
    case 'empty':
      return <>{empty}</>
    case 'stale':
      return (
        <>
          <StaleNote what={what} updatedAt={panel.updatedAt} retry={retry} />
          {children(panel.data)}
        </>
      )
    case 'ready':
      return <>{children(panel.data)}</>
  }
}

/** Needs attention: problems and open alerts, and an all-clear only when both answered. */
export function NeedsAttentionBody({
  panel,
  retry,
}: {
  panel: AttentionPanel<AttentionItem, Alert>
  retry: () => void
}) {
  if (panel.state === 'loading') return <Loading />
  if (panel.state === 'error') {
    return (
      <PanelError
        title={`Couldn't check for ${panel.failed.join(' or ')}.`}
        error={panel.error}
        retry={retry}
      />
    )
  }
  if (panel.state === 'clear') {
    return <p className="py-6 text-center text-sm text-ink-500">Nothing is flagged right now.</p>
  }
  return (
    <>
      {panel.failed.length > 0 && (
        <div
          role="status"
          className="mb-3 flex items-center justify-between gap-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200"
        >
          <span>
            {panel.stale ? "Couldn't refresh" : "Couldn't check for"} {panel.failed.join(' or ')}.
            This list may not be complete.
          </span>
          <button type="button" className="shrink-0 font-semibold underline" onClick={retry}>
            Try again
          </button>
        </div>
      )}
      <ul className="space-y-3">
        {/* Failing checks, failed imports and the rest, beside the alerts: a
            count of four failing checks above a box saying nothing is flagged
            was the page contradicting itself. */}
        {panel.first.map((item, index) => (
          <li
            key={`${item.kind}-${index}`}
            className={`border-l-2 pl-3 ${
              item.severity === 'critical' ? 'border-red-400' : 'border-amber-400'
            }`}
          >
            <div className="flex items-center gap-2">
              <Badge
                tone={item.severity === 'critical' ? 'danger' : 'warning'}
                icon={item.severity === 'critical' ? '■' : '▲'}
              >
                {ATTENTION_KIND[item.kind] ?? item.kind}
              </Badge>
              {item.at && <span className="text-xs text-ink-500">{relativeTime(item.at)}</span>}
            </div>
            <Link
              to={item.link}
              className="mt-1 block text-sm font-medium text-ink-800 hover:text-brand-700 hover:underline"
            >
              {item.title}
            </Link>
            {item.detail && (
              <p className="line-clamp-2 text-xs text-ink-600" title={item.detail}>
                {item.detail}
              </p>
            )}
          </li>
        ))}
        {panel.second.map((alert) => (
          <li key={alert.id} className="border-l-2 border-red-400 pl-3">
            <div className="flex items-center gap-2">
              <Badge
                tone={alert.severity === 'critical' ? 'danger' : 'warning'}
                icon={alert.severity === 'critical' ? '■' : '▲'}
              >
                {alert.severity}
              </Badge>
              <span className="text-xs text-ink-500">{relativeTime(alert.created_at)}</span>
            </div>
            <p className="mt-1 text-sm font-medium text-ink-800">{alert.title}</p>
            <p className="text-xs text-ink-500">{alert.message}</p>
          </li>
        ))}
      </ul>
    </>
  )
}
