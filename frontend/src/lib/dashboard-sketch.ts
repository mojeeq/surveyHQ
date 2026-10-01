/**
 * Where a dashboard's widgets sit, worked out small enough to draw as a
 * thumbnail.
 *
 * The list page wants to show what a board looks like without opening it, and
 * the honest way to do that would be to render the board - which is fifteen
 * queries against DuckDB for every card on the page, to produce something
 * 240 pixels wide. So the thumbnail is drawn from the shape alone: where each
 * widget is and what kind it is, which the list endpoint already has in hand.
 *
 * Two rules decide where a block goes, and both are the board's rather than
 * this file's invention:
 *
 *   a widget with no stored position is placed by its turn in the list, two
 *   to a row - which is what the board does with one, so a thumbnail that
 *   placed it anywhere else would be a thumbnail of a different board;
 *
 *   the grid packs upwards, so a widget stored at row 8 with nothing above it
 *   is drawn at row 6. Drawing the stored rows instead leaves a thumbnail full
 *   of gaps the board does not have.
 */

import type { WidgetType } from './types'

/** The grid the board uses unless its appearance says otherwise. */
export const SKETCH_COLUMNS = 12

/** The size a widget is given when it has never been placed or resized. */
const UNPLACED = { w: 6, h: 4 }

/** One widget as the list endpoint sends it. */
export interface SketchWidget {
  kind: WidgetType
  layout?: Record<string, unknown> | null
}

/** One widget as it is drawn: a kind and a box, in grid units. */
export interface SketchBlock {
  kind: WidgetType
  x: number
  y: number
  w: number
  h: number
}

/** A whole number from whatever JSON carried, or the fallback. */
function whole(value: unknown, fallback: number): number {
  const found = Number(value)
  return Number.isFinite(found) ? Math.round(found) : fallback
}

function overlapping(one: SketchBlock, other: SketchBlock): boolean {
  return (
    one.x < other.x + other.w &&
    one.x + one.w > other.x &&
    one.y < other.y + other.h &&
    one.y + one.h > other.y
  )
}

/**
 * Where each widget is drawn, in grid units, in the order they were given.
 *
 * Boxes are kept inside the grid: a board saved on a 24-column grid and drawn
 * on a 12-column one would otherwise put half its widgets outside the picture.
 */
export function placeBlocks(
  widgets: SketchWidget[],
  columns: number = SKETCH_COLUMNS,
): SketchBlock[] {
  const grid = Math.max(1, Math.round(columns) || SKETCH_COLUMNS)

  const blocks: SketchBlock[] = widgets.map((widget, index) => {
    const layout = widget.layout ?? {}
    const w = Math.min(grid, Math.max(1, whole(layout.w, UNPLACED.w)))
    const x = Math.min(grid - w, Math.max(0, whole(layout.x, (index % 2) * UNPLACED.w)))
    return {
      kind: widget.kind,
      x,
      w,
      y: Math.max(0, whole(layout.y, Math.floor(index / 2) * UNPLACED.h)),
      h: Math.max(1, whole(layout.h, UNPLACED.h)),
    }
  })

  // Upwards, nearest the top first, so a block only ever settles on blocks
  // that have already stopped moving.
  const settled: SketchBlock[] = []
  for (const block of [...blocks].sort((a, b) => a.y - b.y || a.x - b.x)) {
    while (block.y > 0 && !settled.some((other) => overlapping({ ...block, y: block.y - 1 }, other)))
      block.y -= 1
    settled.push(block)
  }

  return blocks
}

/** How many rows of grid the drawn blocks take up, at least one. */
export function sketchRows(blocks: SketchBlock[]): number {
  return Math.max(1, ...blocks.map((block) => block.y + block.h))
}

/**
 * What a widget looks like when it is too small to read.
 *
 * Eleven kinds is more than a thumbnail can distinguish, and most of the
 * differences do not survive the scale: a cross-tab and a table are both a
 * grid of numbers at 8 pixels tall. So they collapse to the five shapes that
 * are actually telling apart - something plotted, something listed, one big
 * number, a map, and words.
 */
export type SketchFace = 'chart' | 'table' | 'tile' | 'map' | 'note'

const FACES: Record<WidgetType, SketchFace> = {
  chart: 'chart',
  quality: 'chart',
  table: 'table',
  crosstab: 'table',
  freshness: 'table',
  kpi: 'tile',
  indicator: 'tile',
  countdown: 'tile',
  map: 'map',
  text: 'note',
  html: 'note',
}

export function faceOf(kind: WidgetType): SketchFace {
  return FACES[kind] ?? 'note'
}
