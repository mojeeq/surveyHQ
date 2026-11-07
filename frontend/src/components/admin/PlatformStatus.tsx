// Whether background work is running: the status strip at the top of
// Administration -> Background jobs. A page can be served while imports and
// scheduled checks have quietly stopped; this is where an administrator sees it.

import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import { Card, Loading } from '@/components/ui'
import { PanelError } from '@/components/overview/OverviewPanels'

export interface PlatformStatusReport {
  checked_at: string
  ok: boolean
  problems: string[]
  database: { ok: boolean }
  queue: { ok: boolean; backlog: Record<string, number> | null }
  workers: {
    ok: boolean | null
    responding: { name: string; queues: string[] }[]
    queues_without_worker: string[]
  }
  scheduler: {
    ok: boolean | null
    last_sent_at: string | null
    last_task: string | null
    age_seconds: number | null
  }
  jobs: { queued: number; running: number; oldest_queued_at: string | null } | null
}

type Tone = 'ok' | 'bad' | 'unknown'

function Item({ label, tone, children }: { label: string; tone: Tone; children: React.ReactNode }) {
  const dot = tone === 'ok' ? 'bg-emerald-500' : tone === 'bad' ? 'bg-red-500' : 'bg-ink-300'
  return (
    <div className="rounded-md border border-ink-200 px-3 py-2 dark:border-dark-200">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-500">
        <span className={`inline-block h-2 w-2 rounded-full ${dot}`} aria-hidden />
        {label}
      </div>
      <div className="mt-1 text-sm text-ink-800 dark:text-dark-800">{children}</div>
    </div>
  )
}

const tone = (ok: boolean | null): Tone => (ok === null ? 'unknown' : ok ? 'ok' : 'bad')

export function PlatformStatusBody({ report }: { report: PlatformStatusReport }) {
  const backlog = report.queue.backlog
  const waiting = backlog ? Object.values(backlog).reduce((sum, n) => sum + n, 0) : null
  const workers = report.workers.responding
  return (
    <>
      {report.ok ? (
        <p className="mb-3 text-sm font-medium text-emerald-700 dark:text-emerald-400">
          Background work is running.
        </p>
      ) : (
        <ul role="alert" className="mb-3 space-y-1 text-sm text-red-800 dark:text-red-300">
          {report.problems.map((problem) => (
            <li key={problem}>⚠ {problem}</li>
          ))}
        </ul>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Item label="Database" tone={tone(report.database.ok)}>
          {report.database.ok ? 'Reachable' : 'Unreachable'}
        </Item>
        <Item label="Job queue" tone={tone(report.queue.ok)}>
          {!report.queue.ok ? 'Unreachable' : waiting ? `${waiting} waiting` : 'Nothing waiting'}
        </Item>
        <Item label="Workers" tone={tone(report.workers.ok)}>
          {report.workers.ok === null
            ? 'Could not be asked'
            : `${workers.length} answering`}
          {report.workers.queues_without_worker.length > 0 && (
            <span className="block text-xs text-red-700 dark:text-red-300">
              Nobody on: {report.workers.queues_without_worker.join(', ')}
            </span>
          )}
        </Item>
        <Item label="Scheduler" tone={tone(report.scheduler.ok)}>
          {report.scheduler.last_sent_at
            ? `Last sent work ${relativeTime(report.scheduler.last_sent_at)}`
            : !report.queue.ok
              ? 'Unknown while the queue is unreachable'
              : report.scheduler.ok === null
                ? 'Starting up'
                : 'No activity recorded'}
        </Item>
      </div>
      <p className="mt-2 text-xs text-ink-500">Checked {relativeTime(report.checked_at)}.</p>
    </>
  )
}

export default function PlatformStatus() {
  const status = useQuery({
    queryKey: ['platform-status'],
    queryFn: () => api.get<PlatformStatusReport>('/system/status'),
    refetchInterval: 30_000,
  })
  return (
    <Card title="Platform status" subtitle="Workers, the job queue and the scheduler">
      {status.data ? (
        <PlatformStatusBody report={status.data} />
      ) : status.error ? (
        <PanelError
          title="Couldn't check the platform status."
          error={status.error}
          retry={() => void status.refetch()}
        />
      ) : (
        <Loading />
      )}
    </Card>
  )
}
