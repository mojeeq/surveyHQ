/**
 * Which script the Scripts page opens, now that a project can have several.
 *
 * Every link made while a project had one script names the project. Those
 * have to go on landing on the script they meant - the project's oldest -
 * and a project with none has to ask for one rather than open nothing.
 */
import { describe, expect, it } from 'vitest'

import { firstOf, nextName, whichToOpen } from '@/lib/script-open'

const place = (script_id: string, project_id: string, created_at: string, name = 'Main script') => ({
  script_id,
  project_id,
  created_at,
  name,
})

// In the running order, which is not the order they were made in.
const listed = [
  place('s-tables', 'p-census', '2026-10-20T00:00:00Z', 'Tables'),
  place('s-clean', 'p-census', '2026-09-01T00:00:00Z'),
  place('s-other', 'p-labour', '2026-10-01T00:00:00Z'),
]

describe('a project\'s first script', () => {
  it('is its oldest, wherever it sits in the order', () => {
    expect(firstOf(listed, 'p-census')?.script_id).toBe('s-clean')
  })

  it('is nothing for a project with none', () => {
    expect(firstOf(listed, 'p-empty')).toBeUndefined()
  })
})

describe('which script the page opens', () => {
  it('opens the first script of a project named in the address', () => {
    expect(whichToOpen(listed, { project: 'p-census', last: 's-other' })).toEqual({ script: 's-clean' })
  })

  it('asks for a script to be started in a named project with none', () => {
    expect(whichToOpen(listed, { project: 'p-empty', last: null })).toEqual({ start: 'p-empty' })
  })

  it('comes back to the script that was open last', () => {
    expect(whichToOpen(listed, { project: null, last: 's-tables' })).toEqual({ script: 's-tables' })
  })

  it('reads a project id left from before scripts had their own as that project\'s first', () => {
    expect(whichToOpen(listed, { project: null, last: 'p-labour' })).toEqual({ script: 's-other' })
  })

  it('opens the first in the list when the last one is gone', () => {
    expect(whichToOpen(listed, { project: null, last: 's-deleted' })).toEqual({ script: 's-tables' })
  })

  it('opens nothing where there is nothing', () => {
    expect(whichToOpen([], { project: null, last: null })).toBeNull()
  })
})

describe('the name a new script gets', () => {
  it('is "Main script" in a project without one', () => {
    expect(nextName(listed, 'p-empty')).toBe('Main script')
  })

  it('is numbered where the project has it, in any case', () => {
    const shouted = [...listed, place('s-x', 'p-labour', '2026-10-02T00:00:00Z', 'MAIN SCRIPT 2')]
    expect(nextName(listed, 'p-census')).toBe('Main script 2')
    expect(nextName(shouted, 'p-labour')).toBe('Main script 3')
  })
})
