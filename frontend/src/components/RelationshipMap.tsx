import { useMemo, useRef, useState, useEffect } from 'react'
import type { Cardinality, Dataset, Relationship } from '@/lib/types'
import { Badge } from './ui'

/**
 * The datasets in a project and the links between them.
 *
 * Laid out rather than dragged: a survey export has a shape - one interview
 * table with rosters hanging off it - and computing that shape from the
 * cardinalities puts every dataset where it belongs without anyone arranging
 * boxes. Tables that nothing links to sit apart, which is the useful signal
 * that a merge is not yet possible.
 *
 * Links are drawn as SVG between the measured card positions, so the lines stay
 * attached when the container is resized or the list changes.
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

export default function RelationshipMap({
  datasets,
  relationships,
  selectedId,
  onSelect,
}: {
  datasets: Dataset[]
  relationships: Relationship[]
  selectedId: string | null
  onSelect: (relationship: Relationship | null) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const cards = useRef(new Map<string, HTMLDivElement>())
  const [boxes, setBoxes] = useState<Record<string, Point>>({})

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
  }, [datasets, relationships])

  const card = (dataset: Dataset, tone: string) => (
    <div
      key={dataset.id}
      ref={(element) => {
        if (element) cards.current.set(dataset.id, element)
        else cards.current.delete(dataset.id)
      }}
      className={`rounded-card border px-3 py-2 shadow-sm ${tone}`}
    >
      <p className="text-sm font-medium text-ink-900">{dataset.name}</p>
      <p className="text-[11px] text-ink-500">
        {dataset.row_count.toLocaleString()} rows · {dataset.column_count} cols
      </p>
    </div>
  )

  return (
    <div ref={container} className="relative overflow-x-auto">
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

      <div className="relative flex min-w-max flex-col items-center gap-10 py-4">
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
