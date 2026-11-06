import { describe, expect, it } from 'vitest'

import { trail } from '../useBreadcrumbs'

describe('where you are', () => {
  it('is the section alone on a section\'s own page', () => {
    expect(trail('/datasets', null)).toEqual([{ label: 'Datasets' }])
    expect(trail('/', null)).toEqual([{ label: 'Overview' }])
    expect(trail('/explore', null)).toEqual([{ label: 'Analyse' }])
  })

  it('is the section as a link, then the thing, on a page about one thing', () => {
    expect(trail('/datasets/abc', [{ label: 'members' }])).toEqual([
      { label: 'Datasets', to: '/datasets' },
      { label: 'members' },
    ])
  })

  it('names the section before the thing loads', () => {
    expect(trail('/dashboards/abc', null)).toEqual([{ label: 'Dashboards' }])
  })

  it('reads the Indicators address, old or new, as Indicators', () => {
    expect(trail('/indicators', null)).toEqual([{ label: 'Indicators' }])
  })

  it('leaves an address it does not know to the page', () => {
    expect(trail('/nowhere', null)).toEqual([])
  })
})
