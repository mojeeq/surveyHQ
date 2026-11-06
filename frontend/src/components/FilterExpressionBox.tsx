/*
 * The box a filter expression is typed in: coloured, and offering what comes
 * next - the variables while a name is typed, the methods after a dot, a
 * coded variable's labels inside the quotes.
 *
 * CodeMirror, as the script editor is, and loaded only when somebody switches
 * a filter to an expression, so a page with a filter on it does not carry an
 * editor nobody opened. What the words mean is in `lib/filter-expression`;
 * this draws them, underlines the one the last reading stopped at, and
 * reports what is typed.
 */
import { useEffect, useRef } from 'react'
import { Annotation, EditorState, StateEffect, StateField } from '@codemirror/state'
import type { Range } from '@codemirror/state'
import { Decoration, EditorView, drawSelection, keymap, placeholder, tooltips } from '@codemirror/view'
import type { DecorationSet } from '@codemirror/view'
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from '@codemirror/language'
import type { StringStream } from '@codemirror/language'
import {
  acceptCompletion,
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
  startCompletion,
} from '@codemirror/autocomplete'
import type { CompletionContext } from '@codemirror/autocomplete'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { tags } from '@lezer/highlight'

import { suggestAt } from '@/lib/filter-expression'
import type { Variable } from '@/lib/types'

/** A change made by the page rather than typed: not reported back. */
const fromOutside = Annotation.define<boolean>()

/** Where the last reading went wrong, underlined. */
const markError = StateEffect.define<{ from: number; to: number } | null>()
const errorMark = Decoration.mark({ class: 'cm-expression-error' })
const errorField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(marks, transaction) {
    marks = marks.map(transaction.changes)
    for (const effect of transaction.effects) {
      if (!effect.is(markError)) continue
      const length = transaction.state.doc.length
      if (!effect.value || !length) {
        marks = Decoration.none
        continue
      }
      // A mistake at the very end - a bracket never closed - has nothing
      // after it to underline, so the last character carries it.
      const from = Math.min(effect.value.from, length - 1)
      const to = Math.max(from + 1, Math.min(effect.value.to, length))
      const ranges: Range<Decoration>[] = [errorMark.range(from, to)]
      marks = Decoration.set(ranges)
    }
    return marks
  },
  provide: (field) => EditorView.decorations.from(field),
})

const FUNCTIONS = new Set(['isanswered', 'isselected'])
const LOGIC = new Set(['and', 'or', 'not'])
const ATOMS = new Set(['null', 'true', 'false'])

/** Colours for the words: the script editor's classes, so both themes hold. */
const colours = HighlightStyle.define([
  { tag: tags.keyword, class: 'sx-command' },
  { tag: tags.invalid, class: 'sx-invalid' },
  { tag: tags.string, class: 'sx-string' },
  { tag: [tags.number, tags.atom], class: 'sx-number' },
  { tag: tags.propertyName, class: 'sx-function' },
  { tag: tags.variableName, class: 'sx-variable' },
  { tag: tags.operator, class: 'sx-operator' },
])

function language(names: Set<string>) {
  return StreamLanguage.define<{ afterDot: boolean }>({
    startState: () => ({ afterDot: false }),
    token(stream: StringStream, state) {
      if (stream.eatSpace()) return null
      const afterDot = state.afterDot
      state.afterDot = false
      if (stream.match(/^"(?:[^"\\]|\\.)*"?/) || stream.match(/^'(?:[^'\\]|\\.)*'?/)) return 'string'
      if (stream.match(/^`[^`]*`?/)) return 'variableName'
      if (stream.match(/^\d+(\.\d+)?/)) return 'number'
      const word = stream.match(/^[A-Za-z_][A-Za-z0-9_]*/)
      if (word && typeof word !== 'boolean') {
        const lower = word[0].toLowerCase()
        if (afterDot) return 'propertyName'
        if (FUNCTIONS.has(lower) || LOGIC.has(lower) || word[0] === 'string') return 'keyword'
        if (ATOMS.has(lower)) return 'atom'
        return names.has(word[0]) || names.has(lower) ? 'variableName' : 'invalid'
      }
      if (stream.eat('.')) {
        state.afterDot = true
        return 'operator'
      }
      stream.next()
      return 'operator'
    },
  })
}

const keys = keymap.of([
  ...closeBracketsKeymap,
  // Enter is not a new line here: the expression is one condition, and the
  // dialog around it may want the key.
  ...defaultKeymap.filter((binding) => binding.key !== 'Enter'),
  ...historyKeymap,
  ...completionKeymap,
  { key: 'Tab', run: acceptCompletion },
])

export default function FilterExpressionBox({
  value,
  onChange,
  variables,
  error,
  label,
}: {
  value: string
  onChange: (text: string) => void
  variables: Variable[]
  error: { from: number; to: number } | null
  label: string
}) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const latest = useRef({ onChange, variables })
  latest.current = { onChange, variables }

  useEffect(() => {
    if (!host.current) return
    const names = new Set(
      latest.current.variables.flatMap((one) => [one.name, one.name.toLowerCase()]),
    )
    const complete = (context: CompletionContext) => {
      const found = suggestAt(context.state.doc.toString(), context.pos, latest.current.variables)
      if (!found || !found.options.length) return null
      return {
        from: found.from,
        validFor: /^[\w ]*$/,
        options: found.options.map((one) => ({
          label: one.label,
          detail: one.detail,
          type: one.type === 'text' ? 'text' : one.type,
          apply: (target: EditorView, _completion: unknown, from: number, to: number) => {
            const insert = one.insert ?? one.label
            // Into the brackets of IsAnswered() or InList(), or the quotes of
            // Contains(""): what goes there is the next thing to type.
            const back = /\(\)$/.test(insert) ? 1 : /\(""\)$/.test(insert) ? 2 : 0
            target.dispatch({
              changes: { from, to, insert },
              selection: { anchor: from + insert.length - back },
              userEvent: 'input.complete',
            })
            if (back === 1) startCompletion(target)
          },
        })),
      }
    }
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          history(),
          drawSelection(),
          closeBrackets(),
          keys,
          EditorView.lineWrapping,
          language(names),
          syntaxHighlighting(colours),
          autocompletion({ override: [complete], icons: true, maxRenderedOptions: 100, activateOnTyping: true }),
          tooltips({ parent: document.body }),
          placeholder('age >= 15 && sex == "Female" && district.InList("North", "East")'),
          errorField,
          EditorView.contentAttributes.of({ 'aria-label': label, spellcheck: 'false' }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged && !update.transactions.some((one) => one.annotation(fromOutside))) {
              latest.current.onChange(update.state.doc.toString())
            }
          }),
        ],
      }),
    })
    view.current = editor
    return () => {
      editor.destroy()
      view.current = null
    }
    // Made once; a new set of variables remakes it through the key below.
  }, [])

  // The page replaced the text: put it in without calling it typing.
  useEffect(() => {
    const editor = view.current
    if (!editor) return
    const current = editor.state.doc.toString()
    if (value === current) return
    editor.dispatch({
      changes: { from: 0, to: current.length, insert: value },
      annotations: fromOutside.of(true),
    })
  }, [value])

  useEffect(() => {
    view.current?.dispatch({ effects: markError.of(error) })
  }, [error])

  return <div ref={host} className="expression-editor" />
}
