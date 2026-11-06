/**
 * When Enter means "do the thing this dialog is for".
 *
 * Escape has closed a dialog here from the day there were dialogs; Enter did
 * nothing, so every Save, Add and Apply was a reach for the mouse after typing
 * the one field the dialog asked for. Closing that asymmetry is mostly a
 * matter of knowing when *not* to act, which is what this decides. The rest -
 * finding the dialog's own button and pressing it - is the Modal's.
 */

/** The part of a keyboard event this decision rests on. */
export interface EnterContext {
  key: string
  /**
   * Whether something nearer the key already answered it. A combobox choosing
   * the highlighted row, a tag field taking a name, a <details> opening: each
   * calls preventDefault, and the dialog listens on the document, so by the
   * time it runs that is visible here. Without it, choosing a variable from a
   * list would also save the dialog it was chosen in.
   */
  defaultPrevented: boolean
  metaKey: boolean
  ctrlKey: boolean
  altKey: boolean
  shiftKey: boolean
  /**
   * An input method is mid-composition and Enter accepts the candidate.
   * `isComposing` is the modern spelling; 229 is what older engines send for
   * every key while a composition is open. Anyone typing Japanese or Chinese
   * into a dialog would otherwise save it a word in.
   */
  isComposing: boolean
  keyCode: number
  /** The focused element's tag, upper case, or null when nothing is focused. */
  tagName: string | null
  /** An <input>'s type, lower case. Empty for everything else. */
  inputType: string
  isContentEditable: boolean
  /** Its `role`, for the things that are buttons without being <button>. */
  role: string | null
}

/**
 * Elements that answer Enter themselves, and must not have it answered twice.
 *
 * A textarea is prose or a script: Enter there is a new line, and a dialog
 * that submitted on it could not hold a paragraph. A button or a link is
 * already activated by Enter, so firing the dialog's primary as well would do
 * Cancel and Save at once. A summary opens its own <details>.
 */
const OWNS_ENTER = new Set(['TEXTAREA', 'BUTTON', 'A', 'SUMMARY'])

/**
 * Input types that answer Enter themselves, despite reporting as INPUT.
 *
 * A file input opens the file chooser on Enter, and the upload dialog is
 * exactly where that matters: focus the Data file control, press Enter, and
 * confirming the dialog instead means it complains that no file was chosen -
 * having just swallowed the keystroke that would have let you choose one.
 *
 * The rest are buttons wearing an <input>, which Enter already presses, so
 * confirming as well would do two things at once. A checkbox and a radio are
 * deliberately not here: they are worked with the space bar, and Enter on one
 * inside a form has always submitted it.
 */
const INPUTS_OWNING_ENTER = new Set(['file', 'submit', 'reset', 'button', 'image'])

export function confirmsOnEnter(event: EnterContext): boolean {
  if (event.key !== 'Enter') return false
  if (event.defaultPrevented) return false
  if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return false
  if (event.isComposing || event.keyCode === 229) return false
  if (event.isContentEditable) return false
  if (event.tagName !== null && OWNS_ENTER.has(event.tagName)) return false
  if (event.tagName === 'INPUT' && INPUTS_OWNING_ENTER.has(event.inputType)) return false
  if (event.role === 'button' || event.role === 'link') return false
  return true
}

/** Reads the context off a real event, for the one caller that has one. */
export function enterContext(event: KeyboardEvent): EnterContext {
  const target = event.target as HTMLElement | null
  return {
    key: event.key,
    defaultPrevented: event.defaultPrevented,
    metaKey: event.metaKey,
    ctrlKey: event.ctrlKey,
    altKey: event.altKey,
    shiftKey: event.shiftKey,
    isComposing: event.isComposing,
    keyCode: event.keyCode,
    // Nothing focused reads as no tag, and counts: the dialog is the only
    // thing on the screen, so Enter can only have been meant for it.
    tagName: target && target !== document.body ? target.tagName : null,
    inputType: String((target as HTMLInputElement | null)?.type ?? '').toLowerCase(),
    isContentEditable: Boolean(target?.isContentEditable),
    role: target?.getAttribute('role') ?? null,
  }
}
