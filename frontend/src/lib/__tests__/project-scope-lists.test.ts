/**
 * Which project lists the workspace chosen in the header narrows.
 *
 * Choosing a workspace narrows the other pages to that project's data, and the
 * project list they group by with it. The Projects page is the exception: it is
 * where every project is seen and moved between, and narrowed it listed only
 * the one already chosen. It asks with scope=all, which this keeps whole.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setProjectScope } from '@/hooks/useProjectScope'
import { filterScopedCollection } from '@/lib/api'

const PROJECTS = [
  { id: 'fiji', name: 'Fiji Census 2017' },
  { id: 'nauru', name: 'Nauru Census 2026' },
]

// The scope store keeps old deep links in step on two pages; on this one it
// only needs to know where it is. There is no DOM in these tests.
beforeEach(() => {
  vi.stubGlobal('window', { location: { pathname: '/projects', href: 'http://x/projects' } })
})

afterEach(() => {
  setProjectScope(null)
  vi.unstubAllGlobals()
})

describe('the project list under a chosen workspace', () => {
  it('is narrowed to that project for the pages working in it', () => {
    setProjectScope('fiji')
    expect(filterScopedCollection('/projects', PROJECTS)).toEqual([PROJECTS[0]])
  })

  it('is whole for the Projects page, which asks for all of them', () => {
    setProjectScope('fiji')
    expect(filterScopedCollection('/projects?scope=all', PROJECTS)).toEqual(PROJECTS)
  })

  it('is whole everywhere when no workspace is chosen', () => {
    expect(filterScopedCollection('/projects', PROJECTS)).toEqual(PROJECTS)
  })
})
