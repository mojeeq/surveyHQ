/*
 * A project, in the order its data travels.
 *
 * A survey round's work was spread over six pages - Connections, Datasets,
 * this project's Relationships tab, Scripts, Dashboards, and four more for
 * monitoring - and following one import from the server to the board meant
 * visiting all of them. Nothing on any of them said that a merge on the way
 * had not been rebuilt, or that the script had never been saved and so never
 * ran on an import.
 *
 * So this is the project's front page: in, joined, prepared, shown, watched,
 * each step saying what it holds and whether it kept up, and anything that
 * needs a person gathered at the top. The other tabs and pages are still where
 * the work is done; this is where it is seen whole.
 */

import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { Loading } from '@/components/ui'
import { boardFreshness, untilText } from '@/lib/activity'
import { api } from '@/lib/api'
import { formatNumber, relativeTime } from '@/lib/format'

export interface Overview {
  attention: { kind: string; title: string; detail: string; link: string }[]
  imports: {
    id: string
    name: string
    kind: string
    last_sync_at: string | null
    last_sync_status: string
    last_sync_error: string
    next_import_at: string | null
  }[]
  sources: {
    id: string
    name: string
    rows: number
    refreshed_at: string | null
    paradata: boolean
    from_connection: boolean
  }[]
  merges: {
    id: string
    name: string
    from: string
    rows: number
    refreshed_at: string | null
    status: 'rebuilt' | 'failed' | 'stuck'
    message: string
  }[]
  script: {
    exists: boolean
    saved?: boolean
    commands?: number
    last_run_at?: string | null
    last_error?: string
    reads?: string[]
    writes?: string[]
    runs_on_import?: boolean
  }
  outputs: { id: string; name: string; rows: number }[]
  dashboards: {
    id: string
    name: string
    widgets: number
    imported_at: string | null
    next_import_at: string | null
  }[]
  watching: { indicators: number; open_alerts: number; checks: number; failing_checks: number }
}

type Mark = 'ok' | 'warn' | 'none'

/** Whether a step kept up: fine, something to look at, or nothing there yet. */
export function stepMarks(overview: Overview): Record<'in' | 'joined' | 'prepared' | 'shown' | 'watched', Mark> {
  const script = overview.script
  return {
    in: !overview.sources.length
      ? 'none'
      : overview.imports.some((one) => one.last_sync_status === 'failed')
        ? 'warn'
        : 'ok',
    joined: !overview.merges.length
      ? 'none'
      : overview.merges.some((one) => one.status !== 'rebuilt')
        ? 'warn'
        : 'ok',
    prepared: !script.exists
      ? 'none'
      : script.last_error || !script.runs_on_import
        ? 'warn'
        : 'ok',
    shown: overview.dashboards.length ? 'ok' : 'none',
    watched: !overview.watching.indicators && !overview.watching.checks
      ? 'none'
      : overview.watching.open_alerts || overview.watching.failing_checks
        ? 'warn'
        : 'ok',
  }
}

const MARK: Record<Mark, { sign: string; tone: string; label: string }> = {
  ok: { sign: '✓', tone: 'bg-brand-500 text-white', label: 'up to date' },
  warn: { sign: '!', tone: 'bg-amber-500 text-white', label: 'needs attention' },
  none: { sign: '–', tone: 'bg-ink-200 text-ink-600 dark:bg-dark-300 dark:text-dark-700', label: 'nothing here yet' },
}

export function ProjectOverview({
  projectId,
  canManage,
  openTab,
}: {
  projectId: string
  canManage: boolean
  openTab: (tab: 'model' | 'data') => void
}) {
  const overview = useQuery({
    queryKey: ['project-overview', projectId],
    queryFn: () => api.get<Overview>(`/projects/${projectId}/overview`),
  })
  if (overview.isLoading || !overview.data) return <Loading />
  const data = overview.data
  const marks = stepMarks(data)
  const paradata = data.sources.filter((one) => one.paradata).length
  const shownSources = data.sources.filter((one) => !one.paradata)

  return (
    <div className="mt-4 space-y-4">
      {data.attention.length > 0 && (
        <div className="rounded-card border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/30 dark:bg-amber-500/10">
          <p className="text-sm font-semibold text-amber-900 dark:text-amber-100">
            {data.attention.length === 1
              ? 'One thing needs attention'
              : `${data.attention.length} things need attention`}
          </p>
          <ul className="mt-2 space-y-1.5">
            {data.attention.map((one, index) => (
              <li key={index} className="text-sm text-amber-900 dark:text-amber-100">
                <Link to={one.link} className="font-medium underline-offset-2 hover:underline">
                  {one.title}
                </Link>
                {one.detail && (
                  <span className="block text-xs text-amber-800/90 dark:text-amber-200/90">
                    {one.detail}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <ol className="relative space-y-4 before:absolute before:bottom-6 before:left-[15px] before:top-6 before:w-px before:bg-ink-200 dark:before:bg-dark-300">
        <Step
          number={1}
          mark={marks.in}
          title="Data comes in"
          summary={
            data.imports.length
              ? `${data.imports.length} connection(s), ${data.sources.length} dataset(s)`
              : data.sources.length
                ? `${data.sources.length} uploaded dataset(s), no connection`
                : 'No data yet'
          }
          action={<Link to="/connections" className="btn-ghost btn-sm">Connections</Link>}
        >
          {data.imports.map((one) => (
            <Row
              key={one.id}
              name={one.name}
              detail={
                <>
                  {one.last_sync_at
                    ? `last import ${relativeTime(one.last_sync_at)}${one.last_sync_status === 'failed' ? ' (failed)' : ''}`
                    : 'never imported'}
                  {' · '}
                  {one.next_import_at ? `next ${untilText(one.next_import_at)}` : 'no import scheduled'}
                </>
              }
              warn={one.last_sync_status === 'failed' ? one.last_sync_error : ''}
            />
          ))}
          {shownSources.map((one) => (
            <Row
              key={one.id}
              name={one.name}
              to={`/datasets/${one.id}`}
              detail={`${formatNumber(one.rows)} rows · updated ${relativeTime(one.refreshed_at)}`}
            />
          ))}
          {paradata > 0 && (
            <p className="text-xs text-ink-500">
              and {paradata} paradata dataset(s), listed on the Data &amp; dashboards tab
            </p>
          )}
        </Step>

        <Step
          number={2}
          mark={marks.joined}
          title="Joined"
          summary={
            data.merges.length
              ? `${data.merges.length} merged dataset(s), rebuilt after every import`
              : 'No merged datasets'
          }
          action={
            <button className="btn-ghost btn-sm" onClick={() => openTab('model')}>
              Relationships
            </button>
          }
        >
          {data.merges.map((one) => (
            <Row
              key={one.id}
              name={one.name}
              to={`/datasets/${one.id}`}
              detail={`${one.from} · ${formatNumber(one.rows)} rows · rebuilt ${relativeTime(one.refreshed_at)}`}
              warn={one.status !== 'rebuilt' ? `Not rebuilt from the latest data. ${one.message}` : ''}
            />
          ))}
          {!data.merges.length && (
            <p className="text-xs text-ink-500">
              Relate two datasets on the Relationships tab and merge them; the merge then
              rebuilds itself whenever its sources change.
            </p>
          )}
        </Step>

        <Step
          number={3}
          mark={marks.prepared}
          title="Prepared"
          summary={
            !data.script.exists
              ? 'No script'
              : data.script.runs_on_import
                ? `A script of ${data.script.commands} command(s), run again on every import`
                : data.script.saved
                  ? 'A saved script that has not run yet'
                  : 'A script that ran but was never saved, so imports do not re-run it'
          }
          action={
            // To the project's script on the Scripts page, where every
            // project's script is written. Somebody who may only read it is
            // shown it, read-only; writing one takes the manager role.
            canManage || data.script.exists ? (
              <Link
                to={`/scripts?project=${encodeURIComponent(projectId)}`}
                className="btn-ghost btn-sm"
              >
                {!canManage ? 'View script' : data.script.exists ? 'Open script' : 'Write a script'}
              </Link>
            ) : undefined
          }
        >
          {data.script.exists && (
            <>
              <p className="text-xs text-ink-500">
                {data.script.last_run_at ? `Last ran ${relativeTime(data.script.last_run_at)}` : 'Never run'}
                {data.script.reads?.length ? ` · reads ${data.script.reads.join(', ')}` : ''}
              </p>
              {data.script.last_error && (
                <p className="text-xs text-amber-800 dark:text-amber-200">{data.script.last_error}</p>
              )}
              {data.outputs.map((one) => (
                <Row
                  key={one.id}
                  name={one.name}
                  to={`/datasets/${one.id}`}
                  detail={`written by the script · ${formatNumber(one.rows)} rows`}
                />
              ))}
            </>
          )}
        </Step>

        <Step
          number={4}
          mark={marks.shown}
          title="Shown"
          summary={
            data.dashboards.length ? `${data.dashboards.length} dashboard(s)` : 'No dashboards yet'
          }
          action={<Link to="/dashboards" className="btn-ghost btn-sm">Dashboards</Link>}
        >
          {data.dashboards.map((one) => (
            <Row
              key={one.id}
              name={one.name}
              to={`/dashboards/${one.id}`}
              detail={`${one.widgets} widget(s) · ${boardFreshness(one, '')}`}
            />
          ))}
        </Step>

        <Step
          number={5}
          mark={marks.watched}
          title="Watched"
          summary="Indicators, alerts and quality checks on this project's data"
        >
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs">
            <Link to="/monitoring" className="text-ink-600 hover:text-brand-700 dark:text-dark-600">
              {data.watching.indicators} indicator(s)
            </Link>
            <Link to="/alerts" className="text-ink-600 hover:text-brand-700 dark:text-dark-600">
              {data.watching.open_alerts} open {data.watching.open_alerts === 1 ? 'alert' : 'alerts'}
            </Link>
            <Link to="/quality" className="text-ink-600 hover:text-brand-700 dark:text-dark-600">
              {data.watching.failing_checks} of {data.watching.checks} check(s) failing
            </Link>
          </div>
        </Step>
      </ol>
    </div>
  )
}

function Step({
  number,
  mark,
  title,
  summary,
  action,
  children,
}: {
  number: number
  mark: Mark
  title: string
  summary: string
  action?: ReactNode
  children?: ReactNode
}) {
  const shown = MARK[mark]
  return (
    <li className="relative flex gap-4">
      <span
        className={`z-10 grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-bold ring-4 ring-white dark:ring-slate-950 ${shown.tone}`}
        title={shown.label}
      >
        <span aria-hidden>{mark === 'none' ? number : shown.sign}</span>
        <span className="sr-only">{`Step ${number}, ${shown.label}`}</span>
      </span>
      <div className="min-w-0 flex-1 rounded-card border border-ink-100 bg-white p-4 dark:border-dark-200 dark:bg-dark-50">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
            <p className="mt-0.5 text-xs text-ink-500">{summary}</p>
          </div>
          {action}
        </div>
        {children && <div className="mt-3 space-y-2">{children}</div>}
      </div>
    </li>
  )
}

function Row({
  name,
  detail,
  to,
  warn,
}: {
  name: string
  detail: ReactNode
  to?: string
  warn?: string
}) {
  return (
    <div className="text-sm">
      {to ? (
        <Link to={to} className="font-medium text-ink-800 hover:text-brand-700">
          {name}
        </Link>
      ) : (
        <span className="font-medium text-ink-800">{name}</span>
      )}
      <span className="block text-xs text-ink-500">{detail}</span>
      {warn && (
        <span className="mt-1 block rounded-control bg-amber-50 px-2 py-1 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
          {warn}
        </span>
      )}
    </div>
  )
}
