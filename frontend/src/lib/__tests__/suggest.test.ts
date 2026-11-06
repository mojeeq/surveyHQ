/**
 * When Tab takes the suggestion a box is showing.
 *
 * Tab is also how a keyboard moves through a form, so it fills a box only
 * when that is plainly what is wanted - an empty box marked as holding a
 * suggestion - and otherwise does what Tab always does.
 */
import { describe, expect, it } from 'vitest'

import { suggestionFor } from '@/lib/suggest'
import type { SuggestingBox, TabPress } from '@/lib/suggest'

const tab: TabPress = {
  key: 'Tab', shiftKey: false, altKey: false, ctrlKey: false, metaKey: false, defaultPrevented: false,
}
const box: SuggestingBox = {
  suggests: true, value: '', placeholder: 'Daily field monitoring', readOnly: false, disabled: false,
}

describe('Tab in a box showing a suggestion', () => {
  it('fills in the suggestion when the box is empty', () => {
    expect(suggestionFor(tab, box)).toBe('Daily field monitoring')
  })

  it('moves on as usual once anything is typed', () => {
    expect(suggestionFor(tab, { ...box, value: 'D' })).toBeNull()
  })

  it('moves on as usual from a box not marked as suggesting', () => {
    // "Search datasets…" is grey text too, and an instruction, not a value.
    expect(suggestionFor(tab, { ...box, suggests: false, placeholder: 'Search datasets…' })).toBeNull()
  })

  it('never fills on Shift+Tab, which goes back', () => {
    expect(suggestionFor({ ...tab, shiftKey: true }, box)).toBeNull()
  })

  it('leaves Tab with a modifier to whatever shortcut it is', () => {
    expect(suggestionFor({ ...tab, ctrlKey: true }, box)).toBeNull()
    expect(suggestionFor({ ...tab, altKey: true }, box)).toBeNull()
  })

  it('leaves a box that handled Tab itself alone', () => {
    expect(suggestionFor({ ...tab, defaultPrevented: true }, box)).toBeNull()
  })

  it('does not write into a box that cannot be written', () => {
    expect(suggestionFor(tab, { ...box, readOnly: true })).toBeNull()
    expect(suggestionFor(tab, { ...box, disabled: true })).toBeNull()
  })

  it('has nothing to fill from an empty suggestion', () => {
    expect(suggestionFor(tab, { ...box, placeholder: '   ' })).toBeNull()
  })

  it('is only Tab', () => {
    expect(suggestionFor({ ...tab, key: 'Enter' }, box)).toBeNull()
  })
})
