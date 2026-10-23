/*
 * What the activity panel says about the work going on behind the screen.
 *
 * Asked for because an import gave no sign of itself between the click and the
 * result: whether the server was still preparing the export, whether the files
 * had been read, whether the merges had been rebuilt - or, as it turned out,
 * passed over without a word. The server writes each step onto the job as it
 * starts and ends; this decides how that reads in the top bar.
 */

import type { Activity, ActivityJob, JobStage } from './types'

/** Still to finish: queued, or running. */
export function isActive(job: Pick<ActivityJob, 'status'>): boolean {
  return job.status === 'queued' || job.status === 'running'
}

/** The step a job is on, or the one it reached last. */
export function currentStage(job: Pick<ActivityJob, 'stages'>): JobStage | null {
  const running = job.stages.find((stage) => stage.status === 'running')
  if (running) return running
  const started = job.stages.filter((stage) => stage.status !== 'pending')
  return started.length ? started[started.length - 1] : null
}

/** One line for the top bar: what is happening now. */
export function headline(activity: Activity | undefined): string {
  const active = (activity?.jobs ?? []).filter(isActive)
  if (!active.length) return ''
  const job = active[0]
  if (job.status === 'queued') return `${job.title} - waiting to start`
  const stage = currentStage(job)
  const doing = stage ? stage.detail || stage.label : 'starting'
  const more = active.length > 1 ? ` (+${active.length - 1} more)` : ''
  return `${doing}${more}`
}

/** Whether a finished job left something somebody should read. */
export function needsAttention(job: ActivityJob): boolean {
  if (job.status === 'failed') return true
  return job.stages.some((stage) => stage.status === 'warning' || stage.status === 'failed')
}

/** How often to ask: often while something is moving, rarely when not. */
export function pollInterval(activity: Activity | undefined): number {
  return (activity?.jobs ?? []).some(isActive) ? 3000 : 30000
}

/** The jobs that were active last time and are not now - the moment the data,
 *  and every dashboard on it, has moved. */
export function justFinished(
  before: Activity | undefined,
  after: Activity | undefined,
): ActivityJob[] {
  const wasActive = new Set((before?.jobs ?? []).filter(isActive).map((job) => job.id))
  return (after?.jobs ?? []).filter((job) => wasActive.has(job.id) && !isActive(job))
}

/** "in 12 min", "in 3 h", or "due now" - when a scheduled import starts. */
export function untilText(due: string, now: number = Date.now()): string {
  const minutes = Math.round((new Date(due).getTime() - now) / 60000)
  if (Number.isNaN(minutes)) return ''
  if (minutes <= 0) return 'due now'
  if (minutes < 60) return `in ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `in ${hours} h`
  return `in ${Math.round(hours / 24)} d`
}

/** The mark beside a step, so its state never rests on colour alone. */
export const STAGE_MARK: Record<JobStage['status'], string> = {
  pending: '○',
  running: '●',
  done: '✓',
  warning: '!',
  failed: '✕',
  skipped: '–',
}
