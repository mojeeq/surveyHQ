/**
 * Which script the Scripts page opens, and what a new one is called.
 *
 * A project had one script, so "the project's script" named it, and every
 * link to the editor - the project page, the overview, an old bookmark - says
 * `?project=`. A project can have several now and the page opens a script by
 * its own id; a link by project still works, and means the project's oldest
 * script, which is the one it meant when it was made.
 */

export interface Placed {
  script_id: string
  name: string
  project_id: string
  created_at: string | null
}

/** A project's oldest script: what a link to "the project's script" means.
 *  Ordered as the server orders it, by when it was made and then by id. */
export function firstOf<T extends Placed>(places: T[], projectId: string): T | undefined {
  return places
    .filter((one) => one.project_id === projectId)
    .sort(
      (a, b) =>
        (a.created_at ?? '').localeCompare(b.created_at ?? '') ||
        a.script_id.localeCompare(b.script_id),
    )[0]
}

export type Opening = { script: string } | { start: string } | null

/** What to open when the address names no script.
 *
 *  A project named in the address opens its first script, or - with none -
 *  asks for one to be started there. With nothing named, the script that was
 *  open last, which may be a project's id from before scripts had their own;
 *  and otherwise the first in the list, since an editor that opens on nothing
 *  is a page to click through before it does anything.
 */
export function whichToOpen(
  listed: Placed[],
  asked: { project: string | null; last: string | null },
): Opening {
  if (asked.project) {
    const first = firstOf(listed, asked.project)
    return first ? { script: first.script_id } : { start: asked.project }
  }
  if (asked.last) {
    if (listed.some((one) => one.script_id === asked.last)) return { script: asked.last }
    const first = firstOf(listed, asked.last)
    if (first) return { script: first.script_id }
  }
  return listed[0] ? { script: listed[0].script_id } : null
}

/** The name a new script in this project gets when nobody gives one: the
 *  same rule the server applies, so the box can show it before it is sent.
 *  Names are told apart without regard to case, as the server does. */
export function nextName(places: Placed[], projectId: string, wanted = 'Main script'): string {
  const taken = new Set(
    places.filter((one) => one.project_id === projectId).map((one) => one.name.toLowerCase()),
  )
  if (!taken.has(wanted.toLowerCase())) return wanted
  let number = 2
  while (taken.has(`${wanted} ${number}`.toLowerCase())) number += 1
  return `${wanted} ${number}`
}
