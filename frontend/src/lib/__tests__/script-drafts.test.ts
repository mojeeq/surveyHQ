/**
 * Unsaved scripts outliving the page they were typed on.
 *
 * Leaving the Scripts page used to lose whatever had not been saved. Drafts
 * are kept now - in memory for moving around the app, and in the browser's
 * storage for a reload - each belonging to the account that typed it, and
 * these are the rules they are kept by.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/** A browser's storage, as far as the drafts use it. */
function fakeStorage(refuse = false) {
  const items = new Map<string, string>()
  return {
    items,
    get length() {
      return items.size
    },
    key: (index: number) => [...items.keys()][index] ?? null,
    getItem: (key: string) => items.get(key) ?? null,
    setItem: (key: string, value: string) => {
      if (refuse) throw new Error('QuotaExceededError')
      items.set(key, value)
    },
    removeItem: (key: string) => void items.delete(key),
  }
}

/** The module afresh, as a page load would find it. */
async function fresh() {
  vi.resetModules()
  return import('@/lib/script-drafts')
}

const draft = { text: 'use people\ngen x = 1', base: 'use people', at: '2026-10-24T20:00:00Z' }

describe('drafts', () => {
  let storage: ReturnType<typeof fakeStorage>

  beforeEach(() => {
    storage = fakeStorage()
    vi.stubGlobal('window', { localStorage: storage })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps a draft until it is cleared', async () => {
    const drafts = await fresh()
    expect(drafts.writeDraft('ann', 'p1', draft)).toBe(true)
    expect(drafts.readDraft('ann', 'p1')).toEqual(draft)
    expect(drafts.draftedScripts('ann').has('p1')).toBe(true)
    drafts.clearDraft('ann', 'p1')
    expect(drafts.readDraft('ann', 'p1')).toBeNull()
    expect(drafts.draftedScripts('ann').has('p1')).toBe(false)
    expect(storage.items.size).toBe(0)
  })

  it('outlives a reload, by way of the browser\'s storage', async () => {
    const before = await fresh()
    before.writeDraft('ann', 'p1', draft)
    const after = await fresh()
    expect(after.readDraft('ann', 'p1')).toEqual(draft)
    expect(after.draftedScripts('ann')).toEqual(new Set(['p1']))
  })

  it('is the account\'s that typed it, not the next one to sign in', async () => {
    // A shared office computer: one person signs out, another signs in with
    // the right to edit the same project.
    const drafts = await fresh()
    drafts.writeDraft('ann', 'p1', draft)
    expect(drafts.readDraft('ben', 'p1')).toBeNull()
    expect(drafts.draftedScripts('ben').size).toBe(0)
    drafts.clearDraft('ben', 'p1')
    expect(drafts.readDraft('ann', 'p1')).toEqual(draft)
    const reloaded = await fresh()
    expect(reloaded.readDraft('ben', 'p1')).toBeNull()
    expect(reloaded.readDraft('ann', 'p1')).toEqual(draft)
  })

  it('keeps nothing with nobody signed in', async () => {
    const drafts = await fresh()
    expect(drafts.writeDraft('', 'p1', draft)).toBe(false)
    expect(drafts.readDraft('', 'p1')).toBeNull()
    expect(storage.items.size).toBe(0)
  })

  it('leaves a draft from before drafts had owners alone', async () => {
    storage.items.set('surveyhq.scriptDraft.p1', JSON.stringify(draft))
    const drafts = await fresh()
    expect(drafts.readDraft('ann', 'p1')).toBeNull()
    expect(drafts.draftedScripts('ann').size).toBe(0)
  })

  it('still covers moving around the app where storage is refused, and says so', async () => {
    vi.stubGlobal('window', { localStorage: fakeStorage(true) })
    const drafts = await fresh()
    expect(drafts.writeDraft('ann', 'p1', draft)).toBe(false)
    expect(drafts.readDraft('ann', 'p1')).toEqual(draft)
  })

  it('works with no storage at all', async () => {
    vi.stubGlobal('window', undefined)
    const drafts = await fresh()
    expect(drafts.writeDraft('ann', 'p1', draft)).toBe(false)
    expect(drafts.readDraft('ann', 'p1')).toEqual(draft)
    expect(drafts.lastOpen('ann')).toBeNull()
  })

  it('tells the list only when a script gains or loses a draft', async () => {
    const drafts = await fresh()
    drafts.writeDraft('ann', 'p1', draft)
    const first = drafts.draftedScripts('ann')
    drafts.writeDraft('ann', 'p1', { ...draft, text: 'use people' })
    // A keystroke in a script that has a draft already is the same list.
    expect(drafts.draftedScripts('ann')).toBe(first)
    drafts.writeDraft('ann', 'p2', draft)
    expect(drafts.draftedScripts('ann')).not.toBe(first)
  })

  it('ignores what it cannot read', async () => {
    storage.items.set('surveyhq.scriptDraft.ann.p1', '{not json')
    storage.items.set('surveyhq.scriptDraft.ann.p2', JSON.stringify({ base: 'x' }))
    const drafts = await fresh()
    expect(drafts.readDraft('ann', 'p1')).toBeNull()
    expect(drafts.readDraft('ann', 'p2')).toBeNull()
  })

  it('keeps what a draft was begun from until it is saved or thrown away', async () => {
    const drafts = await fresh()
    // Begun over the saved script...
    const begun = drafts.draftFrom(null, 'use people\ndrop x', 'use people', 't1')
    expect(begun.base).toBe('use people')
    // ...and reopened after somebody saved another: still begun from the first.
    const reopened = drafts.draftFrom(begun, 'use people\ndrop x', 'use people\ngen y = 2', 't2')
    expect(reopened).toEqual({ text: 'use people\ndrop x', base: 'use people', at: 't2' })
  })

  it('hands a draft kept by project to the script that was the project\'s', async () => {
    // Kept under the project's id while a project had one script.
    const before = await fresh()
    before.writeDraft('ann', 'project-1', draft)
    const after = await fresh()
    after.adoptDraft('ann', 'project-1', 'script-1')
    expect(after.readDraft('ann', 'script-1')).toEqual(draft)
    expect(after.readDraft('ann', 'project-1')).toBeNull()
    expect([...storage.items.keys()]).toEqual(['surveyhq.scriptDraft.ann.script-1'])
  })

  it('does not write an old draft over one the script has of its own', async () => {
    const drafts = await fresh()
    const own = { ...draft, text: 'use households' }
    drafts.writeDraft('ann', 'project-1', draft)
    drafts.writeDraft('ann', 'script-1', own)
    drafts.adoptDraft('ann', 'project-1', 'script-1')
    expect(drafts.readDraft('ann', 'script-1')).toEqual(own)
    expect(drafts.readDraft('ann', 'project-1')).toBeNull()
  })

  it('remembers the last run\'s output and the script that was open, per account', async () => {
    const drafts = await fresh()
    const log = [{ command: 'use people', message: 'Loaded people', ok: true }]
    drafts.rememberLog('ann', 'p1', log)
    expect(drafts.recallLog('ann', 'p1')).toEqual(log)
    expect(drafts.recallLog('ben', 'p1')).toEqual([])
    drafts.rememberLog('ann', 'p1', [])
    expect(drafts.recallLog('ann', 'p1')).toEqual([])
    drafts.rememberOpen('ann', 'p9')
    expect(drafts.lastOpen('ann')).toBe('p9')
    expect(drafts.lastOpen('ben')).toBeNull()
  })
})
