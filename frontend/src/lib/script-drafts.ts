/**
 * Unsaved scripts, kept while the editor is away.
 *
 * The editor held a script's unsaved changes in its own state, so they lived
 * exactly as long as the Scripts page did: open Datasets to check a variable
 * name, come back, and the box was back to the saved script with the work
 * gone. An editor keeps an unsaved file open in a tab for as long as you
 * like, and this does the same - a draft per script, kept until it is saved,
 * run cleanly or thrown away.
 *
 * Not on the server, on purpose. A saved script is the one the next import
 * runs, so saving a draft behind somebody's back would start a half-written
 * script off inside an import. A draft is this person's, on this computer.
 *
 * And this person's alone. A field office shares its computers, and a draft
 * kept by project would be handed to whoever signed in next with the right
 * to edit that project - unsaved work they never wrote, a Save away from
 * becoming the script. So every draft belongs to the account that typed it,
 * in memory and in storage, and signing out leaves it waiting for that
 * account rather than for the next one.
 *
 * Two places, because either can fail the other. In memory, for leaving the
 * page and coming back, which works however the browser is set up; and in
 * the browser's storage, so a reload or a closed tab does not lose it either.
 * Storage can be refused - a private window, blocked site data - and then
 * the memory copy still covers moving around the app, and `writeDraft` says
 * so, so the editor can fall back to asking before the tab is closed.
 *
 * And the output of a script's last run here, in memory only: coming back to
 * a script should show what it just did, not an empty panel.
 */
import { useCallback, useSyncExternalStore } from 'react'

export interface Draft {
  text: string
  /** What the editor opened on when the draft was begun: the saved script,
   *  or the run on record. If that has changed since, somebody saved over
   *  it, and Save would write over their work. */
  base: string
  /** When it was last changed, as an ISO time. */
  at: string
}

export interface LogLine {
  command: string
  message: string
  ok: boolean
}

const PREFIX = 'surveyhq.scriptDraft.'
const LAST_OPEN = 'surveyhq.scripts.open.'

/** Keyed `<account>.<project>`, both of them ids with no dots in. */
const drafts = new Map<string, Draft>()
const logs = new Map<string, LogLine[]>()
const listeners = new Set<() => void>()
/** Bumped whenever a script gains or loses a draft. */
let version = 0
const listed = new Map<string, { version: number; ids: ReadonlySet<string> }>()

const keyOf = (owner: string, projectId: string) => `${owner}.${projectId}`

function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function parsed(raw: string | null): Draft | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<Draft>
    return typeof value.text === 'string'
      ? { text: value.text, base: String(value.base ?? ''), at: String(value.at ?? '') }
      : null
  } catch {
    return null
  }
}

/** Read what storage holds into memory, once, so the list is right from the
 *  first render after a reload. A key with no account in it is from before
 *  drafts had owners and is left alone: there is no knowing whose it was. */
let loaded = false
function load() {
  if (loaded) return
  loaded = true
  const store = storage()
  if (!store) return
  try {
    for (let i = 0; i < store.length; i += 1) {
      const key = store.key(i)
      if (!key?.startsWith(PREFIX)) continue
      const id = key.slice(PREFIX.length)
      if (!id.includes('.')) continue
      const draft = parsed(store.getItem(key))
      if (draft) drafts.set(id, draft)
    }
  } catch {
    // Storage that cannot be read is storage there is nothing in.
  }
}

function changed() {
  version += 1
  for (const listener of listeners) listener()
}

/** The draft to keep for what is in the box now.
 *
 *  Its starting point is kept from its first keystroke until it is saved or
 *  thrown away. Taken afresh each time, a script somebody else saved in the
 *  meantime became the draft's starting point the moment it was reopened,
 *  and the warning that Save would write over their work showed once and
 *  was gone.
 */
export function draftFrom(previous: Draft | null, text: string, opening: string, at: string): Draft {
  return { text, base: previous ? previous.base : opening, at }
}

export function readDraft(owner: string, projectId: string): Draft | null {
  if (!owner) return null
  load()
  return drafts.get(keyOf(owner, projectId)) ?? null
}

/** Keep a draft. False when only the memory copy could be kept, so it will
 *  not outlive the tab - or, with nobody signed in, when nothing was kept. */
export function writeDraft(owner: string, projectId: string, draft: Draft): boolean {
  if (!owner) return false
  load()
  const key = keyOf(owner, projectId)
  const isNew = !drafts.has(key)
  drafts.set(key, draft)
  // Only a script gaining or losing a draft redraws the list; a keystroke in
  // one that has one already changes nothing there.
  if (isNew) changed()
  try {
    const store = storage()
    if (!store) return false
    store.setItem(PREFIX + key, JSON.stringify(draft))
    return true
  } catch {
    return false
  }
}

export function clearDraft(owner: string, projectId: string) {
  if (!owner) return
  load()
  const key = keyOf(owner, projectId)
  const had = drafts.delete(key)
  try {
    storage()?.removeItem(PREFIX + key)
  } catch {
    // Nothing to clear where nothing could be kept.
  }
  if (had) changed()
}

/** The scripts this account has a draft of, as they stand. The same set is
 *  handed back until one is gained or lost, which is what React needs of a
 *  snapshot. */
export function draftedScripts(owner: string): ReadonlySet<string> {
  load()
  const cached = listed.get(owner)
  if (cached && cached.version === version) return cached.ids
  const prefix = `${owner}.`
  const ids = new Set(
    owner
      ? [...drafts.keys()].filter((key) => key.startsWith(prefix)).map((key) => key.slice(prefix.length))
      : [],
  )
  listed.set(owner, { version, ids })
  return ids
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The scripts this account has a draft of, kept current as drafts come and go. */
export function useDrafts(owner: string): ReadonlySet<string> {
  const snapshot = useCallback(() => draftedScripts(owner), [owner])
  return useSyncExternalStore(subscribe, snapshot)
}

export function recallLog(owner: string, projectId: string): LogLine[] {
  return logs.get(keyOf(owner, projectId)) ?? []
}

export function rememberLog(owner: string, projectId: string, log: LogLine[]) {
  if (log.length) logs.set(keyOf(owner, projectId), log)
  else logs.delete(keyOf(owner, projectId))
}

/** The script this account had open last, so the page comes back to it. */
export function lastOpen(owner: string): string | null {
  if (!owner) return null
  try {
    return storage()?.getItem(LAST_OPEN + owner) ?? null
  } catch {
    return null
  }
}

export function rememberOpen(owner: string, projectId: string) {
  if (!owner) return
  try {
    storage()?.setItem(LAST_OPEN + owner, projectId)
  } catch {
    // Opening on the first script instead is no loss.
  }
}
