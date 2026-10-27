/*
 * The box a script is written in: coloured, and offering what comes next.
 *
 * It was a plain textarea with line numbers drawn beside it. A script is code,
 * and the things that make code quick to write - a command that shows it is a
 * command, a typo that shows it is not, the dataset names offered after `use`,
 * the variables after `drop`, the options after the comma - all want an editor
 * that knows what each word is. CodeMirror is that editor; what it knows about
 * this language is in `lib/script-language`, worked out from the engine's own
 * vocabulary and the project's own datasets.
 *
 * The text still belongs to the page. This draws what it is given and reports
 * what is typed, and the rules about when an answer from the server may write
 * the box stay where they were, in ProjectScript: an outside change of `value`
 * replaces the text here without being reported back as typing.
 */
import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { Annotation, Compartment, EditorState, RangeSet, StateEffect, StateField } from '@codemirror/state'
import {
  Decoration,
  EditorView,
  GutterMarker,
  drawSelection,
  gutterLineClass,
  highlightActiveLine,
  highlightActiveLineGutter,
  hoverTooltip,
  keymap,
  lineNumbers,
  placeholder as placeholderText,
  tooltips,
} from '@codemirror/view'
import { HighlightStyle, StreamLanguage, bracketMatching, syntaxHighlighting } from '@codemirror/language'
import {
  acceptCompletion,
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
  startCompletion,
} from '@codemirror/autocomplete'
import type { Completion as EditorCompletion, CompletionContext } from '@codemirror/autocomplete'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { tags } from '@lezer/highlight'

import { insertLine } from '@/lib/script-insert'
import { acceptChange, completeAt, describeAt, scriptParser } from '@/lib/script-language'
import type { LanguageIndex } from '@/lib/script-language'

export interface ScriptEditorHandle {
  /** Put a line in where the cursor is, as typing it would. */
  insertLine: (line: string) => void
  /** Put the cursor at the start of a line, in view. */
  goTo: (line: number) => void
}

/** Marks a change that came from outside - the page filling the box - so it
 *  is not reported back as something the person typed. */
const fromOutside = Annotation.define<boolean>()

/** The line the last run stopped on, marked in the margin and across. */
const markStopped = StateEffect.define<number | null>()
const stoppedAt = StateField.define<number | null>({
  create: () => null,
  update(value, transaction) {
    for (const effect of transaction.effects) if (effect.is(markStopped)) value = effect.value
    return value
  },
})
class StoppedMarker extends GutterMarker {
  elementClass = 'cm-stopped-gutter'
}
const stoppedMarker = new StoppedMarker()
const stoppedLine = Decoration.line({ class: 'cm-stopped-line' })
const stoppedDecorations = [
  EditorView.decorations.compute([stoppedAt, 'doc'], (state) => {
    const line = state.field(stoppedAt)
    if (!line || line > state.doc.lines) return Decoration.none
    return Decoration.set([stoppedLine.range(state.doc.line(line).from)])
  }),
  gutterLineClass.compute([stoppedAt, 'doc'], (state) => {
    const line = state.field(stoppedAt)
    if (!line || line > state.doc.lines) return RangeSet.empty
    return RangeSet.of([stoppedMarker.range(state.doc.line(line).from)])
  }),
]

/** Classes rather than colours, so light and dark are both in index.css with
 *  the rest of the palette. */
const colours = HighlightStyle.define([
  { tag: tags.keyword, class: 'sx-command' },
  { tag: tags.invalid, class: 'sx-invalid' },
  { tag: tags.comment, class: 'sx-comment' },
  { tag: tags.string, class: 'sx-string' },
  { tag: tags.macroName, class: 'sx-macro' },
  { tag: [tags.number, tags.atom], class: 'sx-number' },
  { tag: tags.typeName, class: 'sx-dataset' },
  { tag: tags.propertyName, class: 'sx-option' },
  { tag: tags.function(tags.variableName), class: 'sx-function' },
  { tag: tags.variableName, class: 'sx-variable' },
  { tag: tags.operator, class: 'sx-operator' },
])

/** The editor's own keys, less Ctrl+Enter: that runs the script here, and is
 *  handled with Ctrl+S by the page around this rather than taken for a
 *  blank line. Tab takes a suggestion when the list is open and otherwise
 *  moves on, as it does everywhere else, so the keyboard is never trapped. */
const keys = keymap.of([
  ...closeBracketsKeymap,
  ...defaultKeymap.filter((binding) => binding.key !== 'Mod-Enter'),
  ...historyKeymap,
  ...completionKeymap,
  { key: 'Tab', run: acceptCompletion },
])

export const ScriptEditor = forwardRef<
  ScriptEditorHandle,
  {
    value: string
    onChange: (text: string) => void
    readOnly: boolean
    placeholder: string
    index: LanguageIndex
    stoppedLine: number | null
    onCaret: (caret: { line: number; column: number }) => void
    label: string
  }
>(function ScriptEditor({ value, onChange, readOnly, placeholder, index, stoppedLine: stopped, onCaret, label }, ref) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  // Read by the editor's callbacks, which are made once, so they always see
  // the latest of each rather than the first.
  const latest = useRef({ onChange, onCaret, index })
  latest.current = { onChange, onCaret, index }
  const language = useRef(new Compartment())
  const editable = useRef(new Compartment())
  const hint = useRef(new Compartment())
  // The name a screen reader gives the box, which follows the script's own
  // name when it is renamed.
  const named = useRef(new Compartment())

  useEffect(() => {
    if (!host.current) return
    const complete = (context: CompletionContext) => {
      const answer = completeAt(context.state.doc.toString(), context.pos, latest.current.index)
      if (!answer || !answer.options.length) return null
      if (!context.explicit && answer.from === context.pos && !answer.eager) return null
      return {
        from: answer.from,
        validFor: answer.validFor,
        options: answer.options.map(
          (one): EditorCompletion => ({
            label: one.label,
            type: one.type,
            detail: one.detail,
            info: one.info,
            boost: one.boost,
            apply:
              one.insert === undefined
                ? undefined
                : (target, _completion, from, to) => {
                    const change = acceptChange(target.state.sliceDoc(0, to + 1), from, to, one)
                    target.dispatch({
                      changes: { from: change.from, to: change.to, insert: change.insert },
                      selection: { anchor: change.caret },
                      userEvent: 'input.complete',
                    })
                    // Into the brackets of `by()` or `keep()`: what goes there
                    // is the next thing to offer.
                    if (one.caretBack) startCompletion(target)
                  },
          }),
        ),
      }
    }
    const help = hoverTooltip((target, pos) => {
      const found = describeAt(target.state.doc.toString(), pos, latest.current.index)
      if (!found) return null
      return {
        pos,
        above: true,
        create: () => {
          const dom = document.createElement('div')
          dom.className = 'sx-hover'
          const title = document.createElement('code')
          title.textContent = found.title
          const body = document.createElement('p')
          body.textContent = found.body
          dom.append(title, body)
          return { dom }
        },
      }
    })

    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          highlightActiveLine(),
          history(),
          drawSelection(),
          bracketMatching(),
          closeBrackets(),
          keys,
          language.current.of(StreamLanguage.define(scriptParser(index))),
          syntaxHighlighting(colours),
          autocompletion({ override: [complete], icons: true, maxRenderedOptions: 100 }),
          help,
          // On the page rather than inside the card, which clips what
          // overhangs it, so a list near the bottom of the box is not cut off.
          tooltips({ parent: document.body }),
          editable.current.of(EditorState.readOnly.of(readOnly)),
          hint.current.of(placeholderText(placeholder)),
          stoppedAt,
          stoppedDecorations,
          named.current.of(EditorView.contentAttributes.of({ 'aria-label': label, spellcheck: 'false' })),
          EditorView.updateListener.of((update) => {
            if (update.docChanged && !update.transactions.some((one) => one.annotation(fromOutside))) {
              latest.current.onChange(update.state.doc.toString())
            }
            if (update.docChanged || update.selectionSet) {
              const head = update.state.selection.main.head
              const line = update.state.doc.lineAt(head)
              latest.current.onCaret({ line: line.number, column: head - line.from + 1 })
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
    // Made once; everything that changes afterwards is passed in below.
  }, [])

  // The page filled the box: replace the text, without calling it typing.
  useEffect(() => {
    const editor = view.current
    if (!editor) return
    const current = editor.state.doc.toString()
    if (value === current) return
    editor.dispatch({
      changes: { from: 0, to: current.length, insert: value },
      selection: { anchor: Math.min(editor.state.selection.main.head, value.length) },
      annotations: fromOutside.of(true),
    })
  }, [value])

  useEffect(() => {
    view.current?.dispatch({
      effects: language.current.reconfigure(StreamLanguage.define(scriptParser(index))),
    })
  }, [index])

  useEffect(() => {
    view.current?.dispatch({ effects: editable.current.reconfigure(EditorState.readOnly.of(readOnly)) })
  }, [readOnly])

  useEffect(() => {
    view.current?.dispatch({ effects: hint.current.reconfigure(placeholderText(placeholder)) })
  }, [placeholder])

  useEffect(() => {
    view.current?.dispatch({ effects: markStopped.of(stopped) })
  }, [stopped])

  useEffect(() => {
    view.current?.dispatch({
      effects: named.current.reconfigure(
        EditorView.contentAttributes.of({ 'aria-label': label, spellcheck: 'false' }),
      ),
    })
  }, [label])

  useImperativeHandle(ref, () => ({
    insertLine(line: string) {
      const editor = view.current
      if (!editor) return
      const doc = editor.state.doc.toString()
      const at = editor.state.selection.main.head
      const { text, caret } = insertLine(doc, at, line)
      // insertLine only ever adds at the caret, so the change is what it added.
      editor.dispatch({
        changes: { from: at, insert: text.slice(at, at + text.length - doc.length) },
        selection: { anchor: caret },
        scrollIntoView: true,
        userEvent: 'input',
      })
      editor.focus()
    },
    goTo(line: number) {
      const editor = view.current
      if (!editor) return
      const target = editor.state.doc.line(Math.max(1, Math.min(line, editor.state.doc.lines)))
      editor.dispatch({
        selection: { anchor: target.from },
        effects: EditorView.scrollIntoView(target.from, { y: 'center' }),
      })
      editor.focus()
    },
  }))

  return <div ref={host} className="script-editor min-h-0 min-w-0 flex-1" />
})
