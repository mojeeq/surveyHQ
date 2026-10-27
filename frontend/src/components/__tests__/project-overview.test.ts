/**
 * The mark beside each step of a project's pipeline.
 *
 * The overview exists so that a merge left behind, or a script imports do not
 * run, is seen without visiting six pages. The mark is what catches the eye,
 * so what earns the amber one is pinned.
 */
import { describe, expect, it } from 'vitest'

import { scriptSummary, stepMarks } from '../ProjectOverview'
import type { Overview } from '../ProjectOverview'

function overview(overrides: Partial<Overview> = {}): Overview {
  return {
    attention: [],
    imports: [],
    sources: [],
    merges: [],
    scripts: [],
    outputs: [],
    dashboards: [],
    watching: { indicators: 0, open_alerts: 0, checks: 0, failing_checks: 0 },
    ...overrides,
  }
}

const script = {
  id: 's', name: 'Clean roster', saved: true, commands: 4, last_run_at: '2026-10-01T09:00:00Z',
  last_error: '', reads: ['people'], writes: ['adults'], runs_on_import: true,
}

const source = { id: 'd', name: 'people', rows: 3, refreshed_at: null, paradata: false, from_connection: true }

describe('the mark beside each step', () => {
  it('is empty where the project has nothing yet', () => {
    expect(Object.values(stepMarks(overview()))).toEqual(['none', 'none', 'none', 'none', 'none'])
  })

  it('warns on a failed import', () => {
    const failed = overview({
      sources: [source],
      imports: [
        {
          id: 'c', name: 'Field server', kind: 'survey_solutions', last_sync_at: null,
          last_sync_status: 'failed', last_sync_error: 'refused', next_import_at: null,
        },
      ],
    })
    expect(stepMarks(failed).in).toBe('warn')
  })

  it('warns on a merge that did not keep up', () => {
    const stuck = overview({
      merges: [{ id: 'm', name: 'Roster + Household', from: '', rows: 1, refreshed_at: null, status: 'stuck', message: 'gone' }],
    })
    expect(stepMarks(stuck).joined).toBe('warn')
  })

  it('warns on a script imports will not run', () => {
    const unsaved = { ...script, saved: false, runs_on_import: false }
    expect(stepMarks(overview({ scripts: [unsaved] })).prepared).toBe('warn')
    expect(stepMarks(overview({ scripts: [script] })).prepared).toBe('ok')
  })

  it('warns when any one of several scripts did not keep up', () => {
    const failed = { ...script, id: 't', name: 'Tables', last_error: 'no such variable' }
    expect(stepMarks(overview({ scripts: [script, failed] })).prepared).toBe('warn')
  })

  it('counts a script just started as nothing yet, not as a fault', () => {
    const empty = { ...script, id: 'n', saved: false, commands: 0, last_run_at: null, reads: [], writes: [], runs_on_import: false }
    expect(stepMarks(overview({ scripts: [empty] })).prepared).toBe('none')
    expect(stepMarks(overview({ scripts: [script, empty] })).prepared).toBe('ok')
    expect(scriptSummary(empty)).toBe('Nothing written yet')
  })

  it('warns on open alerts or failing checks', () => {
    const alarmed = overview({ watching: { indicators: 2, open_alerts: 1, checks: 0, failing_checks: 0 } })
    expect(stepMarks(alarmed).watched).toBe('warn')
  })
})
