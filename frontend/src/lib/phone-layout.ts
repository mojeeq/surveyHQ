/**
 * A board laid out for a phone: one column, in reading order.
 *
 * The grid scales a twelve-column board down to whatever width it is given,
 * so on a phone two widgets side by side became two slivers a few characters
 * wide - a dashboard of truncated titles and charts too narrow to read. On a
 * narrow screen every widget takes the full width instead, one under the
 * other, in the order a reader takes them in on the wide board: top to
 * bottom, and left to right within a row.
 *
 * A group goes as one piece. Its heading first and its members under it, so
 * the frame drawn round a group still encloses exactly its own widgets.
 *
 * Only what is drawn. Nothing here is saved, and the board keeps its own
 * layout for every screen wide enough to show it.
 */

/** Narrower than this, a board is stacked. */
export const PHONE_WIDTH = 640

export interface PlacedItem {
  i: string
  x: number
  y: number
  w: number
  h: number
}

/**
 * `groupOf` names, for a widget in a group, the id of that group's heading
 * item; for anything else it returns undefined.
 */
export function stackForPhone<T extends PlacedItem>(
  items: T[],
  columns: number,
  groupOf: (id: string) => string | undefined,
): T[] {
  const units = new Map<string, T[]>()
  for (const item of items) {
    const key = groupOf(item.i) ?? item.i
    const unit = units.get(key)
    if (unit) unit.push(item)
    else units.set(key, [item])
  }

  const byPlace = (a: PlacedItem, b: PlacedItem) => a.y - b.y || a.x - b.x
  const ordered = [...units.entries()]
    .map(([key, members]) => {
      // The heading leads its group whatever its stored row; then the
      // members as they are read on the wide board.
      // The item the unit is keyed by: a group's heading, or a widget alone.
      const heading = members.find((member) => member.i === key)
      const rest = members.filter((member) => member !== heading).sort(byPlace)
      const all = heading ? [heading, ...rest] : rest
      const corner = [...members].sort(byPlace)[0]
      return { corner, all }
    })
    .sort((a, b) => byPlace(a.corner, b.corner))

  let y = 0
  const stacked: T[] = []
  for (const { all } of ordered) {
    for (const item of all) {
      stacked.push({ ...item, x: 0, y, w: columns })
      y += item.h
    }
  }
  return stacked
}
