/**
 * The mark beside each step of a project's pipeline.
 *
 * The overview exists so that a merge left behind, or a script imports do not
 * run, is seen without visiting six pages. The mark is what catches the eye,
 * so what earns the amber one is pinned.
 */
import { describe, expect, it } from 'vitest'

import { stepMarks } from '../ProjectOverview'
import type { Overview } from '../ProjectOverview'

function overview(overrides: Partial<Overview> = {}): Overview {
  return {
    attention: [],
    imports: [],
    sources: [],
    merges: [],
    script: { exists: false },
    outputs: [],
    dashboards: [],
    watching: { indicators: 0, open_alerts: 0, checks: 0, failing_checks: 0 },
    ...overrides,
  }
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
    expect(stepMarks(overview({ script: { exists: true, saved: false, runs_on_import: false } })).prepared).toBe('warn')
    expect(stepMarks(overview({ script: { exists: true, saved: true, runs_on_import: true } })).prepared).toBe('ok')
  })

  it('warns on open alerts or failing checks', () => {
    const alarmed = overview({ watching: { indicators: 2, open_alerts: 1, checks: 0, failing_checks: 0 } })
    expect(stepMarks(alarmed).watched).toBe('warn')
  })
})
