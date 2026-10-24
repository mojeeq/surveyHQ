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
import { useSyncExternalStore } from 'react'

export interface Draft {
  text: string
  /** What the editor opened on when the draft was made: the saved script, or
   *  the run on record. If that has changed since, somebody saved over it. */
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
const LAST_OPEN = 'surveyhq.scripts.open'

const drafts = new Map<string, Draft>()
const logs = new Map<string, LogLine[]>()
const listeners = new Set<() => void>()
/** Which scripts have a draft, as one value per change, for React to read. */
let held: ReadonlySet<string> = new Set()

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
 *  first render after a reload. */
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
      const draft = parsed(store.getItem(key))
      if (draft) drafts.set(key.slice(PREFIX.length), draft)
    }
  } catch {
    // Storage that cannot be read is storage there is nothing in.
  }
  held = new Set(drafts.keys())
}

function changed() {
  held = new Set(drafts.keys())
  for (const listener of listeners) listener()
}

export function readDraft(projectId: string): Draft | null {
  load()
  return drafts.get(projectId) ?? null
}

/** Keep a draft. False when only the memory copy could be kept, so it will
 *  not outlive the tab. */
export function writeDraft(projectId: string, draft: Draft): boolean {
  load()
  const isNew = !drafts.has(projectId)
  drafts.set(projectId, draft)
  // Only a script gaining or losing a draft redraws the list; a keystroke in
  // one that has one already changes nothing there.
  if (isNew) changed()
  try {
    const store = storage()
    if (!store) return false
    store.setItem(PREFIX + projectId, JSON.stringify(draft))
    return true
  } catch {
    return false
  }
}

export function clearDraft(projectId: string) {
  load()
  const had = drafts.delete(projectId)
  try {
    storage()?.removeItem(PREFIX + projectId)
  } catch {
    // Nothing to clear where nothing could be kept.
  }
  if (had) changed()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The scripts with a draft, as they stand. */
export function draftedScripts(): ReadonlySet<string> {
  load()
  return held
}

/** The scripts with a draft, kept current as drafts come and go. */
export function useDrafts(): ReadonlySet<string> {
  return useSyncExternalStore(subscribe, draftedScripts)
}

export function recallLog(projectId: string): LogLine[] {
  return logs.get(projectId) ?? []
}

export function rememberLog(projectId: string, log: LogLine[]) {
  if (log.length) logs.set(projectId, log)
  else logs.delete(projectId)
}

/** The script that was open last, so the page comes back to it. */
export function lastOpen(): string | null {
  try {
    return storage()?.getItem(LAST_OPEN) ?? null
  } catch {
    return null
  }
}

export function rememberOpen(projectId: string) {
  try {
    storage()?.setItem(LAST_OPEN, projectId)
  } catch {
    // Opening on the first script instead is no loss.
  }
}
