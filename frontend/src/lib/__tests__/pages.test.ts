import { describe, expect, it } from 'vitest'

import { PAGES } from '@/lib/pages'

/**
 * The list App builds its routes from and the navigation warms from is one
 * list on purpose. A second copy would eventually disagree, and the symptom -
 * one tab that still stalls while the others do not - looks like anything but
 * a stale list.
 */
describe('the page list', () => {
  it('covers every destination in the sidebar', () => {
    // Read off Layout's NAV_GROUPS. Written out rather than imported because
    // importing Layout drags the whole shell, and the point is to notice when
    // these two drift.
    const navigable = [
      '/',
      '/projects',
      '/datasets',
      '/connections',
      '/explore',
      '/dashboards',
      '/monitoring',
      '/quality',
      '/alerts',
      '/help',
      '/admin',
    ]
    for (const path of navigable) {
      expect(Object.keys(PAGES)).toContain(path)
    }
  })

  it('offers a loader for each, not a module', () => {
    // Calling it is what starts the download; a module here would mean the
    // code was already in the bundle and none of this bought anything.
    for (const [path, load] of Object.entries(PAGES)) {
      expect(typeof load, `${path} should be a function`).toBe('function')
    }
  })
})
