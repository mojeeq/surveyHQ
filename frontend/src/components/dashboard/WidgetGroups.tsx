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
 *
 * The frame is drawn on the grid's own lines, and the widgets are moved in
 * from it instead. A frame drawn outside its widgets reached into the gutter
 * between cells - which is all the room there is between one cell and the
 * next - so two groups side by side met in the middle of it, and a widget
 * beside a group sat closer to it than to any other widget. On the grid's
 * lines, a group is as far from its neighbours as a widget is from its own.
 */

import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import type { Layout } from 'react-grid-layout'

import ColorPicker from '@/components/ColorPicker'
import { Field, Modal } from '@/components/ui'
import { isDark } from '@/lib/colour'
import type { Widget, WidgetGroup } from '@/lib/types'

/** The prefix that tells a group's grid item from a widget's. */
export const GROUP_PREFIX = 'group:'

/** Height of a title bar, in grid rows. */
export const GROUP_BAR_ROWS = 1

/** How far a group's widgets sit in from its frame, in pixels. */
export const GROUP_INSET = 10

/** How wide the frame's line is: the bar sits inside it, not over it. */
export const GROUP_LINE = 2

/** A group's heading when nobody has sized it: text-xs. */
export const DEFAULT_GROUP_TITLE = 12

/** The wash behind a group that has chosen no ground: the frame, and its bar. */
const FRAME_WASH = 'rgb(148 163 184 / 0.07)'
const BAR_WASH = 'rgb(148 163 184 / 0.12)'

/** The ground a group's frame is painted with. */
export function groupGround(group: WidgetGroup): string {
  return group.background || FRAME_WASH
}

/** The ground of a group's title bar: its own colour, or a shade more wash. */
export function groupBarGround(group: WidgetGroup): string {
  return group.background || BAR_WASH
}

/** The frame's line: the group's colour, or the board's ink, or a quiet slate. */
export function frameInk(group: WidgetGroup, tone?: string): string {
  return group.color || tone || 'rgb(148 163 184 / 0.7)'
}

/**
 * The heading's ink. A colour chosen for it wins; on a ground somebody painted
 * dark it is light without being asked, since dark-on-navy is no heading.
 */
export function groupInk(group: WidgetGroup): string | undefined {
  if (group.color) return group.color
  return isDark(group.background) ? '#f4f5f7' : undefined
}

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

/** Which sides of a widget face its group's frame, and so are moved in from it. */
export type Inset = { left: boolean; right: boolean; bottom: boolean }

/**
 * The sides of each grouped widget that lie on its group's frame.
 *
 * The frame is the box round the bar and every member, so a widget on its
 * left edge, its right edge or its foot has the frame's line on that side and
 * is moved in from it by `GROUP_INSET`. Nothing is moved in at the top: the
 * bar is above every member, with the grid's own gutter between them. A side
 * inside the group stays where the grid put it, so two widgets in a group
 * are as far apart as any two widgets on the board.
 *
 * A folded group has no frame and its widgets are not shown, so it moves
 * nothing. Read from the laid-out positions, as the frames are, so a widget
 * being dragged keeps in step with the frame drawn round it.
 */
export function insets(
  groups: WidgetGroup[],
  layout: Layout[],
  membersOf: (groupId: string) => string[],
): Map<string, Inset> {
  const at = new Map(layout.map((item) => [item.i, item]))
  const found = new Map<string, Inset>()
  for (const group of groups) {
    if (group.collapsed) continue
    const bar = at.get(groupItemId(group))
    if (!bar) continue
    const members = membersOf(group.id)
      .map((id) => at.get(id))
      .filter((item): item is Layout => Boolean(item))
    const box = bounding([bar, ...members].map(({ x, y, w, h }) => ({ x, y, w, h })))
    if (!box) continue
    for (const item of members) {
      found.set(item.i, {
        left: item.x === box.x,
        right: item.x + item.w === box.x + box.w,
        bottom: item.y + item.h === box.y + box.h,
      })
    }
  }
  return found
}

/** The padding that moves a widget in from its group's frame. */
export function insetPadding(inset: Inset | undefined): CSSProperties | undefined {
  if (!inset) return undefined
  return {
    paddingLeft: inset.left ? GROUP_INSET : 0,
    paddingRight: inset.right ? GROUP_INSET : 0,
    paddingBottom: inset.bottom ? GROUP_INSET : 0,
  }
}

/**
 * How a group's bar is drawn: the cell the grid places, and the strip in it.
 *
 * An open group's bar is the frame's top row, so it sits just inside the
 * frame's line rather than over it, with a dashed rule under it - one outline
 * round the group, not a second box drawn on top of the first. A folded group
 * has no frame, and its bar is a box of its own.
 */
export function barStyles(
  group: WidgetGroup,
  tone?: string,
): { cell: CSSProperties; strip: CSSProperties } {
  const ink = frameInk(group, tone)
  if (group.collapsed) {
    return {
      cell: {},
      strip: { border: `1px dashed ${ink}`, backgroundColor: groupBarGround(group) },
    }
  }
  return {
    cell: { padding: `${GROUP_LINE}px ${GROUP_LINE}px 0` },
    strip: { borderBottom: `1px dashed ${ink}`, backgroundColor: groupBarGround(group) },
  }
}

export type Grid = {
  columns: number
  rowHeight: number
  canvasWidth: number
  margin: number
  padding: number
}

/**
 * Where each group's bar goes, so that it is drawn above its members.
 *
 * The grid packs its items upwards in order of their stored rows, the bar
 * included, so a bar whose stored row is below its members' is packed after
 * them and drawn underneath: the heading at the foot of its own group. Its row
 * went stale whenever a widget was dragged, which saved where every widget had
 * been packed to and not where the bar had. So the bar is placed one row above
 * its highest member here, whatever is stored. A group whose first member is
 * on the top row has no row above it, and its members are moved down one -
 * which is what the grid does anyway the moment the bar is put above them.
 *
 * `members` is each widget in a group: its group and its stored row.
 */
export function barsAbove(
  groups: { id: string; y?: number }[],
  members: { groupId: string; y: number }[],
): { bars: Map<string, number>; push: Map<string, number> } {
  const highest = new Map<string, number>()
  for (const member of members) {
    highest.set(member.groupId, Math.min(highest.get(member.groupId) ?? Infinity, member.y))
  }
  const bars = new Map<string, number>()
  const push = new Map<string, number>()
  for (const group of groups) {
    const stored = Number(group.y ?? 0)
    const first = highest.get(group.id)
    if (first === undefined || stored < first) {
      bars.set(group.id, stored)
    } else if (first >= GROUP_BAR_ROWS) {
      bars.set(group.id, first - GROUP_BAR_ROWS)
    } else {
      bars.set(group.id, 0)
      push.set(group.id, GROUP_BAR_ROWS - first)
    }
  }
  return { bars, push }
}

/** A group as the grid has it: its bar and its members, where they were packed. */
export type PlacedGroup = { id: string; bar: Box; members: Box[] }

/**
 * Which group a widget dropped at `box` belongs to, or "" for none.
 *
 * The group whose box it landed in: its middle within the group's columns,
 * and its top below the bar and above the foot of the group's other members.
 * Under an empty group that is the row straight beneath the bar. A widget
 * landing exactly at the foot of a group is just below it, not in it, which
 * is where "take out" puts one.
 *
 * Joining a group only ever happened through a widget's menu, and leaving
 * one too: a widget dragged into a box sat there as a stranger the box was
 * drawn round, and a member dragged out took the box with it.
 *
 * `groups` leave the dropped widget out of their members, so a member is
 * judged against the rest of its group rather than against itself.
 */
export function groupAt(box: Box, groups: PlacedGroup[]): string {
  const middle = box.x + box.w / 2
  let found: PlacedGroup | null = null
  for (const group of groups) {
    const frame = bounding([group.bar, ...group.members]) as Box
    const foot = frame.y + frame.h
    const across = middle >= frame.x && middle < frame.x + frame.w
    const below = box.y > group.bar.y
    const within = group.members.length ? box.y < foot : box.y === group.bar.y + GROUP_BAR_ROWS
    // The nearest bar above it, if two groups ever stack in the same columns.
    if (across && below && within && (!found || group.bar.y > found.bar.y)) found = group
  }
  return found ? found.id : ''
}

/**
 * Where a widget goes when it is taken out of a group: just below it.
 *
 * Left where it stood, a widget taken out was still inside the box - the box
 * is drawn round the bar and the rest of the group, which still spanned it -
 * so taking one out looked like nothing at all. Below the group is out of it.
 *
 * Under the tallest of the remaining members, because the grid packs upwards:
 * set down anywhere else in the group's columns it would float back up into
 * the space it left, under the bar, and be inside the box again. Coming up
 * under the tallest member, the first thing it meets is that member's foot,
 * which is the foot of the group.
 */
export function spotBelow(
  widget: { w: number; h: number },
  group: PlacedGroup,
  columns: number,
): Box {
  const rest = group.members
  if (!rest.length) {
    // Only the bar is left, and only the bar is boxed: straight under it is out.
    return { x: Math.min(group.bar.x, Math.max(0, columns - widget.w)), y: group.bar.y + GROUP_BAR_ROWS, ...widget }
  }
  const tallest = rest.reduce((low, one) => (one.y + one.h > low.y + low.h ? one : low))
  return {
    x: Math.min(tallest.x, Math.max(0, columns - widget.w)),
    y: tallest.y + tallest.h,
    ...widget,
  }
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
            className="absolute rounded-control border-dashed transition-all duration-150"
            style={{
              left,
              top,
              width,
              height,
              borderWidth: GROUP_LINE,
              borderColor: frameInk(group, tone),
              backgroundColor: groupGround(group),
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
  onStyle,
}: {
  group: WidgetGroup
  /** How many widgets are in it, which is all a collapsed group can show. */
  count: number
  editing: boolean
  onRename: (name: string) => void
  onToggle: () => void
  onRemove: () => void
  /** Save the group's colours and heading size. */
  onStyle: (change: Pick<WidgetGroup, 'color' | 'background' | 'title_size'>) => void
}) {
  const [styling, setStyling] = useState(false)
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

  const ink = groupInk(group)
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
          className="input input-xs min-w-0 flex-1"
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
          style={group.title_size ? { fontSize: group.title_size, lineHeight: 1.2 } : undefined}
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
            onClick={() => setStyling(true)}
            className="shrink-0 text-xs opacity-60 hover:opacity-100"
            aria-label={`Style "${group.name}"`}
            title="Colours and heading size"
          >
            ◐
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
      {styling && (
        <GroupStyle
          group={group}
          onClose={() => setStyling(false)}
          onSave={(change) => {
            onStyle(change)
            setStyling(false)
          }}
        />
      )}
    </div>
  )
}

/**
 * A group's colours and heading size.
 *
 * Its own small dialog rather than a row of controls on the bar: the bar is a
 * line one grid row tall that is also the drag handle, and three pickers on it
 * would be dragged by every attempt to use them.
 */
function GroupStyle({
  group,
  onClose,
  onSave,
}: {
  group: WidgetGroup
  onClose: () => void
  onSave: (change: Pick<WidgetGroup, 'color' | 'background' | 'title_size'>) => void
}) {
  const [color, setColor] = useState(group.color ?? '')
  const [background, setBackground] = useState(group.background ?? '')
  const [size, setSize] = useState<number | undefined>(group.title_size)
  const preview: WidgetGroup = { ...group, color, background, title_size: size }
  // Onto the body: the bar is a grid item, and the grid places its items with
  // transforms, which would make the dialog's fixed position relative to the
  // bar and clip it to the bar's one row. A press in it still bubbles to the
  // bar through React, which the grid drags by, so it is stopped here.
  return createPortal(
    <div onMouseDown={(event) => event.stopPropagation()} onTouchStart={(event) => event.stopPropagation()}>
      <Modal
        open
        onClose={onClose}
        title={`Style "${group.name}"`}
        footer={
          <>
            <button className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={() =>
                onSave({ color: color || undefined, background: background || undefined, title_size: size })
              }
            >
              Save
            </button>
          </>
        }
      >
        <div
          className="mb-4 rounded-control border-2 border-dashed px-3 py-2"
          style={{
            borderColor: color || 'rgb(148 163 184 / 0.7)',
            backgroundColor: groupBarGround(preview),
            color: groupInk(preview),
          }}
          aria-hidden="true"
        >
          <span
            className="font-semibold uppercase tracking-wide"
            style={{ fontSize: size ?? DEFAULT_GROUP_TITLE }}
          >
            {group.name}
          </span>
        </div>
        <Field
          label="Background"
          hint="The group's own ground, behind its widgets and its title bar. A dark one turns the heading light by itself."
        >
          <ColorPicker
            value={background}
            onChange={setBackground}
            allowNone
            label="Group background"
            noneLabel="The faint grey wash"
          />
        </Field>
        <Field label="Heading and frame colour" hint="The group's name and the dashed line round it.">
          <ColorPicker
            value={color}
            onChange={setColor}
            allowNone
            label="Group heading"
            noneLabel="The dashboard's own ink"
          />
        </Field>
        <Field label={`Heading size: ${size ?? DEFAULT_GROUP_TITLE}px`}>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={10}
              max={32}
              step={1}
              className="w-48"
              aria-label="Heading size"
              value={size ?? DEFAULT_GROUP_TITLE}
              onChange={(event) => setSize(Number(event.target.value))}
            />
            {size !== undefined && (
              <button className="btn-ghost btn-sm" onClick={() => setSize(undefined)}>
                Default
              </button>
            )}
          </div>
        </Field>
      </Modal>
    </div>,
    document.body,
  )
}
