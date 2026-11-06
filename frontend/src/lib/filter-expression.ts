/**
 * A filter written out as an expression, the way a Survey Solutions condition
 * is: `sex == "Female" && age.InRange(15, 49) && IsAnswered(phone)`.
 *
 * The row-by-row builder is fine for one or two conditions and slow for more:
 * every bracket is a box, every "or" a dropdown, and something an analyst
 * would type in ten seconds takes a minute of clicking. An expression is what
 * anyone who has written a questionnaire condition already knows - C# with the
 * Survey Solutions helpers - so that is the syntax.
 *
 * It is not a second filter language. The text is read into exactly the
 * filter the builder makes, a group of conditions and nested groups, and that
 * is what is saved and what the server runs: the expression is another way of
 * writing it, and printing a saved filter gives the expression back. So a
 * filter written either way can be edited the other way, and nothing that
 * reads filters - queries, exports, quality checks - knows which was used.
 *
 * What it understands:
 *
 *   age >= 15, sex == 2, district != "North"     comparisons: == != > >= < <=
 *   a && b, a || b, !a, ( ... )                   and, or, not, brackets
 *                                                 (also the words and / or / not)
 *   x.InList(1, 2, 3)        is one of            x.InRange(15, 49)  between
 *   x.Contains("text")       contains             x.StartsWith("A")  x.EndsWith("z")
 *   IsAnswered(x)            is present           !IsAnswered(x)     is missing
 *   IsSelected(x)            a ticked option      x == null          is missing
 *   end_date < start_date    one column against another
 *   inc2020 - inc2019 > 100, total != boys + girls, (a - b) / b * 100 >= 10
 *                            arithmetic: + - * / and brackets, on either side
 *   x.OnOrAfter("2026-01-01"), x.Before("2026-02-01")   a date range
 *
 * A coded variable can be compared with its codes or its labels: `sex == 2`
 * and `sex == "Female"` are the same filter, and a saved filter is printed
 * with the labels, because that is what reads. A name that is not a plain word
 * is written in backticks: `my column`.
 */
import type { Condition, FilterGroup, FilterOperator, Variable } from '@/lib/types'

/** Why an expression could not be read, and where - for the underline. */
export class ExpressionError extends Error {
  from: number
  to: number
  constructor(message: string, from: number, to: number) {
    super(message)
    this.from = from
    this.to = Math.max(to, from + 1)
  }
}

export type ParseResult =
  | { ok: true; filter: FilterGroup }
  | { ok: false; error: ExpressionError }

// ---- tokens -----------------------------------------------------------------

type TokenKind = 'name' | 'quoted' | 'number' | 'string' | 'op' | 'punct' | 'end'

interface Token {
  kind: TokenKind
  /** The name, the string's contents, the number's digits, or the symbol. */
  text: string
  from: number
  to: number
}

const SYMBOLS = ['==', '!=', '>=', '<=', '&&', '||', '<>', '>', '<', '!', '=', '(', ')', ',', '.', '-', '+', '*', '/']

/** Every token in the text, or the first thing that is not one. */
export function tokenize(text: string): Token[] {
  const tokens: Token[] = []
  let at = 0
  while (at < text.length) {
    const char = text[at]
    if (/\s/.test(char)) {
      at++
      continue
    }
    const from = at
    if (/[A-Za-z_]/.test(char)) {
      while (at < text.length && /[A-Za-z0-9_]/.test(text[at])) at++
      tokens.push({ kind: 'name', text: text.slice(from, at), from, to: at })
      continue
    }
    if (/[0-9]/.test(char)) {
      while (at < text.length && /[0-9]/.test(text[at])) at++
      if (text[at] === '.' && /[0-9]/.test(text[at + 1] ?? '')) {
        at++
        while (at < text.length && /[0-9]/.test(text[at])) at++
      }
      tokens.push({ kind: 'number', text: text.slice(from, at), from, to: at })
      continue
    }
    if (char === '"' || char === "'" || char === '`') {
      at++
      let body = ''
      while (at < text.length && text[at] !== char) {
        if (text[at] === '\\' && at + 1 < text.length) {
          body += text[at + 1]
          at += 2
        } else {
          body += text[at++]
        }
      }
      if (at >= text.length) {
        throw new ExpressionError(
          char === '`' ? 'This name has no closing `' : `This text has no closing ${char}`,
          from,
          text.length,
        )
      }
      at++
      tokens.push({ kind: char === '`' ? 'quoted' : 'string', text: body, from, to: at })
      continue
    }
    const symbol = SYMBOLS.find((one) => text.startsWith(one, at))
    if (symbol) {
      at += symbol.length
      const kind = '(),.'.includes(symbol) ? 'punct' : 'op'
      tokens.push({ kind, text: symbol, from, to: at })
      continue
    }
    if (char === '&' || char === '|') {
      throw new ExpressionError(`Write ${char}${char}, not a single ${char}`, from, from + 1)
    }
    throw new ExpressionError(`"${char}" has no meaning here`, from, from + 1)
  }
  tokens.push({ kind: 'end', text: '', from: text.length, to: text.length })
  return tokens
}

// ---- the tree an expression reads as -----------------------------------------

type Logic =
  | { kind: 'and' | 'or'; items: Logic[] }
  | { kind: 'condition'; condition: Condition }

const COMPARE: Record<string, FilterOperator> = {
  '==': 'eq',
  '=': 'eq',
  '!=': 'ne',
  '<>': 'ne',
  '>': 'gt',
  '>=': 'gte',
  '<': 'lt',
  '<=': 'lte',
}

/** The comparison read the other way round: `5 < age` is `age > 5`. */
const MIRROR: Partial<Record<FilterOperator, FilterOperator>> = {
  eq: 'eq',
  ne: 'ne',
  gt: 'lt',
  gte: 'lte',
  lt: 'gt',
  lte: 'gte',
}

/** What `!` turns each operator into. Starts/ends with have no opposite. */
const OPPOSITE: Partial<Record<FilterOperator, FilterOperator>> = {
  eq: 'ne',
  ne: 'eq',
  gt: 'lte',
  lte: 'gt',
  gte: 'lt',
  lt: 'gte',
  in: 'not_in',
  not_in: 'in',
  contains: 'not_contains',
  not_contains: 'contains',
  is_null: 'is_not_null',
  is_not_null: 'is_null',
  selected: 'not_selected',
  not_selected: 'selected',
  on_or_after: 'before',
  before: 'on_or_after',
}

/** The methods written after a variable, by the operator each one makes. */
const METHODS: Record<string, { operator: FilterOperator; args: 'one' | 'two' | 'many' }> = {
  inlist: { operator: 'in', args: 'many' },
  inrange: { operator: 'between', args: 'two' },
  contains: { operator: 'contains', args: 'one' },
  startswith: { operator: 'starts_with', args: 'one' },
  endswith: { operator: 'ends_with', args: 'one' },
  onorafter: { operator: 'on_or_after', args: 'one' },
  before: { operator: 'before', args: 'one' },
}

/** The functions a variable is put inside. */
const FUNCTIONS: Record<string, FilterOperator> = {
  isanswered: 'is_not_null',
  isselected: 'selected',
}

/** Words that are not variable names unless written in backticks. */
const WORDS = new Set(['and', 'or', 'not', 'null', 'true', 'false'])

/** A label's code, matched as written and then ignoring case and spaces. */
function codeForLabel(variable: Variable, label: string): string | undefined {
  const labels = Object.entries(variable.value_labels ?? {})
  const exact = labels.find(([, shown]) => shown === label)
  if (exact) return exact[0]
  const plain = (text: string) => text.trim().toLowerCase()
  return labels.find(([, shown]) => plain(shown) === plain(label))?.[0]
}

/** The closest of the names to one that was mistyped, if any is close. */
function closest(name: string, names: string[]): string | undefined {
  const lower = name.toLowerCase()
  let best: string | undefined
  let bestScore = Infinity
  for (const candidate of names) {
    const score = distance(lower, candidate.toLowerCase())
    if (score < bestScore) {
      best = candidate
      bestScore = score
    }
  }
  return bestScore <= Math.max(1, Math.floor(name.length / 3)) ? best : undefined
}

function distance(a: string, b: string): number {
  const row = Array.from({ length: b.length + 1 }, (_, i) => i)
  for (let i = 1; i <= a.length; i++) {
    let previous = row[0]
    row[0] = i
    for (let j = 1; j <= b.length; j++) {
      const kept = row[j]
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, previous + (a[i - 1] === b[j - 1] ? 0 : 1))
      previous = kept
    }
  }
  return row[b.length]
}

class Reader {
  private at = 0
  private readonly byName: Map<string, Variable>
  private readonly byLower: Map<string, Variable[]>

  constructor(
    private readonly tokens: Token[],
    private readonly variables: Variable[],
  ) {
    this.byName = new Map(variables.map((one) => [one.name, one]))
    this.byLower = new Map()
    for (const one of variables) {
      const key = one.name.toLowerCase()
      this.byLower.set(key, [...(this.byLower.get(key) ?? []), one])
    }
  }

  private get next(): Token {
    return this.tokens[this.at]
  }

  private take(): Token {
    return this.tokens[this.at++]
  }

  private is(text: string): boolean {
    const token = this.next
    return (token.kind === 'op' || token.kind === 'punct') && token.text === text
  }

  private isWord(word: string): boolean {
    return this.next.kind === 'name' && this.next.text.toLowerCase() === word
  }

  private expect(text: string, what: string): Token {
    if (!this.is(text)) {
      const token = this.next
      throw new ExpressionError(
        token.kind === 'end' ? `Expected ${what} at the end` : `Expected ${what} here`,
        token.from,
        token.to,
      )
    }
    return this.take()
  }

  read(): Logic {
    const logic = this.or()
    const token = this.next
    if (token.kind !== 'end') {
      throw new ExpressionError(
        token.text === ')'
          ? 'This ) has no ( to close'
          : 'Expected && or || before this',
        token.from,
        token.to,
      )
    }
    return logic
  }

  private or(): Logic {
    const items = [this.and()]
    while (this.is('||') || this.isWord('or')) {
      this.take()
      items.push(this.and())
    }
    return items.length === 1 ? items[0] : { kind: 'or', items }
  }

  private and(): Logic {
    const items = [this.not()]
    while (this.is('&&') || this.isWord('and')) {
      this.take()
      items.push(this.not())
    }
    return items.length === 1 ? items[0] : { kind: 'and', items }
  }

  private not(): Logic {
    if (this.is('!') || this.isWord('not')) {
      const bang = this.take()
      return negate(this.not(), bang)
    }
    return this.primary()
  }

  private primary(): Logic {
    const token = this.next
    if (this.is('(')) {
      // A bracket is either a group of conditions - (a || b) - or the start
      // of a sum: (inc2020 - inc2019) / inc2019 > 1. It is read as a group
      // first, and read again as a sum if that fails or if what follows the
      // closing bracket carries on a sum or a comparison.
      const start = this.at
      let asGroup: ExpressionError | null = null
      try {
        this.take()
        if (this.is(')')) throw new ExpressionError('Nothing between these brackets', token.from, this.next.to)
        const inside = this.or()
        this.expect(')', 'a closing )')
        if (!this.continuesSum()) return inside
      } catch (error) {
        if (!(error instanceof ExpressionError)) throw error
        asGroup = error
      }
      this.at = start
      try {
        return this.comparison()
      } catch (error) {
        // Whichever reading got further said the more useful thing.
        if (asGroup && error instanceof ExpressionError && error.from < asGroup.from) throw asGroup
        throw error
      }
    }
    if (token.kind === 'end') {
      throw new ExpressionError(
        this.at === 0 ? 'Write a condition' : 'Expected a condition at the end',
        token.from,
        token.to,
      )
    }

    // IsAnswered(x), IsSelected(x), string.IsNullOrEmpty(x)
    const after = this.tokens[this.at + 1]
    if (token.kind === 'name' && after?.kind === 'punct' && after.text === '(') {
      const operator = FUNCTIONS[token.text.toLowerCase()]
      if (operator) {
        this.take()
        this.take()
        const variable = this.variable()
        this.expect(')', 'a closing )')
        return condition({ variable: variable.name, operator, value: null, use_label: false })
      }
    }
    if (
      token.kind === 'name' &&
      token.text === 'string' &&
      this.tokens[this.at + 1]?.text === '.' &&
      this.tokens[this.at + 2]?.text.toLowerCase() === 'isnullorempty'
    ) {
      this.at += 3
      this.expect('(', 'a (')
      const variable = this.variable()
      this.expect(')', 'a closing )')
      return condition({ variable: variable.name, operator: 'is_null', value: null, use_label: false })
    }
    return this.comparison()
  }

  /** Whether the next token carries on a sum or compares one. */
  private continuesSum(): boolean {
    const token = this.next
    return token.kind === 'op' && (token.text in COMPARE || ['+', '-', '*', '/'].includes(token.text))
  }

  /** Two sides and a comparison between them, or a variable and a method. */
  private comparison(): Logic {
    const left = this.side(false)
    if (this.is('.') && left.kind === 'sum' && left.sum.kind === 'var') {
      return this.method(left.sum.variable)
    }
    const compare = this.next
    const operator = COMPARE[compare.text]
    if (compare.kind !== 'op' || !operator) {
      const single = left.kind === 'sum' && left.sum.kind === 'var' ? left.sum.variable.name : null
      throw new ExpressionError(
        compare.kind === 'end'
          ? single
            ? `Expected a comparison after ${single}, such as == or >`
            : 'Expected a comparison at the end, such as == or >'
          : 'Expected a comparison such as == or > here',
        compare.from,
        compare.to,
      )
    }
    this.take()
    return this.compare(left, operator, this.side(true), compare)
  }

  /**
   * One side of a comparison: text in quotes, null, true or false, or a sum
   * of variables and numbers - which may be a single variable or a single
   * number. `compared` says it is the right-hand side, where a bare word is
   * more likely text that lost its quotes than a variable.
   */
  private side(compared: boolean): Side {
    const token = this.next
    if (token.kind === 'string') return { kind: 'value', literal: this.literal() }
    if (token.kind === 'name') {
      const word = token.text.toLowerCase()
      if (word === 'null') {
        this.take()
        return { kind: 'null', from: token.from, to: token.to }
      }
      if (word === 'true' || word === 'false') return { kind: 'value', literal: this.literal() }
    }
    return { kind: 'sum', sum: this.sum(compared) }
  }

  private sum(compared: boolean): Arith {
    let left = this.term(compared)
    while (this.is('+') || this.is('-')) {
      const op = this.take().text as '+' | '-'
      left = { kind: 'op', op, left, right: this.term(compared) }
    }
    return left
  }

  private term(compared: boolean): Arith {
    let left = this.factor(compared)
    while (this.is('*') || this.is('/')) {
      const op = this.take().text as '*' | '/'
      left = { kind: 'op', op, left, right: this.factor(compared) }
    }
    return left
  }

  private factor(compared: boolean): Arith {
    const token = this.next
    if (this.is('-')) {
      this.take()
      const item = this.factor(compared)
      return item.kind === 'num' && !item.text.startsWith('-')
        ? { ...item, text: `-${item.text}`, from: token.from }
        : { kind: 'neg', item }
    }
    if (this.is('(')) {
      this.take()
      const inside = this.sum(compared)
      this.expect(')', 'a closing )')
      return inside
    }
    if (token.kind === 'number') {
      this.take()
      return { kind: 'num', text: token.text, from: token.from, to: token.to }
    }
    if (token.kind === 'string') {
      throw new ExpressionError('A sum works on numbers - text cannot be part of one', token.from, token.to)
    }
    if (token.kind === 'name' || token.kind === 'quoted') {
      const variable = this.variable(compared)
      return { kind: 'var', variable, from: token.from, to: token.to }
    }
    throw new ExpressionError(
      token.kind === 'end' ? 'Expected a value at the end' : 'Expected a value here',
      token.from,
      token.to,
    )
  }

  /** x.InList(...), x.InRange(...), x.Contains(...) and the rest. */
  private method(variable: Variable): Logic {
    this.take()
    const method = this.next
    const known = method.kind === 'name' ? METHODS[method.text.toLowerCase()] : undefined
    if (!known) {
      throw new ExpressionError(
        'Expected InList, InRange, Contains, StartsWith or EndsWith after the dot',
        method.from,
        method.to,
      )
    }
    this.take()
    this.expect('(', 'a (')
    const values: Literal[] = []
    if (!this.is(')')) {
      values.push(this.literal())
      while (this.is(',')) {
        this.take()
        values.push(this.literal())
      }
    }
    const close = this.expect(')', 'a closing )')
    const wanted = { one: 1, two: 2, many: values.length || 1 }[known.args]
    if (values.length !== wanted) {
      const name = method.text
      throw new ExpressionError(
        known.args === 'two'
          ? `${name} takes two values, the lowest and the highest`
          : known.args === 'many'
            ? `${name} needs at least one value`
            : `${name} takes one value`,
        method.from,
        close.to,
      )
    }
    if (known.operator === 'in' || known.operator === 'between') {
      return condition({
        variable: variable.name,
        operator: known.operator,
        value: values.map((one) => this.code(variable, one)),
        use_label: false,
      })
    }
    return condition({ variable: variable.name, operator: known.operator, value: values[0].text, use_label: false })
  }

  /**
   * The condition two sides make.
   *
   * A variable against a value, null, or another variable is the condition
   * the builder makes, with a label read as its code. Anything with
   * arithmetic in it keeps the sum: `formula` for the left side and
   * `other_formula` for the right, a plain number staying the value. The
   * side with no variable in it goes on the right - `100 < inc2020 - inc2019`
   * is `inc2020 - inc2019 > 100`.
   */
  private compare(left: Side, operator: FilterOperator, right: Side, at: Token): Logic {
    const single = (side: Side) => (side.kind === 'sum' && side.sum.kind === 'var' ? side.sum.variable : null)

    if (left.kind === 'null' || right.kind === 'null') {
      const other = left.kind === 'null' ? right : left
      const variable = single(other)
      if (!variable) {
        throw new ExpressionError('Only a variable can be compared with null', at.from, at.to)
      }
      if (operator !== 'eq' && operator !== 'ne') {
        throw new ExpressionError('Only == and != can be used with null', at.from, at.to)
      }
      return condition({
        variable: variable.name,
        operator: operator === 'eq' ? 'is_null' : 'is_not_null',
        value: null,
        use_label: false,
      })
    }

    if (left.kind === 'value' && right.kind === 'value') {
      throw new ExpressionError('This compares two values - one side needs a variable', at.from, at.to)
    }
    if (left.kind === 'value' || right.kind === 'value') {
      const value = left.kind === 'value' ? left.literal : (right as { literal: Literal }).literal
      const other = left.kind === 'value' ? right : left
      const op = left.kind === 'value' ? (MIRROR[operator] as FilterOperator) : operator
      const variable = single(other)
      if (variable) {
        return condition({ variable: variable.name, operator: op, value: this.code(variable, value), use_label: false })
      }
      if (value.quoted || !/^-?\d+(\.\d+)?$/.test(value.text)) {
        throw new ExpressionError('A sum is compared with a number', value.from, value.to)
      }
      const sum = (other as { sum: Arith }).sum
      return condition({
        variable: this.firstVariable(sum).name,
        operator: op,
        value: value.text,
        use_label: false,
        formula: this.formulaText(sum),
      })
    }

    // Both sides are sums: put the one with a variable in it on the left.
    let [one, other, op] = [left.sum, right.sum, operator]
    if (!variablesOf(one).length) {
      if (!variablesOf(other).length) {
        throw new ExpressionError('Neither side names a variable', at.from, at.to)
      }
      ;[one, other, op] = [other, one, MIRROR[operator] as FilterOperator]
    }
    const made: Condition = {
      variable: this.firstVariable(one).name,
      operator: op,
      value: '',
      use_label: false,
    }
    if (one.kind !== 'var') made.formula = this.formulaText(one)
    if (other.kind === 'num') made.value = other.text
    else if (other.kind === 'var') made.other_variable = other.variable.name
    else if (!variablesOf(other).length) made.value = String(constant(other))
    else made.other_formula = this.formulaText(other)
    return condition(made)
  }

  private firstVariable(sum: Arith): Variable {
    return variablesOf(sum)[0].variable
  }

  /**
   * A sum as the server reads it: plain names, + - * / and brackets. A name
   * that is not a plain word cannot be written in one.
   */
  private formulaText(sum: Arith): string {
    for (const one of variablesOf(sum)) {
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(one.variable.name)) {
        throw new ExpressionError(
          `${one.variable.name} cannot be used in a sum - only names that are plain words can`,
          one.from,
          one.to,
        )
      }
    }
    return printSum(sum)
  }

  /**
   * A value as the filter stores it: a coded variable's label becomes its
   * code, which is what the builder's dropdown stores too.
   */
  private code(variable: Variable, value: Literal): string {
    if (!value.quoted || !value.text || !Object.keys(variable.value_labels ?? {}).length) return value.text
    const code = codeForLabel(variable, value.text)
    if (code !== undefined) return code
    if (value.text in (variable.value_labels ?? {})) return value.text
    const labels = Object.values(variable.value_labels ?? {})
    const near = closest(value.text, labels)
    throw new ExpressionError(
      near
        ? `${variable.name} has no label "${value.text}" - did you mean "${near}"?`
        : `${variable.name} has no label "${value.text}". Its labels are ${labels
            .slice(0, 6)
            .map((one) => `"${one}"`)
            .join(', ')}${labels.length > 6 ? ', …' : ''}`,
      value.from,
      value.to,
    )
  }

  private literal(): Literal {
    const token = this.next
    if (this.is('-')) {
      this.take()
      const number = this.next
      if (number.kind !== 'number') throw new ExpressionError('Expected a number after -', number.from, number.to)
      this.take()
      return { text: `-${number.text}`, quoted: false, from: token.from, to: number.to }
    }
    if (token.kind === 'number') {
      this.take()
      return { text: token.text, quoted: false, from: token.from, to: token.to }
    }
    if (token.kind === 'string') {
      this.take()
      return { text: token.text, quoted: true, from: token.from, to: token.to }
    }
    if (token.kind === 'name' && (token.text === 'true' || token.text === 'false')) {
      this.take()
      return { text: token.text, quoted: false, from: token.from, to: token.to }
    }
    if (token.kind === 'name') {
      throw new ExpressionError(
        `"${token.text}" is not a value here - put text in quotes: "${token.text}"`,
        token.from,
        token.to,
      )
    }
    throw new ExpressionError(
      token.kind === 'end' ? 'Expected a value at the end' : 'Expected a value here',
      token.from,
      token.to,
    )
  }

  /** A variable's name. `compared` says it stands where a value could have. */
  private variable(compared = false): Variable {
    const token = this.next
    if (token.kind !== 'name' && token.kind !== 'quoted') {
      throw new ExpressionError(
        token.kind === 'end' ? 'Expected a variable at the end' : 'Expected a variable here',
        token.from,
        token.to,
      )
    }
    this.take()
    const exact = this.byName.get(token.text)
    if (exact) return exact
    const loose = this.byLower.get(token.text.toLowerCase())
    if (loose?.length === 1) return loose[0]
    const near = closest(token.text, this.variables.map((one) => one.name))
    if (compared) {
      throw new ExpressionError(
        `There is no variable "${token.text}" - to compare with text, put it in quotes: "${token.text}"${
          near ? ` (or did you mean ${near}?)` : ''
        }`,
        token.from,
        token.to,
      )
    }
    throw new ExpressionError(
      near
        ? `There is no variable "${token.text}" - did you mean ${near}?`
        : `There is no variable "${token.text}"`,
      token.from,
      token.to,
    )
  }
}

interface Literal {
  text: string
  quoted: boolean
  from: number
  to: number
}

/** Arithmetic over variables and numbers, as read. */
type Arith =
  | { kind: 'num'; text: string; from: number; to: number }
  | { kind: 'var'; variable: Variable; from: number; to: number }
  | { kind: 'op'; op: '+' | '-' | '*' | '/'; left: Arith; right: Arith }
  | { kind: 'neg'; item: Arith }

/** One side of a comparison. */
type Side =
  | { kind: 'value'; literal: Literal }
  | { kind: 'null'; from: number; to: number }
  | { kind: 'sum'; sum: Arith }

function variablesOf(sum: Arith): { variable: Variable; from: number; to: number }[] {
  if (sum.kind === 'var') return [sum]
  if (sum.kind === 'num') return []
  if (sum.kind === 'neg') return variablesOf(sum.item)
  return [...variablesOf(sum.left), ...variablesOf(sum.right)]
}

/** A sum with no variables in it, worked out: `60 * 24` is 1440. */
function constant(sum: Arith): number {
  if (sum.kind === 'num') return Number(sum.text)
  if (sum.kind === 'neg') return -constant(sum.item)
  if (sum.kind === 'var') return NaN
  const [a, b] = [constant(sum.left), constant(sum.right)]
  return sum.op === '+' ? a + b : sum.op === '-' ? a - b : sum.op === '*' ? a * b : a / b
}

/** A sum written out, with brackets only where the order needs them. */
function printSum(sum: Arith, outer = 0, right = false): string {
  if (sum.kind === 'num') return sum.text
  if (sum.kind === 'var') return sum.variable.name
  if (sum.kind === 'neg') return `-${printSum(sum.item, 3)}`
  const rank = sum.op === '+' || sum.op === '-' ? 1 : 2
  const text = `${printSum(sum.left, rank)} ${sum.op} ${printSum(sum.right, rank, true)}`
  return rank < outer || (right && rank === outer) ? `(${text})` : text
}

function condition(one: Condition): Logic {
  if (!one.other_variable) delete one.other_variable
  if (!one.formula) delete one.formula
  if (!one.other_formula) delete one.other_formula
  return { kind: 'condition', condition: one }
}

/** `!` pushed down to the conditions, by swapping each for its opposite. */
function negate(logic: Logic, bang: Token): Logic {
  if (logic.kind !== 'condition') {
    return { kind: logic.kind === 'and' ? 'or' : 'and', items: logic.items.map((one) => negate(one, bang)) }
  }
  const { condition: one } = logic
  if (one.operator === 'between') {
    const [low, high] = one.value as string[]
    return {
      kind: 'or',
      items: [
        condition({ ...one, operator: 'lt', value: low }),
        condition({ ...one, operator: 'gt', value: high }),
      ],
    }
  }
  const opposite = OPPOSITE[one.operator]
  if (!opposite) {
    throw new ExpressionError(
      `! cannot go in front of ${one.operator === 'starts_with' ? 'StartsWith' : 'EndsWith'}: there is no "does not start with" filter`,
      bang.from,
      bang.to,
    )
  }
  return condition({ ...one, operator: opposite })
}

/** The tree as the filter the builder makes: and/or groups, flattened. */
function toGroup(logic: Logic): FilterGroup {
  if (logic.kind === 'condition') return { op: 'and', conditions: [logic.condition], groups: [] }
  const group: FilterGroup = { op: logic.kind, conditions: [], groups: [] }
  for (const item of logic.items) {
    if (item.kind === 'condition') group.conditions.push(item.condition)
    else if (item.kind === logic.kind) {
      const inner = toGroup(item)
      group.conditions.push(...inner.conditions)
      group.groups.push(...inner.groups)
    } else group.groups.push(toGroup(item))
  }
  return group
}

/**
 * The filter an expression says, or why it says nothing.
 *
 * Blank is the empty filter - every record - which is what clearing the
 * builder's last row gives.
 */
export function parseFilter(text: string, variables: Variable[]): ParseResult {
  if (!text.trim()) return { ok: true, filter: { op: 'and', conditions: [], groups: [] } }
  try {
    const tokens = tokenize(text)
    return { ok: true, filter: toGroup(new Reader(tokens, variables).read()) }
  } catch (error) {
    if (error instanceof ExpressionError) return { ok: false, error }
    throw error
  }
}

// ---- printing ------------------------------------------------------------------

const SYMBOL_OF: Partial<Record<FilterOperator, string>> = {
  eq: '==',
  ne: '!=',
  gt: '>',
  gte: '>=',
  lt: '<',
  lte: '<=',
}

/** A name as an expression writes it: bare if it is a plain word. */
export function printName(name: string): string {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(name) && !WORDS.has(name.toLowerCase())
    ? name
    : `\`${name.replace(/[`\\]/g, (one) => `\\${one}`)}\``
}

function quote(text: string): string {
  return `"${text.replace(/["\\]/g, (one) => `\\${one}`)}"`
}

/**
 * A stored value as an expression writes it.
 *
 * A code with a label of its own is written as the label - `sex == "Female"`
 * rather than `sex == 2` - unless two codes share that label, when the label
 * would not say which. A number is written bare, anything else in quotes.
 */
function printValue(value: unknown, variable: Variable | undefined, labelled: boolean): string {
  const text = value === null || value === undefined ? '' : String(value)
  if (labelled) return quote(text)
  const labels = variable?.value_labels ?? {}
  const label = labels[text]
  if (label !== undefined && Object.values(labels).filter((one) => one === label).length === 1) {
    return quote(label)
  }
  return /^-?\d+(\.\d+)?$/.test(text) ? text : quote(text)
}

function asList(value: unknown): unknown[] {
  if (Array.isArray(value)) return value
  if (value === null || value === undefined || value === '') return []
  return String(value)
    .split(',')
    .map((part) => part.trim())
}

/** One condition written out, as the builder shows a row it cannot edit. */
export function printConditionText(one: Condition, variables: Variable[]): string {
  return printCondition(one, new Map(variables.map((item) => [item.name, item])))
}

function printCondition(one: Condition, byName: Map<string, Variable>): string {
  const name = printName(one.variable)
  const variable = byName.get(one.variable)
  const labelled = Boolean(one.use_label)
  const value = (item: unknown) => printValue(item, variable, labelled)
  const symbol = SYMBOL_OF[one.operator]
  if ((one.formula || one.other_formula) && symbol) {
    const right = one.other_formula
      || (one.other_variable ? printName(one.other_variable) : String(one.value ?? ''))
    return `${one.formula || name} ${symbol} ${right}`
  }
  if (one.other_variable && symbol) return `${name} ${symbol} ${printName(one.other_variable)}`
  switch (one.operator) {
    case 'in':
      return `${name}.InList(${asList(one.value).map(value).join(', ')})`
    case 'not_in':
      return `!${name}.InList(${asList(one.value).map(value).join(', ')})`
    case 'between': {
      const [low = '', high = ''] = asList(one.value)
      return `${name}.InRange(${value(low)}, ${value(high)})`
    }
    case 'contains':
      return `${name}.Contains(${quote(String(one.value ?? ''))})`
    case 'not_contains':
      return `!${name}.Contains(${quote(String(one.value ?? ''))})`
    case 'starts_with':
      return `${name}.StartsWith(${quote(String(one.value ?? ''))})`
    case 'ends_with':
      return `${name}.EndsWith(${quote(String(one.value ?? ''))})`
    case 'on_or_after':
      return `${name}.OnOrAfter(${quote(String(one.value ?? ''))})`
    case 'before':
      return `${name}.Before(${quote(String(one.value ?? ''))})`
    case 'is_null':
      return `!IsAnswered(${name})`
    case 'is_not_null':
      return `IsAnswered(${name})`
    case 'selected':
      return `IsSelected(${name})`
    case 'not_selected':
      return `!IsSelected(${name})`
    default:
      return `${name} ${symbol ?? '=='} ${value(one.value)}`
  }
}

function printGroup(group: FilterGroup, byName: Map<string, Variable>, inside: boolean): string {
  const parts = [
    ...group.conditions.map((one) => printCondition(one, byName)),
    ...group.groups
      .map((one) => printGroup(one, byName, true))
      .filter(Boolean),
  ]
  const joined = parts.join(group.op === 'or' ? ' || ' : ' && ')
  return inside && parts.length > 1 ? `(${joined})` : joined
}

/** A saved filter written out as an expression. */
export function printFilter(filter: FilterGroup | null | undefined, variables: Variable[]): string {
  if (!filter) return ''
  return printGroup(filter, new Map(variables.map((one) => [one.name, one])), false)
}

// ---- suggestions -----------------------------------------------------------------

export interface Suggestion {
  label: string
  /** What goes in, when it differs from the label. */
  insert?: string
  detail?: string
  type: 'variable' | 'method' | 'function' | 'keyword' | 'text'
}

/** What the methods after a dot are, and what each one is for. */
export const METHOD_HELP: { name: string; insert: string; detail: string }[] = [
  { name: 'InList', insert: 'InList()', detail: 'is one of: x.InList(1, 2, 3)' },
  { name: 'InRange', insert: 'InRange()', detail: 'between, ends included: x.InRange(15, 49)' },
  { name: 'Contains', insert: 'Contains("")', detail: 'text contains' },
  { name: 'StartsWith', insert: 'StartsWith("")', detail: 'text starts with' },
  { name: 'EndsWith', insert: 'EndsWith("")', detail: 'text ends with' },
  { name: 'OnOrAfter', insert: 'OnOrAfter("")', detail: 'a date on or after a day' },
  { name: 'Before', insert: 'Before("")', detail: 'a date before a day' },
]

/**
 * What could come next at the caret, and where the word being replaced starts.
 *
 * After a dot: the methods. Inside quotes after a coded variable: its labels.
 * Anywhere else a word is being typed: the variables, and the two functions.
 */
export function suggestAt(
  text: string,
  caret: number,
  variables: Variable[],
): { from: number; options: Suggestion[] } | null {
  const before = text.slice(0, caret)

  // Inside an open string: the labels of the variable it is being compared to.
  const quotes = (before.match(/"/g) ?? []).length - (before.match(/\\"/g) ?? []).length
  if (quotes % 2 === 1) {
    const open = before.lastIndexOf('"')
    // The variable this text is compared with: the last name before it that
    // is not a method or inside an earlier string - `district` in both
    // `district == "` and `district.InList("North", "`.
    const plain = before.slice(0, open).replace(/"(?:[^"\\]|\\.)*"/g, '""')
    const names = [...plain.matchAll(/`([^`]+)`|([A-Za-z_][A-Za-z0-9_]*)/g)]
      .filter((found) => plain[(found.index ?? 0) - 1] !== '.')
      .map((found) => found[1] ?? found[2])
    const known = new Map(variables.map((one) => [one.name, one]))
    const variable = [...names].reverse().map((name) => known.get(name)).find(Boolean)
    const labels = Object.values(variable?.value_labels ?? {})
    if (!labels.length) return null
    return {
      from: open + 1,
      options: labels.map((label) => ({
        label,
        insert: label.replace(/["\\]/g, (one) => `\\${one}`),
        detail: variable?.name,
        type: 'text',
      })),
    }
  }

  const word = before.match(/[A-Za-z_][A-Za-z0-9_]*$/)
  const from = caret - (word?.[0].length ?? 0)
  if (text[from - 1] === '.') {
    return {
      from,
      options: METHOD_HELP.map((one) => ({ label: one.name, insert: one.insert, detail: one.detail, type: 'method' })),
    }
  }
  if (!word) return null
  return {
    from,
    options: [
      ...variables.map(
        (one): Suggestion => ({
          label: one.name,
          insert: printName(one.name),
          detail: one.label || undefined,
          type: 'variable',
        }),
      ),
      { label: 'IsAnswered', insert: 'IsAnswered()', detail: 'has an answer', type: 'function' },
      { label: 'IsSelected', insert: 'IsSelected()', detail: 'a ticked option', type: 'function' },
    ],
  }
}
