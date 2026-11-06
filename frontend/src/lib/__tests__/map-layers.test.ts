/**
 * A data quality map's key: which layers it lists, in what order, with what
 * count - and that what Leaflet writes as markup cannot carry any.
 */
import { describe, expect, it } from 'vitest'

import {
  DEFAULT_POINT_FILL,
  categoryLabel,
  formatMetres,
  mapCategories,
  type MapPoint,
} from '@/lib/map-layers'

const pin = (extra: Partial<MapPoint> = {}): MapPoint => ({ lat: -0.5, lon: 166.9, value: 1, rows: 1, ...extra })

describe('the layers a map lists', () => {
  it('lists nothing but the locations on a plain map', () => {
    const listed = mapCategories({ points: [pin({ rows: 3 }), pin()] })
    expect(listed).toEqual([
      { key: 'gps:all', text: 'Interview locations', color: DEFAULT_POINT_FILL, kind: 'dot', count: 4 },
    ])
  })

  it('lists every finding there is, worst first, counted from the check', () => {
    const listed = mapCategories({
      points: [pin({ area_status: 'match' }), pin({ area_status: 'mismatch' })],
      areaCounts: { match: 40, mismatch: 3, outside: 0, unrecorded: 2 },
      duplicates: { metres: 100, places: 6 },
      manual: {
        points: [pin({ area_status: 'match' }), pin({ area_status: 'mismatch' })],
        counts: { match: 30, mismatch: 4 },
        records: 34,
      },
      lines: { metres: 100, lines: [], total: 5 },
    })
    expect(listed.map((one) => [one.key, one.count])).toEqual([
      ['gps:mismatch', 3],
      ['gps:unrecorded', 2],
      ['gps:match', 40],
      ['duplicates', 6],
      ['manual:mismatch', 4],
      ['manual:match', 30],
      ['lines', 5],
    ])
    expect(listed.find((one) => one.key === 'duplicates')?.text).toBe('Duplicated GPS (within 100 m)')
    expect(listed.find((one) => one.key === 'manual:mismatch')?.text).toBe('Manual location is in another area')
    expect(listed.find((one) => one.key === 'lines')?.text).toBe('GPS and manual over 100 m apart')
  })

  it('calls the second location by the name the widget gives it', () => {
    const listed = mapCategories({
      points: [pin()],
      manual: { points: [pin()], records: 1 },
      manualName: 'Reported',
    })
    expect(listed.map((one) => one.text)).toEqual(['GPS locations', 'Reported locations'])
  })
})

describe('a line of the key', () => {
  it('escapes the name and refuses a colour that is not one', () => {
    const label = categoryLabel({
      key: 'gps:all',
      text: '<img src=x onerror=alert(1)>',
      color: 'red;background:url(javascript:alert(1))',
      kind: 'dot',
      count: 1234,
    })
    expect(label).not.toContain('<img')
    expect(label).toContain('&lt;img')
    expect(label).toContain(`background:${DEFAULT_POINT_FILL}`)
    expect(label).toContain('1,234')
  })

  it('draws each kind of layer the way it is drawn on the map', () => {
    const base = { key: 'x', text: 'x', color: '#111827', count: 1 }
    expect(categoryLabel({ ...base, kind: 'ring' })).toContain('map-key-ring')
    expect(categoryLabel({ ...base, kind: 'line' })).toContain('map-key-line')
    expect(categoryLabel({ ...base, kind: 'area', of: 30 })).toContain('1 of 30')
  })
})

describe('a distance', () => {
  it('reads in metres, then kilometres', () => {
    expect(formatMetres(33.4)).toBe('33 m')
    expect(formatMetres(1080)).toBe('1.1 km')
    expect(formatMetres(14_200)).toBe('14 km')
  })
})
