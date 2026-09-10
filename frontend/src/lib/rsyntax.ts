/**
 * A small R tokeniser, for colouring the script boxes.
 *
 * Written rather than installed. A highlighter is the only thing the platform
 * would have pulled a code editor in for, and CodeMirror is fifteen packages
 * and a bundle to serve a survey office that may be on a slow line. R is also
 * peculiar enough - `<-`, `%in%`, backtick names, `NA_character_` - that a
 * generic "r-like" mode gets several of them wrong anyway.
 *
 * One pass, longest match first, no backtracking: the scanner walks the source
 * once and every branch consumes at least one character, so it cannot hang on
 * a pathological line.
 */

export type TokenKind =
  | 'comment'
  | 'string'
  | 'number'
  | 'keyword'
  | 'constant'
  | 'call'
  | 'operator'
  | 'assign'
  | 'punctuation'
  | 'identifier'
  | 'text'

export interface Token {
  kind: TokenKind
  text: string
}

/** Control flow. `function` is here rather than with the calls on purpose. */
const KEYWORDS = new Set([
  'if',
  'else',
  'repeat',
  'while',
  'function',
  'for',
  'next',
  'break',
  'in',
])

/** The values that are spelled, not computed. */
const CONSTANTS = new Set([
  'TRUE',
  'FALSE',
  'NULL',
  'NA',
  'NA_integer_',
  'NA_real_',
  'NA_character_',
  'Inf',
  'NaN',
  'T',
  'F',
])

/**
 * The assignment arrows, longest first.
 *
 * `<-` has to be tried before `<`, or every assignment in the file reads as a
 * comparison followed by a minus.
 */
const ASSIGNMENT = ['<<-', '->>', '<-', '->', '=']

/** Everything else that is punctuation with a meaning. Longest first, again. */
const OPERATORS = [
  '%/%',
  '%%',
  '%*%',
  '%o%',
  ':::',
  '::',
  '...',
  '==',
  '!=',
  '<=',
  '>=',
  '&&',
  '||',
  '|>',
  '**',
  '~',
  '+',
  '-',
  '*',
  '/',
  '^',
  '<',
  '>',
  '!',
  '&',
  '|',
  '?',
  ':',
  '@',
  '$',
]

const PUNCTUATION = new Set(['(', ')', '{', '}', '[', ']', ',', ';'])

const IDENTIFIER_START = /[A-Za-z.]/
const IDENTIFIER_REST = /[A-Za-z0-9._]/
const DIGIT = /[0-9]/
const SPACE = /\s/

/** True when only whitespace stands between here and an opening bracket. */
function callAhead(source: string, from: number): boolean {
  let at = from
  while (at < source.length && SPACE.test(source[at])) at += 1
  return source[at] === '('
}

/** A special operator: %in%, %o%, or anybody's own %...%. */
function readSpecial(source: string, from: number): number {
  const close = source.indexOf('%', from + 1)
  // An unclosed % is a stray character, not an operator running to the end of
  // the file - and a newline inside one means the same thing.
  if (close < 0) return -1
  const body = source.slice(from + 1, close)
  return body.includes('\n') ? -1 : close + 1
}

/** A quoted run, honouring backslash escapes, and unterminated at end of input. */
function readQuoted(source: string, from: number, quote: string): number {
  let at = from + 1
  while (at < source.length) {
    if (source[at] === '\\') {
      at += 2
      continue
    }
    if (source[at] === quote) return at + 1
    at += 1
  }
  return source.length
}

/** A number, including hex, the L and i suffixes, and exponents. */
function readNumber(source: string, from: number): number {
  let at = from
  if (source[at] === '0' && (source[at + 1] === 'x' || source[at + 1] === 'X')) {
    at += 2
    while (at < source.length && /[0-9a-fA-F]/.test(source[at])) at += 1
  } else {
    while (at < source.length && DIGIT.test(source[at])) at += 1
    if (source[at] === '.') {
      at += 1
      while (at < source.length && DIGIT.test(source[at])) at += 1
    }
    if (source[at] === 'e' || source[at] === 'E') {
      let after = at + 1
      if (source[after] === '+' || source[after] === '-') after += 1
      if (DIGIT.test(source[after] ?? '')) {
        at = after
        while (at < source.length && DIGIT.test(source[at])) at += 1
      }
    }
  }
  if (source[at] === 'L' || source[at] === 'i') at += 1
  return at
}

/** Split R source into coloured runs. Every character of the input comes back. */
export function tokenise(source: string): Token[] {
  const tokens: Token[] = []
  let at = 0

  const push = (kind: TokenKind, text: string) => {
    // Runs of the same kind are merged, which keeps the span count down on a
    // long script without changing what is drawn.
    const last = tokens[tokens.length - 1]
    if (last && last.kind === kind) last.text += text
    else tokens.push({ kind, text })
  }

  while (at < source.length) {
    const char = source[at]

    // Comments run to the end of the line, and swallow everything on the way.
    if (char === '#') {
      const end = source.indexOf('\n', at)
      const stop = end < 0 ? source.length : end
      push('comment', source.slice(at, stop))
      at = stop
      continue
    }

    if (char === '"' || char === "'") {
      const end = readQuoted(source, at, char)
      push('string', source.slice(at, end))
      at = end
      continue
    }

    // A backtick name is an identifier that happens to need quoting, so it is
    // coloured as one rather than as a string.
    if (char === '`') {
      const end = readQuoted(source, at, '`')
      push('identifier', source.slice(at, end))
      at = end
      continue
    }

    if (char === '%') {
      const end = readSpecial(source, at)
      if (end > 0) {
        push('operator', source.slice(at, end))
        at = end
        continue
      }
    }

    // A leading dot can begin a name (.susodash) or a number (.5), so the
    // digit after it decides.
    if (DIGIT.test(char) || (char === '.' && DIGIT.test(source[at + 1] ?? ''))) {
      const end = readNumber(source, at)
      push('number', source.slice(at, end))
      at = end
      continue
    }

    if (IDENTIFIER_START.test(char)) {
      let end = at + 1
      while (end < source.length && IDENTIFIER_REST.test(source[end])) end += 1
      const word = source.slice(at, end)
      if (KEYWORDS.has(word)) push('keyword', word)
      else if (CONSTANTS.has(word)) push('constant', word)
      else if (callAhead(source, end)) push('call', word)
      else push('identifier', word)
      at = end
      continue
    }

    const assignment = ASSIGNMENT.find((op) => source.startsWith(op, at))
    if (assignment) {
      push('assign', assignment)
      at += assignment.length
      continue
    }

    const operator = OPERATORS.find((op) => source.startsWith(op, at))
    if (operator) {
      push('operator', operator)
      at += operator.length
      continue
    }

    if (PUNCTUATION.has(char)) {
      push('punctuation', char)
      at += 1
      continue
    }

    push('text', char)
    at += 1
  }

  return tokens
}

/**
 * The class each kind is drawn with.
 *
 * Defined here rather than inline so the editor and the read-only snippets
 * cannot drift apart, and so both themes are decided in one place. See the
 * `.r-syntax` block in index.css for the colours themselves.
 */
export const TOKEN_CLASS: Record<TokenKind, string> = {
  comment: 'r-comment',
  string: 'r-string',
  number: 'r-number',
  keyword: 'r-keyword',
  constant: 'r-constant',
  call: 'r-call',
  operator: 'r-operator',
  assign: 'r-assign',
  punctuation: 'r-punctuation',
  identifier: '',
  text: '',
}
