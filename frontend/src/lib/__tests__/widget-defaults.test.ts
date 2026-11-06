/**
 * What a new widget is made of.
 *
 * The last thing that happens before a widget is written, and the part where a
 * mistake is silent: a key missing from the config draws a widget that is
 * simply blank, a key written for the wrong kind leaves settings nothing reads,
 * and a size too small for what is in it is a chart nobody can make out.
 *
 * None of it could be reached before - it was a nested ternary inside the add
 * dialog's mutation, exercised only by filling in the form and pressing the
 * button.
 */

import { describe, expect, it } from 'vitest'

import {
  type WidgetAnswers,
  looksLikeAnUnsplitGps,
  widgetConfig,
  widgetLayout,
  widgetTitle,
} from '@/lib/widget-defaults'

// --- naming ------------------------------------------------------------------

describe('what a widget is called', () => {
  it('uses the name somebody typed, whatever kind it is', () => {
    expect(widgetTitle('map', 'Where the teams are', {})).toBe('Where the teams are')
    expect(widgetTitle('chart', 'Interviews by province', { chartName: 'Other' })).toBe(
      'Interviews by province',
    )
  })

  it('falls back to what the widget is of', () => {
    expect(widgetTitle('chart', '', { chartName: 'Interviews by province' })).toBe(
      'Interviews by province',
    )
    expect(widgetTitle('indicator', '', { indicatorName: 'Response rate' })).toBe(
      'Response rate',
    )
    expect(widgetTitle('quality', '', { datasetName: 'people' })).toBe(
      'Data quality: people',
    )
    expect(widgetTitle('countdown', '', { deadlineLabel: 'Fieldwork ends' })).toBe(
      'Fieldwork ends',
    )
  })

  it('has a fixed name for the kinds that are of nothing', () => {
    expect(widgetTitle('map', '', {})).toBe('Interview locations')
    expect(widgetTitle('html', '', {})).toBe('Embedded content')
    expect(widgetTitle('freshness', '', {})).toBe('Data freshness')
    expect(widgetTitle('countdown', '', {})).toBe('Countdown')
  })

  it('does not name a text note after whatever indicator was last picked', () => {
    // The ternary this replaced ended on the indicator name, so every kind it
    // did not mention fell through to it: switch an indicator widget to a text
    // note and the note was saved as "Response rate".
    expect(widgetTitle('text', '', { indicatorName: 'Response rate' })).toBe('Widget')
  })

  it('never writes a widget with no title at all', () => {
    // Every rung can come back empty: an indicator no longer in the list, a
    // dataset still loading. The ladder has to end on something.
    expect(widgetTitle('indicator', '', {})).toBe('Widget')
    expect(widgetTitle('chart', '', {})).toBe('Widget')
    expect(widgetTitle('text', '', {})).toBe('Widget')
  })
})

// --- the config each kind is written with ------------------------------------

describe('a map widget', () => {
  const map: WidgetAnswers = {
    latitude: 'gps__latitude',
    longitude: 'gps__longitude',
    measureAgg: 'count',
    measureVariable: 'wage',
    detail: ['interview__key'],
    basemap: 'streets',
  }

  it('carries the two columns it plots', () => {
    const config = widgetConfig('map', map)
    expect(config.latitude).toBe('gps__latitude')
    expect(config.longitude).toBe('gps__longitude')
  })

  it('forgets the column when the measure is a count', () => {
    // A count needs nothing to count, and carrying the last column chosen would
    // have the widget sum a variable the dialog no longer shows.
    expect(widgetConfig('map', map).measure_variable).toBe('')
  })

  it('keeps the column when the measure is of something', () => {
    expect(
      widgetConfig('map', { ...map, measureAgg: 'sum' }).measure_variable,
    ).toBe('wage')
  })

  it('leaves out the tiles and the basemap when they are the usual ones', () => {
    const config = widgetConfig('map', map)
    expect('tiles' in config).toBe(false)
    expect('basemap' in config).toBe(false)
  })

  it('writes them when they are not', () => {
    const config = widgetConfig('map', {
      ...map,
      tiles: '  https://tiles.example/{z}/{x}/{y}.png  ',
      basemap: 'satellite',
    })
    // Trimmed, so a pasted URL with a stray space is still a URL.
    expect(config.tiles).toBe('https://tiles.example/{z}/{x}/{y}.png')
    expect(config.basemap).toBe('satellite')
  })
})

describe('a data quality panel', () => {
  it('always says which view it is', () => {
    expect(widgetConfig('quality', { qualityView: 'rates' }).quality_view).toBe('rates')
  })

  it('leaves out a chart and a limit nobody chose', () => {
    const config = widgetConfig('quality', { qualityView: 'list' })
    expect('quality_chart' in config).toBe(false)
    expect('quality_limit' in config).toBe(false)
  })

  it('writes them when they were chosen', () => {
    const config = widgetConfig('quality', {
      qualityView: 'rates',
      qualityChart: 'bar',
      qualityLimit: 10,
    })
    expect(config.quality_chart).toBe('bar')
    expect(config.quality_limit).toBe(10)
  })

  it('treats a limit of none as none, not as zero', () => {
    // The limit is held as a number and 0 means "no limit", so writing it would
    // make a panel that shows nothing.
    expect('quality_limit' in widgetConfig('quality', { qualityLimit: 0 })).toBe(false)
  })
})

describe('a countdown', () => {
  it('is written as an instant, so it reads the same anywhere', () => {
    const config = widgetConfig('countdown', {
      deadline: '2026-12-01T09:30',
      deadlineLabel: 'Fieldwork ends',
    })
    expect(config.target).toBe(new Date('2026-12-01T09:30').toISOString())
    expect(String(config.target)).toMatch(/Z$/)
    expect(config.label).toBe('Fieldwork ends')
  })
})

describe('the other kinds', () => {
  it('a freshness panel comes with thresholds already set', () => {
    const config = widgetConfig('freshness', { freshnessDatasets: ['a', 'b'] })
    expect(config.dataset_ids).toEqual(['a', 'b'])
    expect(config.warn_hours).toBe(24)
    expect(config.critical_hours).toBe(72)
  })

  it('a text note carries its content', () => {
    expect(widgetConfig('text', { content: 'Round two begins Monday' }).content).toBe(
      'Round two begins Monday',
    )
  })

  it('an indicator tile remembers what it was told to show', () => {
    const config = widgetConfig('indicator', { showBreakdown: false, showTrend: true })
    expect(config.show_breakdown).toBe(false)
    expect(config.show_trend).toBe(true)
  })

  it('a chart widget needs no config of its own', () => {
    expect(widgetConfig('chart', {})).toEqual({})
  })
})

describe('the caption', () => {
  it('goes on any kind', () => {
    for (const kind of ['chart', 'text', 'map', 'freshness'] as const) {
      expect(widgetConfig(kind, { caption: 'As at Friday' }).caption).toBe('As at Friday')
    }
  })

  it('is left out when it is blank or only spaces', () => {
    expect('caption' in widgetConfig('chart', { caption: '   ' })).toBe(false)
    expect('caption' in widgetConfig('chart', {})).toBe(false)
  })

  it('is trimmed', () => {
    expect(widgetConfig('chart', { caption: '  As at Friday ' }).caption).toBe(
      'As at Friday',
    )
  })
})

describe('what each kind writes and what it does not', () => {
  it('writes only the keys its own kind uses', () => {
    // A map's columns are meaningless on a text note, and writing them anyway
    // leaves a widget carrying settings nothing reads.
    const everything: WidgetAnswers = {
      latitude: 'lat',
      longitude: 'lon',
      html: '<p>hi</p>',
      content: 'note',
      qualityView: 'list',
      freshnessDatasets: ['a'],
    }
    expect(Object.keys(widgetConfig('text', everything))).toEqual(['content'])
    expect(Object.keys(widgetConfig('html', everything))).toEqual(['html'])
    expect('latitude' in widgetConfig('quality', everything)).toBe(false)
    expect('html' in widgetConfig('map', everything)).toBe(false)
  })
})

// --- the room it takes -------------------------------------------------------

describe('how big a new widget is', () => {
  it('gives a map the most room', () => {
    expect(widgetLayout('map', {})).toEqual({ w: 6, h: 6 })
  })

  it('gives the small kinds a tile', () => {
    expect(widgetLayout('countdown', {})).toEqual({ w: 3, h: 3 })
    expect(widgetLayout('freshness', {})).toEqual({ w: 4, h: 4 })
  })

  it('grows an indicator tile that has a chart under it', () => {
    expect(
      widgetLayout('indicator', { showBreakdown: true, hasBreakdownVariable: true }),
    ).toEqual({ w: 4, h: 5 })
  })

  it('leaves it a tile when there is no chart to make room for', () => {
    // Both halves matter: asked for a breakdown the indicator cannot draw, or
    // able to draw one nobody asked for, the extra room is empty space.
    expect(
      widgetLayout('indicator', { showBreakdown: true, hasBreakdownVariable: false }),
    ).toEqual({ w: 3, h: 3 })
    expect(
      widgetLayout('indicator', { showBreakdown: false, hasBreakdownVariable: true }),
    ).toEqual({ w: 3, h: 3 })
  })

  it('gives everything else the default', () => {
    expect(widgetLayout('chart', {})).toEqual({ w: 6, h: 4 })
    expect(widgetLayout('text', {})).toEqual({ w: 6, h: 4 })
  })
})

// --- telling somebody their GPS was never split ------------------------------

describe('spotting GPS that was never split into columns', () => {
  const numeric = (name: string) => ({ name, var_type: 'numeric' })
  const text = (name: string) => ({ name, var_type: 'text' })

  it('says so when there is a location column and no coordinates', () => {
    expect(looksLikeAnUnsplitGps([text('gps'), numeric('age')])).toBe(true)
    expect(looksLikeAnUnsplitGps([text('home_geopoint')])).toBe(true)
    expect(looksLikeAnUnsplitGps([text('interview location')])).toBe(true)
  })

  it('says nothing once the split has happened', () => {
    // A numeric latitude settles it, whatever else the dataset carries.
    expect(
      looksLikeAnUnsplitGps([text('gps'), numeric('gps__latitude'), numeric('gps__longitude')]),
    ).toBe(false)
    expect(looksLikeAnUnsplitGps([text('gps'), numeric('lat')])).toBe(false)
  })

  it('is not fooled by a word that merely contains one of these', () => {
    // "allocation" contains "location" and is not a GPS column. Matching on
    // whole words rather than substrings is what keeps this from warning about
    // every dataset with a budget in it.
    expect(looksLikeAnUnsplitGps([text('allocation'), text('relocation')])).toBe(false)
  })

  it('says nothing about a dataset with no location at all', () => {
    expect(looksLikeAnUnsplitGps([text('name'), numeric('age')])).toBe(false)
    expect(looksLikeAnUnsplitGps([])).toBe(false)
  })

  it('does not take a numeric column as the location itself', () => {
    // A numeric "gps" is already a number and cannot be the unsplit text field
    // this is looking for.
    expect(looksLikeAnUnsplitGps([numeric('gps')])).toBe(false)
  })
})
