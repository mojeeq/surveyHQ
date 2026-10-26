/**
 * The script language, as the editor colours and completes it.
 *
 * Everything here is worked out from two answers rather than written down: the
 * vocabulary (`GET /scripts/language`, read off the engine's own tables) and
 * the project's datasets with their variables (`GET /projects/{id}/script/
 * names`). A command added to the engine is coloured and offered without a
 * line changing here, and a command the engine does not know is coloured as
 * the mistake it is.
 *
 * Kept free of the editor itself, so that what is offered where - the part
 * that is easy to get subtly wrong - can be tested as plain functions: the
 * tokenizer is a CodeMirror stream parser, which runs on a string, and the
 * completions and the hover help are worked out from the text and the caret.
 */
import type { StreamParser, StringStream } from '@codemirror/language'

import { commandsOf } from '@/lib/script-lines'

export interface Vocabulary {
  commands: {
    name: string
    aliases: string[]
    syntax: string
    summary: string
    options: { name: string; summary: string; takes_argument: boolean }[]
  }[]
  functions: { name: string; syntax: string; summary: string }[]
  egen: { name: string; summary: string; rowwise: boolean }[]
  collapse: { name: string; summary: string }[]
  label_kinds: { name: string; summary: string }[]
  merge_shapes: string[]
  merge_keep: { name: string; summary: string }[]
  /** The word after a command saying which form it is: duplicates drop. */
  subcommands?: Record<string, { name: string; summary: string }[]>
  /** What a loop's first line is written with: in, of, varlist... */
  loop_words?: { name: string; summary: string }[]
  /** _n and _N. */
  row_names?: { name: string; summary: string }[]
  /** The commands a by prefix can stand in front of. */
  by_able?: string[]
}

/** `by hhid:` or `bysort hhid (age):` at the start of a command, which the
 *  engine reads as a prefix: what follows the colon is a command of its own. */
export const BY_PREFIX = /^\s*(?:by|bys|byso|bysor|bysort)\s+[^:]*:\s*/i

function withoutPrefix(text: string): string {
  const prefixed = BY_PREFIX.exec(text)
  return prefixed ? text.slice(prefixed[0].length) : text
}

export interface ScriptNames {
  datasets: {
    name: string
    slug: string
    rows: number
    variables: { name: string; label: string; type: string }[]
  }[]
}

type Command = Vocabulary['commands'][number]
type DatasetNames = ScriptNames['datasets'][number]

/** The two answers, looked up the way the engine looks things up. */
export interface LanguageIndex {
  vocabulary: Vocabulary
  /** Every spelling of every command, lower case, to the command. */
  verbs: Map<string, Command>
  functions: Map<string, Vocabulary['functions'][number]>
  egen: Map<string, Vocabulary['egen'][number]>
  collapse: Map<string, Vocabulary['collapse'][number]>
  /** By name and by slug, lower case, as `use` matches them. */
  datasets: Map<string, DatasetNames>
  /** Every variable in any of the project's datasets, by name. */
  variables: Map<string, { label: string; type: string; dataset: string }>
}

export const EMPTY_VOCABULARY: Vocabulary = {
  commands: [],
  functions: [],
  egen: [],
  collapse: [],
  label_kinds: [],
  merge_shapes: [],
  merge_keep: [],
  subcommands: {},
  loop_words: [],
  row_names: [],
  by_able: [],
}

export function indexLanguage(vocabulary: Vocabulary, names: ScriptNames | undefined): LanguageIndex {
  const verbs = new Map<string, Command>()
  for (const command of vocabulary.commands) {
    for (const spelling of [command.name, ...command.aliases]) verbs.set(spelling.toLowerCase(), command)
  }
  const datasets = new Map<string, DatasetNames>()
  const variables = new Map<string, { label: string; type: string; dataset: string }>()
  for (const dataset of names?.datasets ?? []) {
    datasets.set(dataset.name.toLowerCase(), dataset)
    if (dataset.slug) datasets.set(dataset.slug.toLowerCase(), dataset)
    for (const variable of dataset.variables) {
      if (!variables.has(variable.name)) {
        variables.set(variable.name, { label: variable.label, type: variable.type, dataset: dataset.name })
      }
    }
  }
  return {
    vocabulary,
    verbs,
    functions: new Map(vocabulary.functions.map((one) => [one.name, one])),
    egen: new Map(vocabulary.egen.map((one) => [one.name, one])),
    collapse: new Map(vocabulary.collapse.map((one) => [one.name, one])),
    datasets,
    variables,
  }
}

// --- colouring --------------------------------------------------------------

export interface LineState {
  /** The line before ended with `///`, so this one carries on its command. */
  continued: boolean
  /** No word of this command has been read yet. */
  atStart: boolean
  /** The command, by its own name; '?' for a word the engine does not know. */
  verb: string | null
  /** Past the comma that starts a command's options. */
  afterComma: boolean
  depth: number
  /** What the next word is: a dataset to read, or a name being given. */
  expect: 'dataset' | 'new-dataset' | null
  /** Just after `label`, `duplicates` or `reshape`, so the next word says
   *  which form of the command this is. */
  labelKind: boolean
  /** Just after `foreach` or `forvalues`: the next word is the loop's name. */
  loopName: boolean
}

function freshState(): LineState {
  return {
    continued: false,
    atStart: true,
    verb: null,
    afterComma: false,
    depth: 0,
    expect: null,
    labelKind: false,
    loopName: false,
  }
}

/** The token names, which CodeMirror maps to highlighting tags. */
export type Token =
  | 'keyword'
  | 'invalid'
  | 'comment'
  | 'string'
  | 'macroName'
  | 'atom'
  | 'number'
  | 'typeName'
  | 'propertyName'
  | 'variableName'
  | 'variableName.function'
  | 'operator'
  | 'punctuation'

/** A stream parser for scripts, knowing this vocabulary and these names. */
export function scriptParser(index: LanguageIndex): StreamParser<LineState> {
  const optionsOf = (verb: string | null) =>
    new Set((verb ? index.verbs.get(verb)?.options ?? [] : []).map((one) => one.name))
  const keepWords = new Set(index.vocabulary.merge_keep.map((one) => one.name))
  const labelKinds = index.vocabulary.label_kinds.map((one) => one.name)
  const forms = (verb: string | null) =>
    verb === 'label'
      ? labelKinds
      : (index.vocabulary.subcommands?.[verb ?? ''] ?? []).map((one) => one.name)
  const loopWords = new Set((index.vocabulary.loop_words ?? []).map((one) => one.name))
  const rowNames = new Set((index.vocabulary.row_names ?? []).map((one) => one.name))

  const token = (stream: StringStream, state: LineState): Token | null => {
    if (stream.sol()) {
      // A line carries on the command above only after a `///`; any other
      // line is a command of its own, as the engine splits them.
      if (!state.continued) Object.assign(state, freshState())
      state.continued = false
    }
    if (stream.eatSpace()) return null

    // `*` starts a comment line, but only where a command would start.
    if (state.atStart && state.verb === null && stream.peek() === '*') {
      stream.skipToEnd()
      return 'comment'
    }
    if (stream.match('///')) {
      stream.skipToEnd()
      state.continued = true
      return 'comment'
    }
    if (stream.match('//')) {
      stream.skipToEnd()
      return 'comment'
    }
    if (stream.peek() === '"') {
      stream.next()
      while (!stream.eol() && stream.next() !== '"') {
        // to the closing quote
      }
      const named = state.expect
      state.expect = null
      return named ? 'typeName' : 'string'
    }
    if (stream.match(/^`[A-Za-z_][A-Za-z0-9_]*'/) || stream.match(/^\$\{[A-Za-z_]\w*\}/) || stream.match(/^\$[A-Za-z_]\w*/)) {
      return 'macroName'
    }
    if (state.verb === 'merge' && stream.match(/^[1m]:[1m]\b/)) return 'atom'
    if (stream.match(/^\d+(\.\d*)?([eE][+-]?\d+)?/) || stream.match(/^\.\d+([eE][+-]?\d+)?/)) {
      return 'number'
    }
    // Missing values: . and .a to .z.
    if (stream.match(/^\.[a-z]?(?![\w.])/)) return 'atom'

    const matched = stream.match(/^[A-Za-z_][A-Za-z0-9_]*/)
    if (matched && typeof matched !== 'boolean') {
      const word = matched[0]
      const lower = word.toLowerCase()
      if (state.atStart) {
        state.atStart = false
        const command = index.verbs.get(lower)
        if (!command) {
          state.verb = '?'
          return 'invalid'
        }
        state.verb = command.name
        if (command.name === 'use') state.expect = 'dataset'
        if (forms(command.name).length) state.labelKind = true
        if (command.name === 'foreach' || command.name === 'forvalues') state.loopName = true
        return 'keyword'
      }
      if (state.labelKind) {
        state.labelKind = false
        // label's kinds go by their first letters too; the others in full.
        const kinds = forms(state.verb)
        if (state.verb === 'label' ? kinds.some((kind) => kind.startsWith(lower)) : kinds.includes(lower)) {
          return 'keyword'
        }
      }
      if (state.loopName) {
        // The name the loop sets, as `name' inside it.
        state.loopName = false
        return 'macroName'
      }
      if (state.verb === 'foreach' && state.depth === 0 && loopWords.has(lower)) return 'keyword'
      // Case matters, as in the engine: _n and _N, not _N and _n.
      if (rowNames.has(word)) return 'atom'
      if (state.expect) {
        state.expect = null
        return 'typeName'
      }
      if (!state.afterComma && state.depth === 0) {
        if (lower === 'using') {
          state.expect = 'dataset'
          return 'keyword'
        }
        if (state.verb === 'save' && lower === 'as') {
          state.expect = 'new-dataset'
          return 'keyword'
        }
        if (lower === 'if' || lower === 'in') return 'keyword'
      }
      if (state.afterComma && state.depth === 0 && optionsOf(state.verb).has(lower)) {
        return 'propertyName'
      }
      if (stream.peek() === '(') {
        if (state.verb === 'egen' && index.egen.has(lower)) return 'variableName.function'
        if (index.functions.has(lower)) return 'variableName.function'
      }
      if (state.depth > 0 && state.verb === 'collapse' && index.collapse.has(lower)) return 'atom'
      if (state.depth > 0 && state.verb === 'merge' && state.afterComma && keepWords.has(lower)) {
        return 'atom'
      }
      return 'variableName'
    }

    const character = stream.next()
    if (character === ':' && state.depth === 0 && (state.verb === 'by' || state.verb === 'bysort')) {
      // The prefix ends here; what follows is the command it runs.
      Object.assign(state, { ...freshState(), continued: state.continued })
      return 'punctuation'
    }
    if (character === '(') state.depth += 1
    else if (character === ')') state.depth = Math.max(0, state.depth - 1)
    else if (character === ',' && state.depth === 0) {
      state.afterComma = true
      return 'punctuation'
    }
    if (character && '=<>!~&|+-*/^'.includes(character)) {
      stream.eatWhile(/[=<>]/)
      return 'operator'
    }
    return 'punctuation'
  }

  return {
    name: 'surveyhq-script',
    startState: freshState,
    token,
    languageData: { commentTokens: { line: '//' } },
  }
}

// --- what comes next ----------------------------------------------------------

export interface Suggestion {
  label: string
  /** CodeMirror's kind, which picks the icon: keyword, function, variable... */
  type: 'keyword' | 'function' | 'variable' | 'property' | 'constant' | 'class' | 'text'
  detail?: string
  info?: string
  /** What goes in, where it is not the label itself. */
  insert?: string
  /** How far back from the end of `insert` the caret goes - into brackets. */
  caretBack?: number
  boost?: number
}

export interface Completion {
  from: number
  options: Suggestion[]
  /** Whether typing more should keep filtering this list rather than ask again. */
  validFor?: RegExp
  /** Worth opening before a letter is typed: after `use `, a comma, a `(`.
   *  Everywhere else a list waits for a letter, or for Ctrl+Space - one that
   *  sprang open after every space in an expression would be in the way. */
  eager?: boolean
}

/** Outside quotes: where the top-level comma is, and the unclosed bracket. */
function shape(text: string): { comma: number; open: number; quoted: boolean } {
  let quoted = false
  let comma = -1
  const opens: number[] = []
  for (let i = 0; i < text.length; i += 1) {
    const character = text[i]
    if (character === '"') quoted = !quoted
    else if (quoted) continue
    else if (character === '(') opens.push(i)
    else if (character === ')') opens.pop()
    else if (character === ',' && !opens.length && comma < 0) comma = i
  }
  return { comma, open: opens.length ? opens[opens.length - 1] : -1, quoted }
}

/** The command the caret is in, up to the caret, joined across `///`. */
function commandBefore(doc: string, pos: number): { text: string; comment: boolean } {
  const lineStart = doc.lastIndexOf('\n', pos - 1) + 1
  const current = doc.slice(lineStart, pos)
  const parts = [current]
  let at = lineStart - 1
  let continuing = false
  while (at > 0) {
    const start = doc.lastIndexOf('\n', at - 1) + 1
    const line = doc.slice(start, at)
    const marker = line.indexOf('///')
    if (marker < 0) break
    parts.unshift(line.slice(0, marker))
    continuing = true
    at = start - 1
  }
  const text = parts.join(' ')
  // A comment line, or past a // on this one.
  const commentLine = !continuing && current.trimStart().startsWith('*')
  let quoted = false
  for (let i = 0; i < current.length; i += 1) {
    if (current[i] === '"') quoted = !quoted
    else if (!quoted && current.startsWith('//', i)) return { text, comment: true }
  }
  return { text, comment: commentLine }
}

/** The variables a script has in memory at a point, as far as the text says.
 *
 *  Worked out by reading the commands above: `use` loads a dataset's, `merge`
 *  and `append` add another's, `gen` and `egen` add one, `rename`, `drop`,
 *  `keep` and `collapse` change the list. Nothing here has to be exact - it
 *  decides what is offered, not what is allowed - and where no `use` has
 *  been read yet, every variable in the project is offered.
 */
export function variablesAt(
  doc: string,
  pos: number,
  index: LanguageIndex,
): { name: string; label: string; from: string }[] | null {
  const lineNumber = doc.slice(0, pos).split('\n').length
  let scope: Map<string, { label: string; from: string }> | null = null
  const load = (name: string, into: Map<string, { label: string; from: string }>) => {
    const dataset = index.datasets.get(name.replace(/^"|"$/g, '').trim().toLowerCase())
    for (const variable of dataset?.variables ?? []) {
      if (!into.has(variable.name)) into.set(variable.name, { label: variable.label, from: dataset!.name })
    }
  }
  for (const command of commandsOf(doc)) {
    if (command.line >= lineNumber) break
    const commandText = withoutPrefix(command.text)
    const [verbWord = '', ...rest] = commandText.split(/\s+/)
    const verb = index.verbs.get(verbWord.toLowerCase().replace(/,$/, ''))?.name
    const body = commandText.slice(verbWord.length).trim()
    const { comma } = shape(body)
    const main = comma >= 0 ? body.slice(0, comma) : body
    const options = comma >= 0 ? body.slice(comma + 1) : ''
    const words = (text: string) => text.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? []
    if (verb === 'use') {
      scope = new Map()
      load(main, scope)
    } else if (!scope) {
      continue
    } else if (verb === 'merge' || verb === 'append') {
      const using = /\busing\s+("[^"]*"|\S+)/i.exec(main)
      if (using) load(using[1], scope)
      if (verb === 'merge' && !/\bnogen(erate)?\b/i.test(options)) scope.set('_merge', { label: 'Where each row came from', from: 'merge' })
    } else if (verb === 'gen' || verb === 'egen') {
      const name = main.split('=')[0].trim().split(/\s+/).pop()
      if (name) scope.set(name, { label: '', from: 'this script' })
    } else if (verb === 'rename' && rest.length >= 2) {
      const [old = '', fresh] = words(main)
      const was = scope.get(old)
      scope.delete(old)
      if (fresh) scope.set(fresh, was ?? { label: '', from: 'this script' })
    } else if ((verb === 'drop' || verb === 'keep') && !/^if\b/i.test(main)) {
      const named = new Set(words(main))
      for (const name of [...scope.keys()]) {
        if (named.has(name) === (verb === 'drop')) scope.delete(name)
      }
    } else if (verb === 'collapse') {
      const next = new Map<string, { label: string; from: string }>()
      const by = /\bby\s*\(([^)]*)\)/i.exec(options)
      for (const name of words(by?.[1] ?? '')) next.set(name, scope.get(name) ?? { label: '', from: 'this script' })
      for (const piece of main.replace(/\([^)]*\)/g, ' ').split(/\s+/)) {
        const name = piece.includes('=') ? piece.split('=')[0] : piece
        if (/^[A-Za-z_]\w*$/.test(name)) next.set(name, scope.get(name) ?? { label: '', from: 'this script' })
      }
      scope = next
    } else if (verb === 'contract') {
      const next = new Map<string, { label: string; from: string }>()
      for (const name of words(main)) next.set(name, scope.get(name) ?? { label: '', from: 'this script' })
      next.set('_freq', { label: 'How many rows', from: 'contract' })
      scope = next
    } else if (['destring', 'recode', 'duplicates', 'tostring', 'encode', 'decode'].includes(verb ?? '')) {
      const made = /\b(?:generate|gen|g)\s*\(([^)]*)\)/i.exec(options)
      for (const name of words(made?.[1] ?? '')) scope.set(name, { label: '', from: 'this script' })
      const prefix = verb === 'recode' ? /\bprefix\s*\(([^)]*)\)/i.exec(options)?.[1]?.trim() : ''
      if (prefix) {
        const recoded = words(main.split('(')[0])
        for (const name of recoded) scope.set(`${prefix}${name}`, { label: '', from: 'this script' })
      }
    } else if (verb === 'reshape') {
      const [direction = '', ...stubs] = words(main)
      const j = /(?<![\w])j\s*\(\s*([A-Za-z_]\w*)/i.exec(options)?.[1]
      if (direction.toLowerCase() === 'long') {
        for (const name of [...scope.keys()]) {
          if (stubs.some((stub) => name.startsWith(stub) && name.length > stub.length)) scope.delete(name)
        }
        for (const name of [...stubs, ...(j ? [j] : [])]) scope.set(name, { label: '', from: 'this script' })
      } else {
        // The new columns are named by the values of j, which the text does
        // not say; what goes is the stubs and j.
        for (const name of [...stubs, ...(j ? [j] : [])]) scope.delete(name)
      }
    }
  }
  if (!scope) return null
  return [...(scope as Map<string, { label: string; from: string }>).entries()].map(([name, about]) => ({ name, ...about }))
}

function variableSuggestions(doc: string, pos: number, index: LanguageIndex): Suggestion[] {
  const known = variablesAt(doc, pos, index)
  const listed = known ?? [...index.variables.entries()].map(([name, about]) => ({ name, label: about.label, from: about.dataset }))
  return listed.map((one) => ({
    label: one.name,
    type: 'variable' as const,
    detail: one.label || undefined,
    info: one.from ? `In ${one.from}` : undefined,
    boost: 1,
  }))
}

function functionSuggestions(index: LanguageIndex): Suggestion[] {
  return index.vocabulary.functions.map((one) => ({
    label: one.name,
    type: 'function' as const,
    detail: one.syntax,
    info: one.summary,
    insert: `${one.name}()`,
    caretBack: 1,
  }))
}

/** What accepting a suggestion changes: the text from `from` to `to`
 *  replaced, and where the caret lands.
 *
 *  A suggestion ending in a closing quote uses one already after the caret
 *  rather than adding a second. The editor types the closing quote along with
 *  the opening one, so `use "Hou` is really `use "Hou|"` - and a second quote
 *  made `use "Household roster""`, a name no dataset has.
 */
export function acceptChange(
  doc: string,
  from: number,
  to: number,
  suggestion: Suggestion,
): { from: number; to: number; insert: string; caret: number } {
  const insert = suggestion.insert ?? suggestion.label
  const end = insert.endsWith('"') && doc[to] === '"' ? to + 1 : to
  return { from, to: end, insert, caret: from + insert.length - (suggestion.caretBack ?? 0) }
}

function datasetSuggestions(index: LanguageIndex, quoted: boolean): Suggestion[] {
  const seen = new Set<DatasetNames>()
  const out: Suggestion[] = []
  for (const dataset of index.datasets.values()) {
    if (seen.has(dataset)) continue
    seen.add(dataset)
    const spaced = /\s/.test(dataset.name)
    out.push({
      label: dataset.name,
      type: 'class',
      detail: `${dataset.rows.toLocaleString()} rows · ${dataset.variables.length} variables`,
      // A name with a space in it is written in quotes; inside quotes already,
      // the closing one is what is missing.
      insert: quoted ? `${dataset.name}"` : spaced ? `"${dataset.name}"` : dataset.name,
    })
  }
  return out
}

function macroNames(doc: string, pos: number, kind: 'local' | 'global'): string[] {
  const above = doc.slice(0, pos)
  const pattern = new RegExp(`^\\s*${kind}\\s+([A-Za-z_][A-Za-z0-9_]*)`, 'gim')
  const found = [...above.matchAll(pattern)].map((match) => match[1])
  if (kind === 'local') {
    // A loop's name is a local inside it.
    const loops = /^\s*(?:foreach|forvalues|forval|forv)\s+([A-Za-z_][A-Za-z0-9_]*)/gim
    found.push(...[...above.matchAll(loops)].map((match) => match[1]))
  }
  return [...new Set(found)]
}

/** What to offer at the caret, or null for nothing. */
export function completeAt(doc: string, pos: number, index: LanguageIndex): Completion | null {
  const { text: whole, comment } = commandBefore(doc, pos)
  if (comment) return null
  // After `by hhid:`, the command it runs starts again.
  const prefixed = BY_PREFIX.test(whole)
  const before = withoutPrefix(whole)
  const word = /[A-Za-z_][A-Za-z0-9_]*$/.exec(before)?.[0] ?? ''
  const from = pos - word.length
  const head = before.slice(0, before.length - word.length)
  const validFor = /^[A-Za-z_][A-Za-z0-9_]*$/

  // A macro being named.
  if (head.endsWith('`')) {
    return { from, validFor, eager: true, options: macroNames(doc, pos, 'local').map((name) => ({ label: name, type: 'constant' as const, insert: `${name}'` })) }
  }
  if (head.endsWith('$')) {
    return { from, validFor, eager: true, options: macroNames(doc, pos, 'global').map((name) => ({ label: name, type: 'constant' as const })) }
  }

  const { comma, open, quoted } = shape(head)

  // Inside quotes there is nothing to offer, except a dataset being named.
  if (quoted) {
    const opened = head.lastIndexOf('"')
    if (/\b(use|using)\s*$/i.test(head.slice(0, opened))) {
      const typed = head.slice(opened + 1) + word
      return { from: pos - typed.length, eager: true, options: datasetSuggestions(index, true) }
    }
    return null
  }

  // The first word: a command - after a by prefix, one that can run in groups.
  if (!head.trim()) {
    const options: Suggestion[] = []
    const able = new Set(index.vocabulary.by_able ?? [])
    for (const command of index.vocabulary.commands) {
      if (prefixed && able.size && !able.has(command.name)) continue
      options.push({ label: command.name, type: 'keyword', detail: command.syntax, info: command.summary, boost: 2 })
      for (const alias of command.aliases) {
        if (alias.length > 2) options.push({ label: alias, type: 'keyword', detail: `as ${command.name}`, info: command.summary, boost: -1 })
      }
    }
    return { from, validFor, options }
  }

  const verbWord = head.trim().split(/\s+/)[0].replace(/,$/, '')
  const command = index.verbs.get(verbWord.toLowerCase())
  if (!command) return null
  const afterVerb = head.trim().slice(verbWord.length)
  const onlyVerb = !afterVerb.trim() && /\s$/.test(head)

  if (command.name === 'label' && onlyVerb) {
    return { from, validFor, eager: true, options: index.vocabulary.label_kinds.map((one) => ({ label: one.name, type: 'keyword' as const, info: one.summary })) }
  }
  const subcommands = index.vocabulary.subcommands?.[command.name]
  if (subcommands?.length && onlyVerb) {
    return { from, validFor, eager: true, options: subcommands.map((one) => ({ label: one.name, type: 'keyword' as const, info: one.summary })) }
  }
  if (command.name === 'forvalues') return null
  if (command.name === 'foreach') {
    // foreach <name> in|of <kind> <list> {
    const parts = afterVerb.trim().split(/\s+/).filter(Boolean)
    const ended = /\s$/.test(head)
    const words = index.vocabulary.loop_words ?? []
    const keyword = (names: string[]) =>
      words.filter((one) => names.includes(one.name)).map((one) => ({ label: one.name, type: 'keyword' as const, info: one.summary }))
    if (parts.length === 1 && ended) return { from, validFor, eager: true, options: keyword(['in', 'of']) }
    if (parts.length === 2 && parts[1] === 'of' && ended) {
      return { from, validFor, eager: true, options: keyword(['varlist', 'newlist', 'local', 'global', 'numlist']) }
    }
    if (parts.length === 3 && parts[1] === 'of' && (parts[2] === 'local' || parts[2] === 'global') && ended) {
      return { from, validFor, eager: true, options: macroNames(doc, pos, parts[2]).map((name) => ({ label: name, type: 'constant' as const })) }
    }
    if (!(parts[1] === 'of' && parts[2] === 'varlist')) return null
  }
  if (command.name === 'merge' && onlyVerb) {
    const typed = /[\w:]*$/.exec(before)?.[0] ?? ''
    return {
      from: pos - typed.length,
      eager: true,
      options: index.vocabulary.merge_shapes.map((one) => ({ label: one, type: 'constant' as const, info: one === 'm:1' ? 'Many rows here to one there' : one === '1:m' ? 'One row here to many there' : 'One row to one row' })),
    }
  }
  if (/\b(use|using)\s+$/i.test(head) && (command.name === 'use' || comma < 0)) {
    return { from, validFor, eager: true, options: datasetSuggestions(index, false) }
  }
  if (command.name === 'use' || command.name === 'save' || command.name === 'local' || command.name === 'global') {
    return null
  }

  // Inside brackets.
  if (open >= 0) {
    // The word the bracket belongs to: `by(`, `keep(`, `round(`. Written
    // against it, so `collapse (` - a statistic, after a space - names none.
    const named = /([A-Za-z_][A-Za-z0-9_]*)$/.exec(head.slice(0, open))?.[1]?.toLowerCase() ?? ''
    const inOptions = comma >= 0 && open > comma
    if (inOptions) {
      if (command.name === 'merge' && named === 'keep') {
        return { from, validFor, eager: true, options: index.vocabulary.merge_keep.map((one) => ({ label: one.name, type: 'constant' as const, info: one.summary })) }
      }
      // keepusing() names variables of the dataset being merged in, not of
      // the one in memory: merge checks them against that one, so a name
      // offered from memory is a name the run refuses.
      if (command.name === 'merge' && named === 'keepusing') {
        const using = /\busing\s+("[^"]*"|[^\s,]+)/i.exec(head.slice(0, comma))
        const other = using
          ? index.datasets.get(using[1].replace(/^"|"$/g, '').trim().toLowerCase())
          : undefined
        if (!other) return null
        return {
          from,
          validFor,
          eager: true,
          options: other.variables.map((one) => ({
            label: one.name,
            type: 'variable' as const,
            detail: one.label || undefined,
            info: `In ${other.name}`,
          })),
        }
      }
      if (['generate', 'gen', 'g', 'ignore'].includes(named)) return null
      return { from, validFor, eager: true, options: variableSuggestions(doc, pos, index) }
    }
    if (command.name === 'collapse' && !named) {
      return { from, validFor, eager: true, options: index.vocabulary.collapse.map((one) => ({ label: one.name, type: 'constant' as const, info: one.summary })) }
    }
    return { from, validFor, options: [...variableSuggestions(doc, pos, index), ...functionSuggestions(index)] }
  }

  // After the comma: the command's options.
  if (comma >= 0) {
    return {
      from,
      validFor,
      eager: true,
      options: command.options.map((one) => ({
        label: one.name,
        type: 'property' as const,
        info: one.summary,
        insert: one.takes_argument ? `${one.name}()` : one.name,
        caretBack: one.takes_argument ? 1 : 0,
      })),
    }
  }

  const equals = head.indexOf('=')
  if (command.name === 'egen') {
    if (equals < 0) return null
    if (/=\s*$/.test(head)) {
      return {
        from,
        validFor,
        eager: true,
        options: index.vocabulary.egen.map((one) => ({ label: one.name, type: 'function' as const, info: one.summary, insert: `${one.name}()`, caretBack: 1 })),
      }
    }
    return null
  }
  if (command.name === 'gen' && equals < 0) return null
  if (command.name === 'rename' && afterVerb.trim().split(/\s+/).filter(Boolean).length >= 1) return null

  const conditionWords: Suggestion[] =
    (command.name === 'drop' || command.name === 'keep') && onlyVerb
      ? [{ label: 'if', type: 'keyword', info: 'Rows where the condition holds', boost: 3 }]
      : []
  const withFunctions = equals >= 0 || /\bif\b/i.test(head) || command.name === 'assert'
  const rowNames = withFunctions
    ? (index.vocabulary.row_names ?? []).map((one) => ({ label: one.name, type: 'constant' as const, info: one.summary }))
    : []
  return {
    from,
    validFor,
    options: [
      ...conditionWords,
      ...variableSuggestions(doc, pos, index),
      ...rowNames,
      ...(withFunctions ? functionSuggestions(index) : []),
    ],
  }
}

// --- what a word is ---------------------------------------------------------

export interface Description {
  title: string
  body: string
}

/** What the word under the pointer is, for the help that hovers over it. */
export function describeAt(doc: string, pos: number, index: LanguageIndex): Description | null {
  const lineStart = doc.lastIndexOf('\n', pos - 1) + 1
  const lineEnd = doc.indexOf('\n', pos) < 0 ? doc.length : doc.indexOf('\n', pos)
  const line = doc.slice(lineStart, lineEnd)
  const at = pos - lineStart
  let start = at
  let end = at
  while (start > 0 && /\w/.test(line[start - 1])) start -= 1
  while (end < line.length && /\w/.test(line[end])) end += 1
  if (start === end) return null
  const word = line.slice(start, end)
  const lower = word.toLowerCase()
  const { text: before, comment } = commandBefore(doc, lineStart + start)
  if (comment) return null
  const head = withoutPrefix(before)
  const first = !head.trim()
  const verb = index.verbs.get(head.trim().split(/\s+/)[0]?.replace(/,$/, '').toLowerCase() ?? '')

  if (first) {
    const command = index.verbs.get(lower)
    return command ? { title: command.syntax, body: command.summary } : null
  }
  const row = index.vocabulary.row_names?.find((one) => one.name === word)
  if (row) return { title: row.name, body: row.summary }
  if (verb && head.trim().split(/\s+/).length === 1) {
    const form = index.vocabulary.subcommands?.[verb.name]?.find((one) => one.name === lower)
    if (form) return { title: `${verb.name} ${form.name}`, body: form.summary }
  }
  if (verb?.name === 'foreach') {
    const loopWord = index.vocabulary.loop_words?.find((one) => one.name === lower)
    if (loopWord) return { title: `foreach ... ${loopWord.name}`, body: loopWord.summary }
  }
  const { comma } = shape(head)
  if (comma >= 0 && verb) {
    const option = verb.options.find((one) => one.name === lower)
    if (option) return { title: `${verb.name}, ${option.name}${option.takes_argument ? '()' : ''}`, body: option.summary }
  }
  const call = line[end] === '('
  if (call && verb?.name === 'egen' && index.egen.has(lower)) {
    const egen = index.egen.get(lower)!
    return { title: `egen ${egen.name}()`, body: egen.summary }
  }
  if (call && index.functions.has(lower)) {
    const fn = index.functions.get(lower)!
    return { title: fn.syntax, body: fn.summary }
  }
  if (/\b(use|using)\s*"?$/i.test(head)) {
    const dataset = index.datasets.get(lower) ?? index.datasets.get(line.slice(start).split('"')[0].trim().toLowerCase())
    if (dataset) return { title: dataset.name, body: `Dataset · ${dataset.rows.toLocaleString()} rows · ${dataset.variables.length} variables` }
  }
  const variable = index.variables.get(word)
  if (variable) {
    return {
      title: word,
      body: [variable.label, `${variable.type || 'variable'} in ${variable.dataset}`].filter(Boolean).join(' · '),
    }
  }
  return null
}
