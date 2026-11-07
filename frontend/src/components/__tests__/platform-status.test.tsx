/**
 * The status strip on Administration -> Background jobs.
 *
 * The API can serve pages while imports and scheduled checks have stopped, and
 * nothing on screen used to say so. These pin that a problem the server found
 * is shown in its own words, and that "running" is only said when there are none.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { PlatformStatusBody, type PlatformStatusReport } from '@/components/admin/PlatformStatus'

const healthy: PlatformStatusReport = {
  checked_at: new Date().toISOString(),
  ok: true,
  problems: [],
  database: { ok: true },
  queue: { ok: true, backlog: { imports: 0, default: 0, monitoring: 0, quality: 0, maintenance: 0 } },
  workers: {
    ok: true,
    responding: [
      { name: 'celery@worker', queues: ['default', 'imports'] },
      { name: 'celery@worker-monitoring', queues: ['maintenance', 'monitoring', 'quality'] },
    ],
    queues_without_worker: [],
  },
  scheduler: {
    ok: true,
    last_sent_at: new Date(Date.now() - 3 * 60_000).toISOString(),
    last_task: 'app.workers.tasks.reap_stale_jobs',
    age_seconds: 180,
  },
  jobs: { queued: 0, running: 0, oldest_queued_at: null },
}

describe('platform status', () => {
  it('says background work is running when nothing is wrong', () => {
    const html = renderToStaticMarkup(<PlatformStatusBody report={healthy} />)
    expect(html).toContain('Background work is running.')
    expect(html).toContain('2 answering')
    expect(html).toContain('Last sent work 3 min ago')
    expect(html).toContain('Nothing waiting')
  })

  it('lists each problem and never says "running" when there is one', () => {
    const report: PlatformStatusReport = {
      ...healthy,
      ok: false,
      problems: [
        'No worker is taking jobs from the imports queue.',
        'The scheduler last sent work 45 minutes ago. Scheduled imports, indicators and checks have stopped.',
      ],
      workers: { ...healthy.workers, ok: false, queues_without_worker: ['imports'] },
      scheduler: { ...healthy.scheduler, ok: false, age_seconds: 2700 },
    }
    const html = renderToStaticMarkup(<PlatformStatusBody report={report} />)
    expect(html).not.toContain('Background work is running.')
    expect(html).toContain('No worker is taking jobs from the imports queue.')
    expect(html).toContain('The scheduler last sent work 45 minutes ago.')
    expect(html).toContain('Nobody on: imports')
  })

  it('says when the queue itself is unreachable', () => {
    const report: PlatformStatusReport = {
      ...healthy,
      ok: false,
      problems: ['The job queue (Redis) is unreachable, so imports and scheduled work cannot run.'],
      queue: { ok: false, backlog: null },
      workers: { ok: null, responding: [], queues_without_worker: [] },
      scheduler: { ok: null, last_sent_at: null, last_task: null, age_seconds: null },
    }
    const html = renderToStaticMarkup(<PlatformStatusBody report={report} />)
    expect(html).toContain('Unreachable')
    expect(html).toContain('Could not be asked')
    expect(html).toContain('Unknown while the queue is unreachable')
  })
})
