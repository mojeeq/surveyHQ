/**
 * Named boxes drawn behind the widgets that belong to them.
 *
 * A page answers "which board am I on". A group answers "what are these four
 * tiles for" - and lets them be moved and folded away as the one thing they
 * already were in the reader's head.
 *
 * The title bar is an ordinary grid item, so dragging, resizing and collision
 * are react-grid-layout's rather than a second implementation of them living
 * here. What this file adds is the frame: a rectangle around the bar and every
 * member, computed with the same arithmetic the grid places items by, and
 * drawn behind them.
 */

import { useEffect, useRef, useState } from 'react'
import type { Layout } from 'react-grid-layout'

import type { Widget, WidgetGroup } from '@/lib/types'

/** The prefix that tells a group's grid item from a widget's. */
export const GROUP_PREFIX = 'group:'

/** Height of a title bar, in grid rows. */
export const GROUP_BAR_ROWS = 1

/** How far outside its contents the frame is drawn, in pixels. */
const FRAME_INSET = 10

export function isGroupItem(id: string): boolean {
  return id.startsWith(GROUP_PREFIX)
}

export function groupIdOf(itemId: string): string {
  return itemId.slice(GROUP_PREFIX.length)
}

export function groupItemId(group: WidgetGroup): string {
  return `${GROUP_PREFIX}${group.id}`
}

/** A widget's layout with every field filled in. */
export type Box = { x: number; y: number; w: number; h: number }

export function boxOf(widget: Widget, fallback: Box): Box {
  return {
    x: Number(widget.layout?.x ?? fallback.x),
    y: Number(widget.layout?.y ?? fallback.y),
    w: Number(widget.layout?.w ?? fallback.w),
    h: Number(widget.layout?.h ?? fallback.h),
  }
}

/**
 * Where react-grid-layout puts an item, in pixels.
 *
 * This is its own arithmetic, repeated rather than imported because it is not
 * exported. If the two ever disagree the frame drifts away from the widgets it
 * is meant to be around, so it is written once here and used for every edge.
 */
export function pixels(
  box: Box,
  { columns, rowHeight, canvasWidth, margin, padding }: Grid,
): { left: number; top: number; width: number; height: number } {
  const colWidth =
    (canvasWidth - padding * 2 - margin * (columns - 1)) / columns
  return {
    left: Math.round(box.x * (colWidth + margin)) + padding,
    top: Math.round(box.y * (rowHeight + margin)) + padding,
    width: Math.round(box.w * colWidth + Math.max(0, box.w - 1) * margin),
    height: Math.round(box.h * rowHeight + Math.max(0, box.h - 1) * margin),
  }
}

export type Grid = {
  columns: number
  rowHeight: number
  canvasWidth: number
  margin: number
  padding: number
}

/** The smallest box holding all of these. */
export function bounding(boxes: Box[]): Box | null {
  if (!boxes.length) return null
  const left = Math.min(...boxes.map((b) => b.x))
  const top = Math.min(...boxes.map((b) => b.y))
  const right = Math.max(...boxes.map((b) => b.x + b.w))
  const bottom = Math.max(...boxes.map((b) => b.y + b.h))
  return { x: left, y: top, w: right - left, h: bottom - top }
}

/**
 * The frames, behind the grid.
 *
 * Drawn from the laid-out positions rather than the saved ones: while a widget
 * is being dragged the grid has moved everything around it, and a frame drawn
 * from what is stored would sit where the group used to be until the mouse
 * came up.
 */
export function GroupFrames({
  groups,
  layout,
  membersOf,
  grid,
  tone,
}: {
  groups: WidgetGroup[]
  /** The live layout, group bars included. */
  layout: Layout[]
  /** The widget ids in each group, by group id. */
  membersOf: (groupId: string) => string[]
  grid: Grid
  /** The board's ink, for a group that has chosen no colour of its own. */
  tone?: string
}) {
  const at = new Map(layout.map((item) => [item.i, item]))
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden="true">
      {groups.map((group) => {
        const bar = at.get(groupItemId(group))
        if (!bar) return null
        // A collapsed group is its bar and nothing else, and the bar draws its
        // own edge - a frame around it would be a second border on one line.
        if (group.collapsed) return null
        const members = membersOf(group.id)
          .map((id) => at.get(id))
          .filter((item): item is Layout => Boolean(item))
        const box = bounding([bar, ...members].map(({ x, y, w, h }) => ({ x, y, w, h })))
        if (!box) return null
        const { left, top, width, height } = pixels(box, grid)
        return (
          <div
            key={group.id}
            className="absolute rounded-control border-2 border-dashed transition-all duration-150"
            style={{
              left: left - FRAME_INSET,
              top: top - FRAME_INSET,
              width: width + FRAME_INSET * 2,
              height: height + FRAME_INSET * 2,
              borderColor: group.color || tone || 'rgb(148 163 184 / 0.7)',
              backgroundColor: 'rgb(148 163 184 / 0.07)',
            }}
          />
        )
      })}
    </div>
  )
}

/**
 * A group's title bar: the thing you drag, name, fold and delete.
 *
 * `widget-handle` is the class the grid is told to drag by, so the bar behaves
 * like a widget's own title bar and the buttons on it stay clickable.
 */
export function GroupBar({
  group,
  count,
  editing,
  onRename,
  onToggle,
  onRemove,
}: {
  group: WidgetGroup
  /** How many widgets are in it, which is all a collapsed group can show. */
  count: number
  editing: boolean
  onRename: (name: string) => void
  onToggle: () => void
  onRemove: () => void
}) {
  const [naming, setNaming] = useState(false)
  const [draft, setDraft] = useState(group.name)
  const field = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setDraft(group.name)
  }, [group.name])

  useEffect(() => {
    if (naming) field.current?.select()
  }, [naming])

  const commit = () => {
    setNaming(false)
    const next = draft.trim()
    if (next && next !== group.name) onRename(next)
    else setDraft(group.name)
  }

  const ink = group.color || undefined
  return (
    <div
      className={`flex h-full items-center gap-2 rounded-control px-2 ${
        editing ? 'widget-handle cursor-move' : ''
      }`}
      style={{ color: ink }}
    >
      <button
        type="button"
        // Not a drag handle: a click here folds the group rather than moving
        // it, and the grid would otherwise start a drag from the same press.
        onMouseDown={(event) => event.stopPropagation()}
        onTouchStart={(event) => event.stopPropagation()}
        onClick={onToggle}
        className="shrink-0 text-xs leading-none opacity-70 hover:opacity-100"
        aria-label={group.collapsed ? `Open "${group.name}"` : `Fold "${group.name}"`}
        title={group.collapsed ? 'Open this group' : 'Fold this group'}
      >
        {group.collapsed ? '▶' : '▼'}
      </button>

      {naming ? (
        <input
          ref={field}
          className="input h-6 min-w-0 flex-1 py-0 text-xs"
          value={draft}
          onMouseDown={(event) => event.stopPropagation()}
          onTouchStart={(event) => event.stopPropagation()}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === 'Enter') commit()
            if (event.key === 'Escape') {
              setDraft(group.name)
              setNaming(false)
            }
          }}
        />
      ) : (
        <span
          className="min-w-0 flex-1 truncate text-xs font-semibold uppercase tracking-wide"
          title={group.name}
        >
          {group.name}
        </span>
      )}

      {group.collapsed && (
        <span className="shrink-0 text-xs opacity-60">
          {count} {count === 1 ? 'widget' : 'widgets'}
        </span>
      )}

      {editing && !naming && (
        <>
          <button
            type="button"
            onMouseDown={(event) => event.stopPropagation()}
            onTouchStart={(event) => event.stopPropagation()}
            onClick={() => setNaming(true)}
            className="shrink-0 text-xs opacity-60 hover:opacity-100"
            aria-label={`Rename "${group.name}"`}
            title="Rename"
          >
            ✎
          </button>
          <button
            type="button"
            onMouseDown={(event) => event.stopPropagation()}
            onTouchStart={(event) => event.stopPropagation()}
            onClick={onRemove}
            className="shrink-0 text-xs opacity-60 hover:opacity-100"
            aria-label={`Remove the group "${group.name}"`}
            title="Remove this group, keeping its widgets"
          >
            ✕
          </button>
        </>
      )}
    </div>
  )
}
