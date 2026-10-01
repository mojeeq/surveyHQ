/**
 * Where a dashboard's widgets end up when it is drawn small.
 *
 * The thumbnail is only worth having if it is a thumbnail of the board. Both
 * rules it follows are the board's own, and both are easy to get subtly wrong
 * in a way nobody notices: a widget placed by its turn in the list rather than
 * by a stored position, and a grid that packs upwards so stored rows are not
 * drawn rows.
 */

import { describe, expect, it } from 'vitest'

import type { WidgetType } from '@/lib/types'
import { faceOf, placeBlocks, sketchRows } from '@/lib/dashboard-sketch'

const chart = (layout?: Record<string, unknown>) => ({ kind: 'chart' as WidgetType, layout })

describe('where a widget is drawn', () => {
  it('puts a placed widget where it was placed', () => {
    const [block] = placeBlocks([chart({ x: 3, y: 0, w: 5, h: 7 })])
    expect(block).toEqual({ kind: 'chart', x: 3, y: 0, w: 5, h: 7 })
  })

  it('places a widget that was never dragged the way the board would', () => {
    // Two to a row, six wide, four tall. The board's own fallback, and a
    // thumbnail that invented its own would be a thumbnail of nothing.
    const blocks = placeBlocks([chart(), chart(), chart(), chart(), chart()])
    expect(blocks.map((b) => [b.x, b.y, b.w, b.h])).toEqual([
      [0, 0, 6, 4],
      [6, 0, 6, 4],
      [0, 4, 6, 4],
      [6, 4, 6, 4],
      [0, 8, 6, 4],
    ])
  })

  it('fills in only the part of a layout that is missing', () => {
    const [block] = placeBlocks([chart({ w: 4 })])
    expect(block.w).toBe(4)
    expect(block.h).toBe(4)
    expect(block.x).toBe(0)
  })

  it('survives a layout carrying something that is not a number', () => {
    // These are JSON columns written by several versions of the app. A widget
    // whose width arrived as "6" or null is still a widget to draw.
    const [block] = placeBlocks([chart({ x: null, y: undefined, w: 'wide', h: {} })])
    expect(block).toEqual({ kind: 'chart', x: 0, y: 0, w: 6, h: 4 })
  })

  it('reads a width that arrived as a numeric string', () => {
    const [block] = placeBlocks([chart({ x: '2', y: '0', w: '4', h: '3' })])
    expect(block).toEqual({ kind: 'chart', x: 2, y: 0, w: 4, h: 3 })
  })
})

describe('keeping the board inside the picture', () => {
  it('narrows a widget wider than the grid', () => {
    const [block] = placeBlocks([chart({ x: 0, y: 0, w: 20, h: 4 })], 12)
    expect(block.w).toBe(12)
    expect(block.x).toBe(0)
  })

  it('pulls back a widget that starts beyond the right edge', () => {
    // A board saved on a 24-column grid, drawn on 12: without this, half its
    // widgets are outside the viewBox and simply missing from the thumbnail.
    const [block] = placeBlocks([chart({ x: 18, y: 0, w: 6, h: 4 })], 12)
    expect(block.x).toBe(6)
    expect(block.w).toBe(6)
  })

  it('draws a wide board on its own number of columns', () => {
    const [block] = placeBlocks([chart({ x: 12, y: 0, w: 12, h: 4 })], 24)
    expect(block).toEqual({ kind: 'chart', x: 12, y: 0, w: 12, h: 4 })
  })

  it('never gives a widget no size at all', () => {
    const [block] = placeBlocks([chart({ x: -4, y: -2, w: 0, h: 0 })])
    expect(block).toEqual({ kind: 'chart', x: 0, y: 0, w: 1, h: 1 })
  })
})

describe('packing upwards, as the grid does', () => {
  it('lifts a widget with nothing above it to the top', () => {
    // Stored at row 9 because something above it was deleted. The board draws
    // it at the top; a thumbnail drawing row 9 is a thumbnail of empty space.
    const [block] = placeBlocks([chart({ x: 0, y: 9, w: 6, h: 4 })])
    expect(block.y).toBe(0)
  })

  it('stops a widget on the one above it rather than through it', () => {
    const [top, below] = placeBlocks([
      chart({ x: 0, y: 0, w: 6, h: 3 }),
      chart({ x: 0, y: 11, w: 6, h: 3 }),
    ])
    expect(top.y).toBe(0)
    expect(below.y).toBe(3)
  })

  it('lets a widget past one that is beside it, not above it', () => {
    const [left, right] = placeBlocks([
      chart({ x: 0, y: 0, w: 6, h: 3 }),
      chart({ x: 6, y: 11, w: 6, h: 3 }),
    ])
    expect(left.y).toBe(0)
    expect(right.y).toBe(0)
  })

  it('settles the higher widget first, whatever order they are given in', () => {
    // Given bottom-up. Settling in the order given would drop the top widget
    // onto the bottom one and leave the board upside down.
    const [bottom, top] = placeBlocks([
      chart({ x: 0, y: 8, w: 6, h: 2 }),
      chart({ x: 0, y: 2, w: 6, h: 2 }),
    ])
    expect(top.y).toBe(0)
    expect(bottom.y).toBe(2)
  })

  it('gives the blocks back in the order they were asked for', () => {
    const blocks = placeBlocks([
      { kind: 'map', layout: { x: 0, y: 6, w: 6, h: 4 } },
      { kind: 'kpi', layout: { x: 0, y: 0, w: 6, h: 3 } },
    ])
    expect(blocks.map((b) => b.kind)).toEqual(['map', 'kpi'])
  })

  it('closes a gap left in the middle of a column', () => {
    const blocks = placeBlocks([
      chart({ x: 0, y: 0, w: 12, h: 2 }),
      chart({ x: 0, y: 7, w: 12, h: 2 }),
      chart({ x: 0, y: 20, w: 12, h: 2 }),
    ])
    expect(blocks.map((b) => b.y)).toEqual([0, 2, 4])
  })
})

describe('how tall the drawing is', () => {
  it('reaches the bottom of the lowest widget', () => {
    expect(sketchRows(placeBlocks([chart({ x: 0, y: 0, w: 6, h: 5 })]))).toBe(5)
  })

  it('is one row for a board with nothing on it, not zero', () => {
    // A viewBox of height zero draws nothing at all, including the ground.
    expect(sketchRows([])).toBe(1)
  })
})

describe('what a widget looks like at eight pixels tall', () => {
  it('has a shape for every kind of widget there is', () => {
    const kinds: WidgetType[] = [
      'chart', 'table', 'kpi', 'indicator', 'text',
      'crosstab', 'quality', 'countdown', 'map', 'html', 'freshness',
    ]
    for (const kind of kinds) expect(faceOf(kind)).toBeTruthy()
  })

  it('draws the things that are plotted as plots', () => {
    expect(faceOf('chart')).toBe('chart')
    expect(faceOf('quality')).toBe('chart')
  })

  it('draws the things that are one number as one number', () => {
    expect(faceOf('kpi')).toBe('tile')
    expect(faceOf('indicator')).toBe('tile')
    expect(faceOf('countdown')).toBe('tile')
  })

  it('draws the things that are grids of numbers as lists', () => {
    expect(faceOf('table')).toBe('table')
    expect(faceOf('crosstab')).toBe('table')
    expect(faceOf('freshness')).toBe('table')
  })

  it('keeps a map and words apart from both', () => {
    expect(faceOf('map')).toBe('map')
    expect(faceOf('text')).toBe('note')
    expect(faceOf('html')).toBe('note')
  })

  it('falls back rather than drawing nothing for a kind it has not met', () => {
    expect(faceOf('something-new' as WidgetType)).toBe('note')
  })
})
