/**
 * A code box that colours what is typed into it.
 *
 * A coloured `<pre>` sits exactly under a transparent `<textarea>`. Typing,
 * selecting, undo, spellcheck, the caret and every keyboard shortcut are the
 * browser's own, because the thing being typed into really is a textarea - the
 * colour is only painted behind it. That is the whole trick, and it is why
 * this is a hundred lines rather than a dependency.
 *
 * The two layers have to agree about metrics down to the pixel or the letters
 * drift apart, so the font, size, line height, padding and wrapping are set
 * once in BOX and used by both.
 */

import { useLayoutEffect, useRef } from 'react'
import type { KeyboardEvent, UIEvent } from 'react'
import { TOKEN_CLASS, tokenise } from '@/lib/rsyntax'

/**
 * Everything that decides where a character lands.
 *
 * Shared by both layers on purpose. `break-words` matches what a textarea does
 * with a word too long for the line, which is the one wrapping case where a
 * plain `pre-wrap` would put the two layers on different lines.
 */
const BOX =
  'm-0 w-full whitespace-pre-wrap break-words font-mono text-xs leading-5 ' +
  'px-3 py-1.5 border border-transparent'

/** Two spaces, which is what the R sources in this project are written with. */
const INDENT = '  '

export default function CodeEditor({
  value,
  onChange,
  placeholder,
  minHeight = 220,
  onSubmit,
  ariaLabel,
}: {
  value: string
  onChange: (next: string) => void
  placeholder?: string
  minHeight?: number
  /** Ctrl or Cmd with Enter, for a box that has something to run. */
  onSubmit?: () => void
  ariaLabel?: string
}) {
  const input = useRef<HTMLTextAreaElement>(null)
  const painted = useRef<HTMLPreElement>(null)
  // Whether Escape was the last key pressed. Tab indents, so this is the way
  // out for anybody working from the keyboard: Escape, then Tab, moves focus
  // on the way it would from any other field. Without it the box is a trap.
  const leaving = useRef(false)

  // The two layers scroll as one. Done on layout rather than in an effect so
  // the paint never lands a frame behind the text after a paste.
  useLayoutEffect(() => {
    const box = input.current
    const behind = painted.current
    if (!box || !behind) return
    behind.scrollTop = box.scrollTop
    behind.scrollLeft = box.scrollLeft
  }, [value])

  const follow = (event: UIEvent<HTMLTextAreaElement>) => {
    const behind = painted.current
    if (!behind) return
    behind.scrollTop = event.currentTarget.scrollTop
    behind.scrollLeft = event.currentTarget.scrollLeft
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Escape') {
      leaving.current = true
      return
    }
    // Armed by Escape: this Tab is the one that moves focus, so it is left to
    // the browser. Shift+Tab always was.
    if (event.key === 'Tab' && leaving.current) {
      leaving.current = false
      return
    }
    leaving.current = false

    if (onSubmit && event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      onSubmit()
      return
    }
    // Tab indents, because a code box that moves focus instead is a code box
    // nobody can indent.
    if (event.key === 'Tab' && !event.shiftKey) {
      const box = event.currentTarget
      const { selectionStart, selectionEnd } = box
      event.preventDefault()
      const next =
        value.slice(0, selectionStart) + INDENT + value.slice(selectionEnd)
      onChange(next)
      // Put the caret after the spaces just inserted, once React has written
      // the new value back into the textarea.
      requestAnimationFrame(() => {
        box.selectionStart = selectionEnd + INDENT.length
        box.selectionEnd = selectionEnd + INDENT.length
      })
    }
  }

  return (
    <div
      className="relative w-full rounded-control bg-white dark:bg-dark-50"
      style={{ minHeight }}
    >
      <pre
        ref={painted}
        aria-hidden="true"
        className={`${BOX} r-syntax pointer-events-none absolute inset-0 overflow-hidden rounded-control`}
      >
        <Painted source={value} />
      </pre>
      <textarea
        ref={input}
        // `code-input` is what makes this layer see-through, so the coloured
        // text behind shows through it, and what gives the caret a colour of
        // its own - a transparent caret being an invisible cursor. It is a
        // class rather than utilities because the `.input` styling it sits
        // beside sets a colour and a background under `.dark` that a utility
        // would lose to. See index.css.
        className={`${BOX} input code-input relative block resize-y`}
        style={{ minHeight }}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        autoComplete="off"
        aria-label={ariaLabel}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onScroll={follow}
        onKeyDown={onKeyDown}
      />
    </div>
  )
}

/** The coloured runs. */
function Painted({ source }: { source: string }) {
  // A textarea ending in a newline shows an empty last line; a pre ending in
  // one does not, so the two would disagree about height and the box would
  // scroll a line short. The trailing space gives that line something to be.
  const text = source.endsWith('\n') ? `${source} ` : source
  return (
    <>
      {tokenise(text).map((token, index) => {
        const className = TOKEN_CLASS[token.kind]
        return className ? (
          <span key={index} className={className}>
            {token.text}
          </span>
        ) : (
          <span key={index}>{token.text}</span>
        )
      })}
    </>
  )
}

/** The same colouring, read-only, for a line of R shown as an example. */
export function CodeSnippet({ source }: { source: string }) {
  return (
    <code className="r-syntax font-mono">
      <Painted source={source} />
    </code>
  )
}
