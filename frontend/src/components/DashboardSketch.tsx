/**
 * A dashboard drawn small enough to fit on its card in a list.
 *
 * Not a screenshot and not a render: the board's widgets are drawn as the
 * cards they are, in the places they sit, with a few strokes inside each to
 * say what kind it is. That is enough to tell a board of six KPI tiles from a
 * board that is one big map, which is the question somebody scanning a list is
 * actually asking, and it costs no queries to answer.
 *
 * One SVG with a viewBox, so it fits whatever width the card gives it and the
 * proportions of the real board survive the scale.
 */

import { useMemo } from 'react'
import type { Appearance } from '@/lib/types'
import {
  type SketchFace,
  type SketchWidget,
  SKETCH_COLUMNS,
  faceOf,
  placeBlocks,
  sketchRows,
} from '@/lib/dashboard-sketch'

/** One grid column, and one grid row, in the drawing's own units. */
const CELL = 16
const ROW = 14
/** The gutter between widgets, which the board has too. */
const GAP = 2

/** Below this a block is a smudge, and strokes inside it are noise. */
const LEGIBLE = { w: 20, h: 16 }

const INK: Record<SketchFace, string> = {
  chart: 'rgb(33 150 243)',
  tile: 'rgb(16 185 129)',
  map: 'rgb(139 92 246)',
  table: 'rgb(100 116 139)',
  note: 'rgb(148 163 184)',
}

/**
 * The strokes inside one widget.
 *
 * Drawn in the block's own pixels and scaled to it, so a tall map and a short
 * one carry the same marks rather than the same number of pixels. Everything
 * sits inside an inset, because a bar that touches the edge of its card reads
 * as part of the card.
 */
function Marks({
  face,
  x,
  y,
  w,
  h,
}: {
  face: SketchFace
  x: number
  y: number
  w: number
  h: number
}) {
  const pad = Math.min(5, w / 6, h / 5)
  const left = x + pad
  const top = y + pad
  const width = w - pad * 2
  const height = h - pad * 2
  const colour = INK[face]

  if (face === 'chart') {
    // Four bars on a baseline, uneven, because an even four is a fence.
    const heights = [0.5, 0.85, 0.62, 1]
    const bar = width / 7
    return (
      <g fill={colour}>
        {heights.map((tall, index) => (
          <rect
            key={index}
            x={left + index * bar * 1.7}
            y={top + height * (1 - tall)}
            width={bar}
            height={height * tall}
            rx={0.6}
          />
        ))}
      </g>
    )
  }

  if (face === 'tile') {
    // One number, large, with its label under it.
    return (
      <g fill={colour}>
        <rect x={left} y={top + height * 0.2} width={width * 0.58} height={height * 0.34} rx={1} />
        <rect
          x={left}
          y={top + height * 0.68}
          width={width * 0.78}
          height={Math.max(1, height * 0.1)}
          rx={0.6}
          opacity={0.55}
        />
      </g>
    )
  }

  if (face === 'map') {
    // Points scattered on a ground, which is what every map on this platform
    // is: interview locations, not a choropleth.
    const points = [
      [0.22, 0.3],
      [0.48, 0.18],
      [0.7, 0.42],
      [0.34, 0.62],
      [0.62, 0.76],
      [0.86, 0.6],
    ]
    const dot = Math.max(1, Math.min(width, height) / 11)
    return (
      <g fill={colour}>
        <rect x={left} y={top} width={width} height={height} rx={1.5} opacity={0.12} />
        {points.map(([px, py], index) => (
          <circle key={index} cx={left + width * px} cy={top + height * py} r={dot} />
        ))}
      </g>
    )
  }

  // A list of rows, or lines of words: the same marks, with a heavier first
  // line for a table's header and a ragged last line for a note's paragraph.
  const lines = Math.max(2, Math.min(4, Math.floor(height / 5)))
  const thickness = Math.max(1, height * 0.1)
  const widths = face === 'table' ? [1, 1, 1, 1] : [1, 0.92, 0.6, 0.8]
  return (
    <g fill={colour}>
      {Array.from({ length: lines }, (_, index) => (
        <rect
          key={index}
          x={left}
          y={top + (index * (height - thickness)) / Math.max(1, lines - 1)}
          width={width * (widths[index] ?? 1)}
          height={thickness}
          rx={0.6}
          opacity={face === 'table' && index === 0 ? 0.9 : 0.5}
        />
      ))}
    </g>
  )
}

export default function DashboardSketch({
  widgets,
  appearance,
  className = '',
}: {
  widgets: SketchWidget[]
  appearance?: Appearance
  className?: string
}) {
  const columns = Math.max(1, Number(appearance?.columns) || SKETCH_COLUMNS)
  const blocks = useMemo(() => placeBlocks(widgets, columns), [widgets, columns])
  const rows = sketchRows(blocks)

  // A board with a ground of its own is previewed on it, and its widgets are
  // the white cards they are on the real thing. Without one the preview takes
  // the page's own surface, which has a dark mode where a fixed colour would
  // not.
  //
  // Applied as backgroundColor rather than the `background` shorthand, as the
  // board itself does. The value is whatever is in the appearance JSON, and
  // the shorthand would accept `url(https://somewhere/x.png)` from it - which
  // the browser would then fetch for every card on the page. A colour property
  // takes colours and drops anything else.
  const ground = (appearance?.background_color ?? '').trim()

  if (!blocks.length)
    return (
      <div
        className={`flex items-center justify-center text-xs text-ink-400 dark:text-dark-400 ${
          ground ? '' : 'bg-ink-50 dark:bg-dark-100'
        } ${className}`}
        style={ground ? { backgroundColor: ground } : undefined}
      >
        No widgets yet
      </div>
    )

  return (
    <div
      className={`overflow-hidden rounded-card ${ground ? '' : 'bg-ink-50 dark:bg-dark-100'} ${className}`}
      style={ground ? { backgroundColor: ground } : undefined}
    >
      {/* The whole board, fitted. Filling the pane instead would mean cropping
          a census board to its first four rows, and four rows of a twelve-row
          board is not a picture of it - the shape of the whole thing is the
          only thing a thumbnail has to offer. */}
      <svg
        viewBox={`0 0 ${columns * CELL} ${rows * ROW}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full"
        role="img"
        aria-label={`${blocks.length} widget${blocks.length === 1 ? '' : 's'}`}
      >
        {blocks.map((block, index) => {
          const x = block.x * CELL + GAP / 2
          const y = block.y * ROW + GAP / 2
          const w = block.w * CELL - GAP
          const h = block.h * ROW - GAP
          const face = faceOf(block.kind)
          return (
            <g key={index}>
              <rect
                x={x}
                y={y}
                width={w}
                height={h}
                rx={2}
                className={ground ? '' : 'fill-white dark:fill-dark-50'}
                fill={ground ? 'rgb(255 255 255 / 0.92)' : undefined}
                stroke="rgb(100 116 139 / 0.22)"
                strokeWidth={0.6}
              />
              {w >= LEGIBLE.w && h >= LEGIBLE.h && (
                <Marks face={face} x={x} y={y} w={w} h={h} />
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
