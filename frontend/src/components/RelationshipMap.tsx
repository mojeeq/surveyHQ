import { useMemo, useRef, useState, useEffect } from 'react'
import type { Cardinality, Dataset, Relationship } from '@/lib/types'
import { Badge } from './ui'

/**
 * The datasets in a project and the links between them.
 *
 * Laid out automatically to begin with: a survey export has a shape - one
 * interview table with rosters hanging off it - and computing that shape from
 * the cardinalities puts every dataset somewhere sensible without anyone
 * arranging boxes. Tables that nothing links to sit apart, which is the useful
 * signal that a merge is not yet possible.
 *
 * But an automatic layout only knows the cardinalities, not which links you are
 * trying to read, and with a dozen tables the lines cross each other. So a box
 * can be dragged, and where it is put is remembered. The arrangement is a way
 * of looking at the project rather than part of it, so it lives in this
 * browser rather than on the server: it is per person, and "Tidy up" puts
 * everything back.
 *
 * Links are drawn as SVG between the measured card positions, so the lines stay
 * attached when the container is resized, the list changes, or a box is moved.
 */

const CARDINALITY_LABEL: Record<Cardinality, string> = {
  one_to_one: '1 — 1',
  one_to_many: '1 — ∗',
  many_to_one: '∗ — 1',
  many_to_many: '∗ — ∗',
}

interface Point {
  x: number
  y: number
  w: number
  h: number
}

interface Offset {
  x: number
  y: number
}

/** The room the diagram gets. Tall enough to arrange a survey's tables in. */
const CANVAS_HEIGHT = 360

export default function RelationshipMap({
  datasets,
  relationships,
  selectedId,
  storageKey,
  onSelect,
}: {
  datasets: Dataset[]
  relationships: Relationship[]
  selectedId: string | null
  /** Where this project's arrangement is remembered, per browser. */
  storageKey?: string
  onSelect: (relationship: Relationship | null) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const cards = useRef(new Map<string, HTMLDivElement>())
  const [boxes, setBoxes] = useState<Record<string, Point>>({})

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

  const remember = (next: Record<string, Offset>) => {
    setOffsets(next)
    if (!memory) return
    try {
      localStorage.setItem(memory, JSON.stringify(next))
    } catch {
      // Private windows and blocked site data both throw. The arrangement
      // still works for this visit; it just will not be here next time.
    }
  }

  const drag = useRef<{
    id: string
    pointerX: number
    pointerY: number
    from: Offset
  } | null>(null)

  const startDrag = (id: string) => (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = {
      id,
      pointerX: event.clientX,
      pointerY: event.clientY,
      from: offsets[id] ?? { x: 0, y: 0 },
    }
  }

  const onDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const active = drag.current
    if (!active) return
    setOffsets((current) => {
      const wanted = {
        x: active.from.x + event.clientX - active.pointerX,
        y: active.from.y + event.clientY - active.pointerY,
      }
      // Keep the box on the canvas. Dragged freely it went straight out of the
      // diagram and sat on top of the relationship list underneath, which is
      // not an arrangement anybody wants and cannot be undone by dragging it
      // back once it is behind something else.
      const measured = boxes[active.id]
      const canvas = container.current
      if (!measured || !canvas) return { ...current, [active.id]: wanted }
      const here = current[active.id] ?? { x: 0, y: 0 }
      const baseX = measured.x - here.x
      const baseY = measured.y - here.y
      const limit = canvas.getBoundingClientRect()
      const clamp = (value: number, low: number, high: number) =>
        Math.min(Math.max(value, low), high)
      return {
        ...current,
        [active.id]: {
          x: clamp(wanted.x, -baseX, limit.width - measured.w - baseX),
          y: clamp(wanted.y, -baseY, CANVAS_HEIGHT - measured.h - baseY),
        },
      }
    })
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

  // Datasets on the "one" side of a link are parents; everything else hangs
  // off them. This is what gives the diagram its shape.
  const { parents, children, loose } = useMemo(() => {
    const isParent = new Set<string>()
    const isChild = new Set<string>()
    for (const link of relationships) {
      if (link.cardinality === 'one_to_many') {
        isParent.add(link.left_dataset_id)
        isChild.add(link.right_dataset_id)
      } else if (link.cardinality === 'many_to_one') {
        isParent.add(link.right_dataset_id)
        isChild.add(link.left_dataset_id)
      }
    }
    const linked = new Set(
      relationships.flatMap((r) => [r.left_dataset_id, r.right_dataset_id]),
    )
    return {
      parents: datasets.filter((d) => isParent.has(d.id)),
      children: datasets.filter((d) => isChild.has(d.id) && !isParent.has(d.id)),
      loose: datasets.filter((d) => !linked.has(d.id)),
    }
  }, [datasets, relationships])

  // Measure after layout so the lines join the cards where they actually are.
  useEffect(() => {
    const measure = () => {
      const root = container.current
      if (!root) return
      const origin = root.getBoundingClientRect()
      const next: Record<string, Point> = {}
      cards.current.forEach((element, id) => {
        const box = element.getBoundingClientRect()
        next[id] = {
          x: box.left - origin.left,
          y: box.top - origin.top,
          w: box.width,
          h: box.height,
        }
      })
      setBoxes(next)
    }
    measure()
    const observer = new ResizeObserver(measure)
    if (container.current) observer.observe(container.current)
    window.addEventListener('resize', measure)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', measure)
    }
    // offsets is in the dependency list so a dragged box takes its lines with
    // it; without that the card moved and the curve stayed behind.
  }, [datasets, relationships, offsets])

  const card = (dataset: Dataset, tone: string) => (
    <div
      key={dataset.id}
      ref={(element) => {
        if (element) cards.current.set(dataset.id, element)
        else cards.current.delete(dataset.id)
      }}
      className={`touch-none cursor-grab select-none rounded-card border px-3 py-2 shadow-sm active:cursor-grabbing ${tone}`}
      style={
        offsets[dataset.id]
          ? {
              transform: `translate(${offsets[dataset.id].x}px, ${offsets[dataset.id].y}px)`,
            }
          : undefined
      }
      onPointerDown={startDrag(dataset.id)}
      onPointerMove={onDrag}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      <p className="text-sm font-medium text-ink-900">{dataset.name}</p>
      <p className="text-[11px] text-ink-500">
        {dataset.row_count.toLocaleString()} rows · {dataset.column_count} cols
      </p>
    </div>
  )

  return (
    <div>
      {/* The canvas is its own box so a dragged card is clipped to the diagram
          rather than escaping over the list of relationships underneath. */}
      <div
        ref={container}
        className="relative overflow-hidden"
        style={{ minHeight: CANVAS_HEIGHT }}
      >
      <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
        {relationships.map((link) => {
          const from = boxes[link.left_dataset_id]
          const to = boxes[link.right_dataset_id]
          if (!from || !to) return null
          const x1 = from.x + from.w / 2
          const y1 = from.y + from.h
          const x2 = to.x + to.w / 2
          const y2 = to.y
          const mid = (y1 + y2) / 2
          const selected = link.id === selectedId
          return (
            <g key={link.id}>
              <path
                d={`M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`}
                fill="none"
                stroke={
                  !link.is_active ? '#c3c2bf' : selected ? '#2563eb' : '#8a8986'
                }
                strokeWidth={selected ? 2.5 : 1.5}
                strokeDasharray={link.is_active ? undefined : '4 3'}
              />
              <text
                x={(x1 + x2) / 2}
                y={mid}
                textAnchor="middle"
                className="fill-ink-500"
                style={{ fontSize: 10 }}
              >
                {CARDINALITY_LABEL[link.cardinality]}
              </text>
            </g>
          )
        })}
      </svg>

      <div
        className="relative flex min-w-max flex-col items-center gap-10 py-4"
        style={{ minHeight: CANVAS_HEIGHT }}
      >
        <div className="flex flex-wrap justify-center gap-4">
          {parents.map((d) => card(d, 'border-brand-300 bg-brand-50'))}
        </div>
        {children.length > 0 && (
          <div className="flex flex-wrap justify-center gap-4">
            {children.map((d) => card(d, 'border-ink-200 bg-white'))}
          </div>
        )}
        {loose.length > 0 && (
          <div className="flex flex-wrap justify-center gap-4 border-t border-dashed border-ink-200 pt-6">
            {loose.map((d) => card(d, 'border-ink-200 bg-ink-50'))}
          </div>
        )}
      </div>
      </div>

      {moved && (
        <div className="mt-1 text-center">
          <button className="btn-ghost btn-sm text-ink-500" onClick={() => remember({})}>
            Tidy up
          </button>
        </div>
      )}

      {loose.length > 0 && (
        <p className="mt-1 text-center text-xs text-ink-400">
          {loose.length} dataset{loose.length === 1 ? '' : 's'} below the line
          {loose.length === 1 ? ' has' : ' have'} no relationship yet
        </p>
      )}

      {relationships.length > 0 && (
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
                <span className="font-medium text-ink-800">{link.left_name}</span>
                <span className="font-mono text-xs text-ink-500">
                  {CARDINALITY_LABEL[link.cardinality]}
                </span>
                <span className="font-medium text-ink-800">{link.right_name}</span>
                <span className="text-xs text-ink-500">
                  on <code className="text-[11px]">{link.left_variable}</code>
                </span>
                <span className="ml-auto flex items-center gap-1.5">
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
