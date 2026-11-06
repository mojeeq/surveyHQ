/**
 * The "⋯" button: the actions on a thing that are not its main one.
 *
 * Deleting sat beside Open and Analyse on every card at the same weight, and
 * beside Archive on a project - one slip from the action somebody meant.
 * Behind a menu it is a deliberate second step, and it is still followed by
 * the confirmation that says what a deletion costs.
 *
 * The widget menu underneath already does the hard part: portalled so a card
 * that clips its overflow cannot cut it off, placed above or below the button
 * by which has room, and closed by a click away or Escape.
 */
import { WidgetMenu, type MenuItem } from '@/components/dashboard/WidgetMenu'

export type { MenuItem }

export default function MoreMenu({
  label,
  items,
  groups,
}: {
  /** What it is the options for, read out as "Options for …". */
  label: string
  /** One band of items; or several, with `groups`. */
  items?: MenuItem[]
  groups?: MenuItem[][]
}) {
  return (
    <WidgetMenu
      label={label}
      groups={groups ?? [items ?? []]}
      always
      className="btn-ghost btn-sm shrink-0 px-1.5 text-ink-600 dark:text-dark-600"
    />
  )
}
