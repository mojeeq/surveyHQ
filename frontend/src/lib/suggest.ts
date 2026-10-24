/*
 * Tab takes the suggestion a box is showing.
 *
 * Plenty of boxes show a suggestion in grey: the name a saved chart will get,
 * a variable's own name as its label, the folder imports are read from. Taking
 * one meant typing it out. Now Tab in an empty box that holds a suggestion
 * fills it in and stays there, so it can be edited; the next Tab moves on as
 * Tab always does, and Shift+Tab never fills anything.
 *
 * Only a box marked `data-suggest` does this, because grey text is not always
 * a suggestion. "Search datasets…" is an instruction; "auto" and "none" say
 * what an empty box means, and typing the word in would change that; an
 * example username or server address would be wrong as it stands. A box is
 * marked where its grey text is a value that is right as it is.
 */

/** What decides it, read off the key and the box. */
export interface TabPress {
  key: string
  shiftKey: boolean
  altKey: boolean
  ctrlKey: boolean
  metaKey: boolean
  defaultPrevented: boolean
}

export interface SuggestingBox {
  /** Whether the box is marked as holding a suggestion. */
  suggests: boolean
  value: string
  placeholder: string
  readOnly: boolean
  disabled: boolean
}

/** The text Tab should fill in, or null to let Tab do what it always does. */
export function suggestionFor(press: TabPress, box: SuggestingBox): string | null {
  if (press.key !== 'Tab' || press.defaultPrevented) return null
  // Shift+Tab goes back, and a modifier means some other shortcut.
  if (press.shiftKey || press.altKey || press.ctrlKey || press.metaKey) return null
  if (!box.suggests || box.readOnly || box.disabled) return null
  // Only an empty box. Once anything is typed the text is the person's, and
  // Tab leaving it is what they expect.
  if (box.value !== '') return null
  const suggestion = box.placeholder.trim()
  return suggestion ? suggestion : null
}

function isTextBox(target: EventTarget | null): target is HTMLInputElement | HTMLTextAreaElement {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement
}

/**
 * Fill a controlled React box as if the text had been typed.
 *
 * Setting `.value` directly is overwritten on React's next render, because
 * React tracks the value it last set. The native setter goes underneath that,
 * and the input event is what React's onChange listens for.
 */
function fill(box: HTMLInputElement | HTMLTextAreaElement, text: string) {
  const prototype =
    box instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(box, text)
  box.dispatchEvent(new Event('input', { bubbles: true }))
  try {
    box.setSelectionRange(text.length, text.length)
  } catch {
    // Some input types (number) have no selection; the value is in either way.
  }
}

/** Listen for Tab across the whole page. Returns what removes the listener. */
export function installSuggestions(root: Document = document): () => void {
  const onKeyDown = (event: KeyboardEvent) => {
    const target = event.target
    if (!isTextBox(target)) return
    const text = suggestionFor(event, {
      suggests: target.dataset.suggest !== undefined,
      value: target.value,
      placeholder: target.placeholder,
      readOnly: target.readOnly,
      disabled: target.disabled,
    })
    if (text === null) return
    event.preventDefault()
    fill(target, text)
  }
  root.addEventListener('keydown', onKeyDown)
  return () => root.removeEventListener('keydown', onKeyDown)
}
