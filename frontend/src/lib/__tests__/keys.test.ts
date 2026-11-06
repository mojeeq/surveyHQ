/**
 * When Enter saves a dialog, and the longer list of when it must not.
 *
 * Escape closed a dialog from the day there were dialogs and Enter did
 * nothing, so every Save was a reach for the mouse after typing the one field
 * the dialog asked for. The risk in closing that gap is not the saving; it is
 * the keystrokes that already meant something else, and each of those is a
 * case here.
 */

import { describe, expect, it } from 'vitest'

import { confirmsOnEnter, type EnterContext } from '@/lib/keys'

/** A plain Enter, typed in a text field, with nothing else going on. */
function pressed(overrides: Partial<EnterContext> = {}): EnterContext {
  return {
    key: 'Enter',
    defaultPrevented: false,
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    shiftKey: false,
    isComposing: false,
    keyCode: 13,
    tagName: 'INPUT',
    inputType: 'text',
    isContentEditable: false,
    role: null,
    ...overrides,
  }
}

describe('Enter confirms a dialog', () => {
  it('after typing in a field, which is the whole point', () => {
    expect(confirmsOnEnter(pressed())).toBe(true)
  })

  it('with nothing focused, because the dialog is all there is on the screen', () => {
    expect(confirmsOnEnter(pressed({ tagName: null }))).toBe(true)
  })

  it('from a dropdown, which does nothing with Enter of its own', () => {
    expect(confirmsOnEnter(pressed({ tagName: 'SELECT' }))).toBe(true)
  })

  it('from a checkbox, a radio or a date field, which do not answer Enter', () => {
    // A checkbox and a radio are worked with the space bar, and Enter on one
    // inside a form has always submitted it.
    for (const inputType of ['checkbox', 'radio', 'date', 'number', 'search']) {
      expect(confirmsOnEnter(pressed({ inputType }))).toBe(true)
    }
  })

  it('only on Enter', () => {
    for (const key of ['Escape', 'Tab', ' ', 'a', 'ArrowDown']) {
      expect(confirmsOnEnter(pressed({ key }))).toBe(false)
    }
  })
})

describe('Enter is left alone where it already means something', () => {
  it('in a textarea, where it is a new line', () => {
    // A comment, a description, a script: a dialog that submitted on Enter
    // could not hold a paragraph.
    expect(confirmsOnEnter(pressed({ tagName: 'TEXTAREA' }))).toBe(false)
  })

  it('in contenteditable, for the same reason', () => {
    expect(confirmsOnEnter(pressed({ tagName: 'DIV', isContentEditable: true }))).toBe(false)
  })

  it('on a focused button, which Enter already presses', () => {
    // Otherwise tabbing to Cancel and pressing Enter would cancel and save.
    expect(confirmsOnEnter(pressed({ tagName: 'BUTTON' }))).toBe(false)
  })

  it('on a link', () => {
    expect(confirmsOnEnter(pressed({ tagName: 'A' }))).toBe(false)
  })

  it('on a summary, which opens its own section', () => {
    expect(confirmsOnEnter(pressed({ tagName: 'SUMMARY' }))).toBe(false)
  })

  it('on a file input, which opens the file chooser on Enter', () => {
    // The upload dialog is exactly where this bites: focus the Data file
    // control, press Enter, and confirming the dialog instead means it
    // complains no file was chosen - having just swallowed the keystroke
    // that would have let you choose one.
    expect(confirmsOnEnter(pressed({ inputType: 'file' }))).toBe(false)
  })

  it('on the input types that are buttons in disguise', () => {
    for (const inputType of ['submit', 'reset', 'button', 'image']) {
      expect(confirmsOnEnter(pressed({ inputType }))).toBe(false)
    }
  })

  it('on anything playing a button or a link without being one', () => {
    expect(confirmsOnEnter(pressed({ tagName: 'DIV', role: 'button' }))).toBe(false)
    expect(confirmsOnEnter(pressed({ tagName: 'SPAN', role: 'link' }))).toBe(false)
  })

  it('when something nearer the key has already answered it', () => {
    // The variable picker choosing the highlighted row, a tag field taking a
    // name. Each calls preventDefault, and the dialog listens on the
    // document, so it sees that. Without this, choosing a variable from a
    // list would also save the dialog it was chosen in.
    expect(confirmsOnEnter(pressed({ defaultPrevented: true }))).toBe(false)
  })

  it('while an input method is composing', () => {
    // Enter accepts the candidate. Anyone typing Japanese or Chinese into a
    // dialog would otherwise save it a word in.
    expect(confirmsOnEnter(pressed({ isComposing: true }))).toBe(false)
    // What engines without `isComposing` send instead, for every key.
    expect(confirmsOnEnter(pressed({ keyCode: 229 }))).toBe(false)
  })

  it('with any modifier held, which is somebody asking for something else', () => {
    // Ctrl+Enter runs the command box; Shift+Enter is a line in a few places.
    expect(confirmsOnEnter(pressed({ ctrlKey: true }))).toBe(false)
    expect(confirmsOnEnter(pressed({ metaKey: true }))).toBe(false)
    expect(confirmsOnEnter(pressed({ shiftKey: true }))).toBe(false)
    expect(confirmsOnEnter(pressed({ altKey: true }))).toBe(false)
  })
})
