/**
 * Unsaved scripts outliving the page they were typed on.
 *
 * Leaving the Scripts page used to lose whatever had not been saved. Drafts
 * are kept now - in memory for moving around the app, and in the browser's
 * storage for a reload - and these are the rules they are kept by.
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
    expect(drafts.writeDraft('p1', draft)).toBe(true)
    expect(drafts.readDraft('p1')).toEqual(draft)
    expect(drafts.draftedScripts().has('p1')).toBe(true)
    drafts.clearDraft('p1')
    expect(drafts.readDraft('p1')).toBeNull()
    expect(drafts.draftedScripts().has('p1')).toBe(false)
    expect(storage.items.size).toBe(0)
  })

  it('outlives a reload, by way of the browser\'s storage', async () => {
    const before = await fresh()
    before.writeDraft('p1', draft)
    const after = await fresh()
    expect(after.readDraft('p1')).toEqual(draft)
    expect(after.draftedScripts()).toEqual(new Set(['p1']))
  })

  it('still covers moving around the app where storage is refused, and says so', async () => {
    vi.stubGlobal('window', { localStorage: fakeStorage(true) })
    const drafts = await fresh()
    expect(drafts.writeDraft('p1', draft)).toBe(false)
    expect(drafts.readDraft('p1')).toEqual(draft)
  })

  it('works with no storage at all', async () => {
    vi.stubGlobal('window', undefined)
    const drafts = await fresh()
    expect(drafts.writeDraft('p1', draft)).toBe(false)
    expect(drafts.readDraft('p1')).toEqual(draft)
    expect(drafts.lastOpen()).toBeNull()
  })

  it('tells the list only when a script gains or loses a draft', async () => {
    const drafts = await fresh()
    drafts.writeDraft('p1', draft)
    const first = drafts.draftedScripts()
    drafts.writeDraft('p1', { ...draft, text: 'use people' })
    // A keystroke in a script that has a draft already is the same list.
    expect(drafts.draftedScripts()).toBe(first)
    drafts.writeDraft('p2', draft)
    expect(drafts.draftedScripts()).not.toBe(first)
  })

  it('ignores what it cannot read', async () => {
    storage.items.set('surveyhq.scriptDraft.p1', '{not json')
    storage.items.set('surveyhq.scriptDraft.p2', JSON.stringify({ base: 'x' }))
    const drafts = await fresh()
    expect(drafts.readDraft('p1')).toBeNull()
    expect(drafts.readDraft('p2')).toBeNull()
  })

  it('remembers the last run\'s output and the script that was open', async () => {
    const drafts = await fresh()
    const log = [{ command: 'use people', message: 'Loaded people', ok: true }]
    drafts.rememberLog('p1', log)
    expect(drafts.recallLog('p1')).toEqual(log)
    drafts.rememberLog('p1', [])
    expect(drafts.recallLog('p1')).toEqual([])
    drafts.rememberOpen('p9')
    expect(drafts.lastOpen()).toBe('p9')
  })
})
