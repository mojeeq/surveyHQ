/**
 * How the activity panel reads the steps the server writes onto a job.
 */
import { describe, expect, it } from 'vitest'

import {
  boardFreshness,
  currentStage,
  headline,
  justFinished,
  needsAttention,
  pollInterval,
  untilText,
} from '../activity'
import type { Activity, ActivityJob, JobStage } from '../types'

function stage(key: string, status: JobStage['status'], detail = ''): JobStage {
  return { key, label: `Step ${key}`, status, detail, items: [] }
}

function job(overrides: Partial<ActivityJob> = {}): ActivityJob {
  return {
    id: 'j1',
    job_type: 'sync',
    status: 'running',
    title: 'Scheduled import from Field server',
    progress: 40,
    stages: [],
    error: '',
    warnings: [],
    project_name: 'Nauru Census 2026',
    started_at: null,
    finished_at: null,
    created_at: '2026-10-23T09:00:00Z',
    ...overrides,
  }
}

const activity = (...jobs: ActivityJob[]): Activity => ({ jobs, upcoming: [] })

describe('the step a job is on', () => {
  it('is the running one', () => {
    const stages = [stage('a', 'done'), stage('b', 'running'), stage('c', 'pending')]
    expect(currentStage({ stages })?.key).toBe('b')
  })

  it('is the last one reached once nothing runs', () => {
    const stages = [stage('a', 'done'), stage('b', 'warning'), stage('c', 'pending')]
    expect(currentStage({ stages })?.key).toBe('b')
  })

  it('is nothing before the first step starts', () => {
    expect(currentStage({ stages: [stage('a', 'pending')] })).toBeNull()
  })
})

describe('the line in the top bar', () => {
  it('says what the running step is doing, in its own words', () => {
    const running = job({
      stages: [stage('download', 'running', 'Survey Solutions is preparing the export: 40%')],
    })
    expect(headline(activity(running))).toBe('Survey Solutions is preparing the export: 40%')
  })

  it('counts the others rather than hiding them', () => {
    const one = job({ stages: [stage('merges', 'running')] })
    const two = job({ id: 'j2', status: 'queued' })
    expect(headline(activity(one, two))).toBe('Step merges (+1 more)')
  })

  it('is empty when nothing is happening', () => {
    expect(headline(activity(job({ status: 'success' })))).toBe('')
  })
})

describe('a finished job worth reading', () => {
  it('is one that failed, or one with a step that warned', () => {
    expect(needsAttention(job({ status: 'failed' }))).toBe(true)
    expect(needsAttention(job({ status: 'success', stages: [stage('m', 'warning')] }))).toBe(true)
    expect(needsAttention(job({ status: 'success', stages: [stage('m', 'done')] }))).toBe(false)
  })
})

describe('when the data has moved', () => {
  it('is when a job that was running is not any more', () => {
    const before = activity(job())
    const after = activity(job({ status: 'success' }))
    expect(justFinished(before, after).map((one) => one.id)).toEqual(['j1'])
  })

  it('is not a job that had already finished', () => {
    const done = activity(job({ status: 'success' }))
    expect(justFinished(done, done)).toEqual([])
  })
})

describe('asking the server', () => {
  it('is often while something runs and rarely otherwise', () => {
    expect(pollInterval(activity(job()))).toBe(3000)
    expect(pollInterval(activity(job({ status: 'success' })))).toBe(30000)
  })
})

describe('when a scheduled import starts', () => {
  const now = Date.parse('2026-10-23T09:30:00Z')
  it('reads in minutes, hours or days', () => {
    expect(untilText('2026-10-23T09:42:00Z', now)).toBe('in 12 min')
    expect(untilText('2026-10-23T12:30:00Z', now)).toBe('in 3 h')
    expect(untilText('2026-10-25T09:30:00Z', now)).toBe('in 2 d')
  })

  it('says due now once it is', () => {
    expect(untilText('2026-10-23T09:30:00Z', now)).toBe('due now')
  })
})

describe('the line over a dashboard', () => {
  const now = Date.now()
  const ago = (minutes: number) => new Date(now - minutes * 60000).toISOString()
  const ahead = (minutes: number) => new Date(now + minutes * 60000).toISOString()

  it('says how old the data is and when it next moves', () => {
    expect(boardFreshness({ imported_at: ago(120), next_import_at: ahead(25) }, '', now)).toBe(
      'Data imported 2 h ago · next import in 25 min',
    )
  })

  it('says so when nothing will move it', () => {
    expect(boardFreshness({ imported_at: ago(5), next_import_at: null }, '', now)).toBe(
      'Data imported 5 min ago · no import scheduled',
    )
  })

  it('falls back to the fetch time only when the server does not say', () => {
    expect(boardFreshness(undefined, ago(0), now)).toBe('Data as of just now')
  })
})
