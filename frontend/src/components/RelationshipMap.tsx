import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Cardinality, Dataset, Relationship } from '@/lib/types'
import { Badge } from './ui'

/**
 * The datasets in a project and the links between them.
 *
 * Laid out on a coordinate grid rather than by flex rows. The rows came first
 * and were the cause of most of what was wrong with this: a row of boxes is as
 * wide as its contents, so a census with a dozen tables ran off the side of a
 * canvas that clipped it, and the lines were drawn from the bottom of one card
 * to the top of another whatever their real positions were - so a link between
 * two boxes side by side swooped down and back up through everything between
 * them.
 *
 * Placing every box at a known point fixes both. The diagram knows how big it
 * is, so it can be zoomed, fitted and scrolled instead of cropped, and an edge
 * can leave from whichever side actually faces the box it is going to.
 *
 * A box can still be dragged, and where it is put is remembered per browser:
 * an automatic layout only knows the cardinalities, not which links you are
 * trying to read. The arrangement is a way of looking at the project rather
 * than part of it, so it lives here rather than on the server, and "Tidy up"
 * puts everything back.
 */

const CARDINALITY_LABEL: Record<Cardinality, string> = {
  one_to_one: '1 - 1',
  one_to_many: '1 - ∗',
  many_to_one: '∗ - 1',
  many_to_many: '∗ - ∗',
}

/** Every box the same size, so a long table name cannot widen the layout. */
const BOX_W = 196
const BOX_H = 62
const GAP_X = 36
const GAP_Y = 84
/** The gap above the unlinked tables, which sit apart under their own rule. */
const LOOSE_GAP = 56
const PAD = 24

const ZOOM_MIN = 0.4
const ZOOM_MAX = 1.6

interface Placed {
  dataset: Dataset
  x: number
  y: number
  tier: number
  loose: boolean
}

interface Offset {
  x: number
  y: number
}

/**
 * Which tier each dataset sits on: a parent above the tables that hang off it.
 *
 * Breadth-first from the tables nothing hangs off, which is what gives a survey
 * export its familiar shape - the interview table on top, its rosters below.
 * Bounded by the number of datasets, so a pair of tables each claiming to be
 * the other's parent cannot walk forever.
 */
function tiersOf(datasets: Dataset[], relationships: Relationship[]) {
  const below = new Map<string, string[]>()
  const hasParent = new Set<string>()
  for (const link of relationships) {
    const [over, under] =
      link.cardinality === 'many_to_one'
        ? [link.right_dataset_id, link.left_dataset_id]
        : link.cardinality === 'one_to_many'
          ? [link.left_dataset_id, link.right_dataset_id]
          : [null, null]
    if (!over || !under || over === under) continue
    below.set(over, [...(below.get(over) ?? []), under])
    hasParent.add(under)
  }

  const linked = new Set(
    relationships.flatMap((r) => [r.left_dataset_id, r.right_dataset_id]),
  )
  const tier = new Map<string, number>()
  const roots = datasets.filter((d) => linked.has(d.id) && !hasParent.has(d.id))
  // A cycle would leave every table with a parent and no root to start from.
  // Falling back to the first linked table draws something readable instead of
  // dropping the whole diagram on the floor.
  const start = roots.length ? roots : datasets.filter((d) => linked.has(d.id)).slice(0, 1)

  let front = start.map((d) => d.id)
  let depth = 0
  const seen = new Set(front)
  for (const id of front) tier.set(id, 0)
  while (front.length && depth < datasets.length) {
    depth += 1
    const next: string[] = []
    for (const id of front) {
      for (const child of below.get(id) ?? []) {
        if (seen.has(child)) continue
        seen.add(child)
        tier.set(child, depth)
        next.push(child)
      }
    }
    front = next
  }
  // A many-to-many link leaves both ends without a tier. They are still related
  // and belong in the diagram, one level under whatever they are linked to.
  for (const d of datasets) {
    if (tier.has(d.id) || !linked.has(d.id)) continue
    const neighbours = relationships
      .filter((r) => r.left_dataset_id === d.id || r.right_dataset_id === d.id)
      .map((r) => (r.left_dataset_id === d.id ? r.right_dataset_id : r.left_dataset_id))
      .map((id) => tier.get(id))
      .filter((t): t is number => t !== undefined)
    tier.set(d.id, neighbours.length ? Math.max(...neighbours) + 1 : 0)
  }
  return { tier, linked }
}

/** Where every box goes, and how big the whole thing is. */
function layoutOf(datasets: Dataset[], relationships: Relationship[], width: number) {
  const { tier, linked } = tiersOf(datasets, relationships)
  const perRow = Math.max(1, Math.floor((width - PAD * 2 + GAP_X) / (BOX_W + GAP_X)))

  const rows = new Map<number, Dataset[]>()
  for (const d of datasets) {
    if (!linked.has(d.id)) continue
    const t = tier.get(d.id) ?? 0
    rows.set(t, [...(rows.get(t) ?? []), d])
  }

  const placed: Placed[] = []
  let y = PAD
  for (const t of [...rows.keys()].sort((a, b) => a - b)) {
    const row = rows.get(t)!
    // A tier wider than the canvas wraps rather than running off the edge,
    // which is what used to happen and why a box could not be read at all.
    for (let start = 0; start < row.length; start += perRow) {
      const slice = row.slice(start, start + perRow)
      const span = slice.length * BOX_W + (slice.length - 1) * GAP_X
      const left = Math.max(PAD, (width - span) / 2)
      slice.forEach((d, i) => {
        placed.push({ dataset: d, x: left + i * (BOX_W + GAP_X), y, tier: t, loose: false })
      })
      y += BOX_H + GAP_Y
    }
  }

  const loose = datasets.filter((d) => !linked.has(d.id))
  let divider = 0
  if (loose.length) {
    y = placed.length ? y - GAP_Y + LOOSE_GAP : PAD
    divider = placed.length ? y - LOOSE_GAP / 2 : 0
    for (let start = 0; start < loose.length; start += perRow) {
      const slice = loose.slice(start, start + perRow)
      const span = slice.length * BOX_W + (slice.length - 1) * GAP_X
      const left = Math.max(PAD, (width - span) / 2)
      slice.forEach((d, i) => {
        placed.push({
          dataset: d,
          x: left + i * (BOX_W + GAP_X),
          y,
          tier: -1,
          loose: true,
        })
      })
      y += BOX_H + GAP_X
    }
    y += PAD - GAP_X
  } else if (placed.length) {
    y = y - GAP_Y + PAD
  }

  const right = placed.reduce((most, p) => Math.max(most, p.x + BOX_W), 0)
  return {
    placed,
    divider,
    width: Math.max(width, right + PAD),
    height: Math.max(220, y),
  }
}

/**
 * Where a line should leave one box and enter another.
 *
 * Chosen from where the boxes actually are. Every edge used to run from the
 * bottom of one card to the top of the other, so two boxes side by side were
 * joined by a curve that dived below them both and came back up - through
 * whatever else was in the way.
 */
function anchors(from: Placed & Offset, to: Placed & Offset) {
  const fromMidY = from.y + BOX_H / 2
  const toMidY = to.y + BOX_H / 2
  const vertical = Math.abs(toMidY - fromMidY) > BOX_H

  if (vertical) {
    const down = toMidY > fromMidY
    const y1 = down ? from.y + BOX_H : from.y
    const y2 = down ? to.y : to.y + BOX_H
    const x1 = from.x + BOX_W / 2
    const x2 = to.x + BOX_W / 2
    const bend = Math.max(24, Math.abs(y2 - y1) / 2)
    return {
      d: `M ${x1} ${y1} C ${x1} ${y1 + (down ? bend : -bend)}, ${x2} ${y2 - (down ? bend : -bend)}, ${x2} ${y2}`,
      mx: (x1 + x2) / 2,
      my: (y1 + y2) / 2,
    }
  }

  const right = to.x > from.x
  const x1 = right ? from.x + BOX_W : from.x
  const x2 = right ? to.x : to.x + BOX_W
  const bend = Math.max(24, Math.abs(x2 - x1) / 2)
  return {
    d: `M ${x1} ${fromMidY} C ${x1 + (right ? bend : -bend)} ${fromMidY}, ${x2 - (right ? bend : -bend)} ${toMidY}, ${x2} ${toMidY}`,
    mx: (x1 + x2) / 2,
    my: (fromMidY + toMidY) / 2,
  }
}

export default function RelationshipMap({
  datasets,
  relationships,
  selectedId,
  storageKey,
  projectName = '',
  onSelect,
}: {
  datasets: Dataset[]
  relationships: Relationship[]
  selectedId: string | null
  /** Where this project's arrangement is remembered, per browser. */
  storageKey?: string
  /** Dropped from the front of every box, since the page already says it. */
  projectName?: string
  onSelect: (relationship: Relationship | null) => void
}) {
  const viewport = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(900)
  const [zoom, setZoom] = useState(1)
  const [expanded, setExpanded] = useState(false)
  // Whether the reader has set the zoom themselves. Until they have, the
  // diagram fits itself to the room it has; afterwards it stays where they put
  // it, because a view that keeps overriding you is worse than one that never
  // helped.
  const chosen = useRef(false)

  const memory = storageKey ? `susodash.relationship-layout.${storageKey}` : ''
  const [offsets, setOffsets] = useState<Record<string, Offset>>(() => {
    if (!memory) return {}
    try {
      return JSON.parse(localStorage.getItem(memory) || '{}')
    } catch {
      // A browser with site data blocked, or something else's key. Neither is
      // a reason to fail to draw the diagram.
      return {}
    }
  })

  const remember = useCallback(
    (next: Record<string, Offset>) => {
      setOffsets(next)
      if (!memory) return
      try {
        localStorage.setItem(memory, JSON.stringify(next))
      } catch {
        // Private windows and blocked site data both throw. The arrangement
        // still works for this visit; it just will not be here next time.
      }
    },
    [memory],
  )

  useEffect(() => {
    const measure = () => {
      if (viewport.current) setWidth(viewport.current.clientWidth)
    }
    measure()
    const observer = new ResizeObserver(measure)
    if (viewport.current) observer.observe(viewport.current)
    return () => observer.disconnect()
  }, [expanded])

  // Escape leaves the expanded view, which is where a reader's hand goes.
  useEffect(() => {
    if (!expanded) return
    const leave = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', leave)
    return () => window.removeEventListener('keydown', leave)
  }, [expanded])

  const layout = useMemo(
    () => layoutOf(datasets, relationships, width / zoom),
    [datasets, relationships, width, zoom],
  )

  const at = useMemo(() => {
    const found = new Map<string, Placed & Offset>()
    for (const p of layout.placed) {
      const shift = offsets[p.dataset.id] ?? { x: 0, y: 0 }
      found.set(p.dataset.id, { ...p, x: p.x + shift.x, y: p.y + shift.y })
    }
    return found
  }, [layout, offsets])

  const drag = useRef<{ id: string; x: number; y: number; from: Offset } | null>(null)

  const startDrag = (id: string) => (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = {
      id,
      x: event.clientX,
      y: event.clientY,
      from: offsets[id] ?? { x: 0, y: 0 },
    }
  }

  const onDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const active = drag.current
    if (!active) return
    const home = layout.placed.find((p) => p.dataset.id === active.id)
    if (!home) return
    // Divided by the zoom, or a box dragged on a shrunken diagram ran away
    // from the pointer - the cursor moves in screen pixels and the box lives
    // in diagram ones.
    const wanted = {
      x: active.from.x + (event.clientX - active.x) / zoom,
      y: active.from.y + (event.clientY - active.y) / zoom,
    }
    // Held on the canvas. Dragged freely a box went off the edge of the
    // diagram, where the only thing that could reach it was a scrollbar that
    // does not go that far - so it could not be dragged back.
    const clamp = (value: number, low: number, high: number) =>
      Math.min(Math.max(value, low), high)
    setOffsets((current) => ({
      ...current,
      [active.id]: {
        x: clamp(wanted.x, -home.x, layout.width - BOX_W - home.x),
        y: clamp(wanted.y, -home.y, layout.height - BOX_H - home.y),
      },
    }))
  }

  const endDrag = () => {
    if (!drag.current) return
    drag.current = null
    // Written once the box is let go rather than on every pixel of the drag.
    setOffsets((current) => {
      if (memory) {
        try {
          localStorage.setItem(memory, JSON.stringify(current))
        } catch {
          /* see remember() */
        }
      }
      return current
    })
  }

  const moved = Object.values(offsets).some((o) => o.x !== 0 || o.y !== 0)
  const loose = layout.placed.filter((p) => p.loose)

  const scaleToFit = useCallback(() => {
    const room = viewport.current
    if (!room || !room.clientHeight) return null
    const raw = layoutOf(datasets, relationships, room.clientWidth)
    // Never above 1: a diagram blown up past the size its boxes were drawn at
    // is not easier to read, only bigger.
    const scale = Math.min(
      1,
      room.clientWidth / Math.max(1, raw.width),
      room.clientHeight / Math.max(1, raw.height),
    )
    return Math.max(ZOOM_MIN, Math.round(scale * 20) / 20)
  }, [datasets, relationships])

  const fit = useCallback(() => {
    const scale = scaleToFit()
    if (scale === null) return
    chosen.current = true
    setZoom(scale)
  }, [scaleToFit])

  /*
   * Show the whole model to begin with.
   *
   * A census has a dozen tables, and at full size that is three times the
   * height of the panel - so what the page opened on was the top third of a
   * diagram, with the rest of it below a scroll nobody had a reason to expect.
   * Fitting it means the shape is the first thing seen, and the reader zooms in
   * on the part they care about rather than hunting for the part they can see.
   */
  useEffect(() => {
    if (chosen.current) return
    const scale = scaleToFit()
    if (scale !== null) setZoom(scale)
  }, [scaleToFit, expanded, width])

  /** The project's own name, dropped from the front of a box. */
  const short = (name: string) => {
    const prefix = projectName.trim()
    if (!prefix || name.length <= prefix.length + 1) return name
    return name.toLowerCase().startsWith(prefix.toLowerCase())
      ? name.slice(prefix.length).replace(/^[\s_:-]+/, '') || name
      : name
  }

  const canvas = (
    <div
      ref={viewport}
      className={`relative overflow-auto rounded-card border border-ink-200 bg-ink-50/40 dark:border-dark-200 dark:bg-dark-100/40 ${
        expanded ? 'h-[calc(100vh-9rem)]' : 'h-[26rem]'
      }`}
    >
      <div
        className="relative origin-top-left"
        style={{
          width: layout.width,
          height: layout.height,
          transform: `scale(${zoom})`,
          // The scrollable area has to be the scaled size, not the drawn one,
          // or half the diagram sits outside anything that can reach it.
          marginBottom: layout.height * (zoom - 1),
          marginRight: layout.width * (zoom - 1),
        }}
      >
        <svg
          className="pointer-events-none absolute inset-0"
          width={layout.width}
          height={layout.height}
          aria-hidden
        >
          {layout.divider > 0 && (
            <line
              x1={PAD}
              y1={layout.divider}
              x2={layout.width - PAD}
              y2={layout.divider}
              stroke="currentColor"
              className="text-ink-200 dark:text-dark-300"
              strokeWidth={1}
              strokeDasharray="5 5"
            />
          )}
          {relationships.map((link) => {
            const from = at.get(link.left_dataset_id)
            const to = at.get(link.right_dataset_id)
            if (!from || !to) return null
            const { d, mx, my } = anchors(from, to)
            const selected = link.id === selectedId
            const label = CARDINALITY_LABEL[link.cardinality]
            return (
              <g key={link.id}>
                <path
                  d={d}
                  fill="none"
                  stroke={!link.is_active ? '#c3c2bf' : selected ? '#2563eb' : '#8a8986'}
                  strokeWidth={selected ? 2.5 : 1.5}
                  strokeDasharray={link.is_active ? undefined : '4 3'}
                />
                {/* On a tile of its own. Set straight on the line the label was
                    unreadable wherever the two crossed, which with a dozen
                    tables is most places. */}
                <rect
                  x={mx - label.length * 3.4 - 5}
                  y={my - 8}
                  width={label.length * 6.8 + 10}
                  height={16}
                  rx={8}
                  className="fill-white stroke-ink-200 dark:fill-dark-100 dark:stroke-dark-300"
                  strokeWidth={1}
                />
                <text
                  x={mx}
                  y={my + 4}
                  textAnchor="middle"
                  className={
                    selected
                      ? 'fill-brand-700 dark:fill-brand-300'
                      : 'fill-ink-600 dark:fill-dark-600'
                  }
                  style={{ fontSize: 10, fontVariantNumeric: 'tabular-nums' }}
                >
                  {label}
                </text>
              </g>
            )
          })}
        </svg>

        {layout.placed.map((p) => {
          const here = at.get(p.dataset.id)!
          const touches = relationships.some(
            (r) =>
              r.id === selectedId &&
              (r.left_dataset_id === p.dataset.id || r.right_dataset_id === p.dataset.id),
          )
          return (
            <div
              key={p.dataset.id}
              title={p.dataset.name}
              className={`absolute touch-none cursor-grab select-none overflow-hidden rounded-card border px-3 py-2 shadow-sm transition-colors active:cursor-grabbing ${
                touches
                  ? 'border-brand-400 bg-brand-50 ring-1 ring-brand-300 dark:border-brand-500/60 dark:bg-brand-500/15 dark:ring-brand-500/40'
                  : p.loose
                    ? 'border-dashed border-ink-300 bg-white/70 dark:border-dark-300 dark:bg-dark-100/70'
                    : p.tier === 0
                      ? 'border-brand-300 bg-brand-50 dark:border-brand-500/50 dark:bg-brand-500/10'
                      : 'border-ink-200 bg-white dark:border-dark-200 dark:bg-dark-100'
              }`}
              style={{ left: here.x, top: here.y, width: BOX_W, height: BOX_H }}
              onPointerDown={startDrag(p.dataset.id)}
              onPointerMove={onDrag}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
            >
              <p className="truncate text-sm font-medium text-ink-900 dark:text-dark-900">
                {short(p.dataset.name)}
              </p>
              <p className="text-[11px] text-ink-500 dark:text-dark-500">
                {p.dataset.row_count.toLocaleString()} rows · {p.dataset.column_count} cols
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )

  const controls = (
    <div className="mb-2 flex flex-wrap items-center gap-1.5">
      <button
        className="btn-ghost btn-sm font-mono text-base leading-none"
        onClick={() => {
          chosen.current = true
          setZoom((z) => Math.max(ZOOM_MIN, Math.round((z - 0.1) * 20) / 20))
        }}
        disabled={zoom <= ZOOM_MIN}
        title="Zoom out"
        aria-label="Zoom out"
      >
        -
      </button>
      <span className="w-12 text-center text-xs tabular-nums text-ink-500">
        {Math.round(zoom * 100)}%
      </span>
      <button
        className="btn-ghost btn-sm font-mono text-base leading-none"
        onClick={() => {
          chosen.current = true
          setZoom((z) => Math.min(ZOOM_MAX, Math.round((z + 0.1) * 20) / 20))
        }}
        disabled={zoom >= ZOOM_MAX}
        title="Zoom in"
        aria-label="Zoom in"
      >
        +
      </button>
      <button className="btn-ghost btn-sm text-ink-600" onClick={fit}>
        Fit
      </button>
      {moved && (
        <button className="btn-ghost btn-sm text-ink-600" onClick={() => remember({})}>
          Tidy up
        </button>
      )}
      <button
        className="btn-ghost btn-sm ml-auto text-ink-600"
        onClick={() => setExpanded((open) => !open)}
      >
        {expanded ? 'Close' : 'Expand'}
      </button>
    </div>
  )

  return (
    <div>
      {expanded ? (
        <div className="fixed inset-0 z-50 flex flex-col bg-white p-4 dark:bg-dark-50">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-ink-900 dark:text-dark-900">
                Data model
              </p>
              <p className="text-xs text-ink-500">
                {projectName || 'How this project’s datasets link to each other'}
              </p>
            </div>
          </div>
          {controls}
          {canvas}
        </div>
      ) : (
        <>
          {controls}
          {canvas}
        </>
      )}

      {loose.length > 0 && !expanded && (
        <p className="mt-1.5 text-center text-xs text-ink-400">
          {loose.length} dataset{loose.length === 1 ? '' : 's'} below the line
          {loose.length === 1 ? ' has' : ' have'} no relationship yet
        </p>
      )}

      {relationships.length > 0 && !expanded && (
        <ul className="mt-4 space-y-1.5">
          {relationships.map((link) => (
            <li key={link.id}>
              <button
                onClick={() => onSelect(link.id === selectedId ? null : link)}
                className={`flex w-full flex-wrap items-center gap-2 rounded-card border px-3 py-2 text-left text-sm transition-colors ${
                  link.id === selectedId
                    ? 'border-brand-400 bg-brand-50'
                    : 'border-ink-200 hover:bg-ink-50'
                }`}
              >
                <span className="font-medium text-ink-800">{short(link.left_name)}</span>
                <span className="font-mono text-xs text-ink-500">
                  {CARDINALITY_LABEL[link.cardinality]}
                </span>
                <span className="font-medium text-ink-800">{short(link.right_name)}</span>
                <span className="text-xs text-ink-500">
                  on <code className="text-[11px]">{link.left_variable}</code>
                </span>
                <span className="ml-auto flex items-center gap-1.5">
                  {/* Said on the row as well as in the panel: a converted key
                      changes which rows a merge joins, and a setting that only
                      shows once a link is selected is a setting nobody finds
                      again when a total comes out wrong. */}
                  {link.key_match !== 'exact' && (
                    <Badge tone="neutral">
                      keys as {link.key_match === 'text' ? 'text' : 'numbers'}
                    </Badge>
                  )}
                  {link.detected && <Badge tone="neutral">detected</Badge>}
                  {!link.is_active && <Badge tone="warning">off</Badge>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
