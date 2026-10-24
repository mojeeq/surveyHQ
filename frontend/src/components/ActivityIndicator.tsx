/*
 * What is happening behind the screen, in the top bar.
 *
 * Asked for in plain words: an import ran, the merges on it were not rebuilt,
 * the dashboard did not move, and nothing anywhere said so. So every import -
 * a sync, a folder, an upload - writes its steps onto its job as they happen,
 * and this shows them: what is running and which step it is on, what each
 * step did once it finished, and when the next scheduled import will start.
 *
 * When a job finishes, everything on screen is asked for again. A dashboard
 * that is open while its data is replaced would otherwise go on showing what
 * it fetched before, which is the "did not update" this exists to end.
 */

import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { Spinner } from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import {
  currentStage,
  headline,
  isActive,
  justFinished,
  needsAttention,
  pollInterval,
  STAGE_MARK,
  untilText,
} from '@/lib/activity'
import { api } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import type { Activity, ActivityJob, JobStage } from '@/lib/types'

const STAGE_TONE: Record<JobStage['status'], string> = {
  pending: 'text-slate-400',
  running: 'text-brand-600 dark:text-brand-400',
  done: 'text-slate-700 dark:text-slate-300',
  warning: 'text-amber-700 dark:text-amber-300',
  failed: 'text-red-700 dark:text-red-300',
  skipped: 'text-slate-400',
}

export default function ActivityIndicator() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const previous = useRef<Activity | undefined>(undefined)

  const activity = useQuery({
    queryKey: ['activity'],
    queryFn: () => api.get<Activity>('/system/activity'),
    refetchInterval: (query) => pollInterval(query.state.data),
  })

  useEffect(() => {
    const finished = justFinished(previous.current, activity.data)
    previous.current = activity.data
    if (!finished.length) return
    // Everything except this query, which has just answered: datasets,
    // dashboards, indicators and scripts all read what the job wrote.
    queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'activity' })
    for (const job of finished) {
      if (job.status === 'failed') toast.push(`${job.title} failed: ${job.error}`, 'error')
      else if (needsAttention(job))
        toast.push(`${job.title} finished, with something to check - see Activity`, 'info')
      else toast.push(`${job.title} finished. Dashboards now show the new data.`, 'success')
    }
  }, [activity.data, queryClient, toast])

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const jobs = activity.data?.jobs ?? []
  const upcoming = activity.data?.upcoming ?? []
  const busy = jobs.some(isActive)
  const line = headline(activity.data)
  const attention = !busy && jobs.some(needsAttention)

  return (
    <div className="relative" ref={box}>
      <button
        // A button with room for words while something runs, the square icon
        // otherwise. Both take their height from the shared control step.
        className={busy ? 'btn-ghost relative px-2.5' : 'icon-button relative'}
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        aria-label={
          busy
            ? `Background activity: ${line}`
            : attention
              ? 'Background activity: something to check'
              : 'Background activity'
        }
        title={busy ? line : attention ? 'Something to check' : 'Background activity'}
      >
        {busy ? <Spinner className="h-4 w-4 text-brand-600" /> : <PulseIcon />}
        {busy && (
          <span className="hidden max-w-[260px] truncate text-xs font-medium text-slate-700 dark:text-slate-300 xl:inline">
            {line}
          </span>
        )}
        {attention && (
          <span
            aria-hidden
            className="absolute right-1 top-1 h-2 w-2 rounded-full bg-amber-500 ring-2 ring-white dark:ring-slate-950"
          />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-12 z-40 w-[420px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl shadow-slate-950/10 dark:border-slate-800 dark:bg-slate-900">
          <div className="border-b border-slate-100 px-4 py-3.5 dark:border-slate-800">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Background activity
            </span>
            <p className="mt-0.5 text-xs text-slate-500">
              Imports, and what follows them: merges, scripts and dashboards.
            </p>
          </div>

          <div className="max-h-[28rem] overflow-y-auto">
            {jobs.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-slate-500">
                Nothing running, and nothing finished in the last half hour.
              </p>
            ) : (
              jobs.map((job) => <JobRow key={job.id} job={job} />)
            )}

            {upcoming.length > 0 && (
              <div className="border-t border-slate-100 px-4 py-3 dark:border-slate-800">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Next scheduled imports
                </p>
                <ul className="mt-2 space-y-1.5">
                  {upcoming.map((one) => (
                    <li key={one.connection_id} className="flex items-baseline justify-between gap-3 text-xs">
                      <span className="min-w-0 truncate text-slate-700 dark:text-slate-300">
                        {one.name}
                        {one.project_name && (
                          <span className="text-slate-400"> · {one.project_name}</span>
                        )}
                      </span>
                      <span
                        className="shrink-0 font-medium text-slate-900 dark:text-slate-100"
                        title={new Date(one.due_at).toLocaleString()}
                      >
                        {untilText(one.due_at)}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-[11px] leading-4 text-slate-400">
                  Dashboards on that data move when the import and everything after it has
                  finished.
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function JobRow({ job }: { job: ActivityJob }) {
  // Open while it runs or when there is something to read; a clean finish
  // folds away to one line.
  const [expanded, setExpanded] = useState(isActive(job) || needsAttention(job))
  const stage = currentStage(job)
  const when = isActive(job)
    ? job.status === 'queued'
      ? 'waiting to start'
      : `started ${relativeTime(job.started_at)}`
    : `finished ${relativeTime(job.finished_at)}`

  return (
    <div className="border-b border-slate-100 px-4 py-3 last:border-0 dark:border-slate-800">
      <button
        className="flex w-full items-start justify-between gap-3 text-left"
        onClick={() => setExpanded((was) => !was)}
        aria-expanded={expanded}
      >
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
            {job.title || 'Background job'}
          </span>
          <span className="mt-0.5 block text-xs text-slate-500">
            {job.project_name && `${job.project_name} · `}
            {when}
          </span>
        </span>
        <JobStatus job={job} />
      </button>

      {isActive(job) && (
        <div
          className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"
          role="progressbar"
          aria-valuenow={Math.round(job.progress)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={stage?.label ?? 'Progress'}
        >
          <div
            className="h-full rounded-full bg-brand-500 transition-all"
            style={{ width: `${Math.max(job.progress, 4)}%` }}
          />
        </div>
      )}

      {expanded && (
        <ol className="mt-3 space-y-2">
          {job.error && !job.stages.length && (
            <li className="text-xs text-red-700 dark:text-red-300">{job.error}</li>
          )}
          {job.stages.map((one) => (
            <StageRow key={one.key} stage={one} />
          ))}
        </ol>
      )}
    </div>
  )
}

function StageRow({ stage }: { stage: JobStage }) {
  const listed = stage.items.filter(
    (item) => item.status !== 'imported' && item.status !== 'rebuilt' && item.status !== 'ran',
  )
  return (
    <li className="flex gap-2.5 text-xs">
      <span className={`mt-px w-3 shrink-0 text-center font-bold ${STAGE_TONE[stage.status]}`} aria-hidden>
        {stage.status === 'running' ? <Spinner className="h-3 w-3" /> : STAGE_MARK[stage.status]}
      </span>
      <span className="min-w-0">
        <span className={`font-medium ${STAGE_TONE[stage.status]}`}>
          {stage.label}
          <span className="sr-only"> ({stage.status})</span>
        </span>
        {stage.detail && (
          <span className="block leading-5 text-slate-500 dark:text-slate-400">{stage.detail}</span>
        )}
        {/* Only what went wrong, item by item. A list of everything that
            went right reads as noise beside the count that says so. */}
        {listed.length > 0 && (
          <ul className="mt-1 space-y-1">
            {listed.map((item, index) => (
              <li key={`${item.name}-${index}`} className="leading-5 text-slate-600 dark:text-slate-300">
                <span className="font-medium">{item.name}</span>
                {item.status !== 'warning' && item.status !== 'updated' && (
                  <span className="text-slate-400"> - {item.status}</span>
                )}
                {item.detail && <span className="block text-slate-500">{item.detail}</span>}
              </li>
            ))}
          </ul>
        )}
      </span>
    </li>
  )
}

function JobStatus({ job }: { job: ActivityJob }) {
  if (isActive(job))
    return (
      <span className="shrink-0 text-xs font-medium text-brand-600 dark:text-brand-400">
        {job.status === 'queued' ? 'Queued' : `${Math.round(job.progress)}%`}
      </span>
    )
  if (job.status === 'failed')
    return <span className="shrink-0 text-xs font-semibold text-red-700 dark:text-red-300">✕ Failed</span>
  if (needsAttention(job))
    return (
      <span className="shrink-0 text-xs font-semibold text-amber-700 dark:text-amber-300">! Check</span>
    )
  return <span className="shrink-0 text-xs font-medium text-slate-500">✓ Done</span>
}

function PulseIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M3 12h4l3-8 4 16 3-8h4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
