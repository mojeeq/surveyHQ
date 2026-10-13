/**
 * Reading a pasted list of quotas.
 *
 * A census has a quota per enumeration area and two thousand of them. Nobody
 * types that into two thousand boxes: the list already exists, in a
 * spreadsheet, and the way it gets here is a copy and a paste. So this takes
 * whatever comes off a clipboard and turns it into {category: target}.
 *
 * Two shapes, because both are what people actually paste:
 *
 *   **A pair per line** - "EA0508,346" or "EA0508<tab>346". The category and
 *   its quota, in either order of columns as long as the quota is the number.
 *
 *   **One column of numbers** - just the quotas, in the order the categories
 *   are listed on screen. This is what you get selecting a single spreadsheet
 *   column, and it is only safe because the list on screen is sorted and the
 *   spreadsheet was sorted the same way; the form says which category each
 *   number landed on so a reader can see it went where they meant.
 *
 * Nothing here talks to the server. A paste of two thousand rows is parsed,
 * counted and checked against the dataset's own values before anything is
 * saved, because a list that silently matched nothing would be worse than a
 * refusal.
 */

export interface ParsedRow {
  category: string
  target: number
}

export interface Parsed {
  rows: ParsedRow[]
  /** Lines that held no number, and so were passed over. */
  skipped: string[]
  /** A header line that was recognised and dropped. */
  header: string
}

/**
 * One line as a category and its quota, or as a single field.
 *
 * The comma is two things at once in this data: the column break and the
 * thousands separator, so "EA0508,15,040" is one area with a quota of 15,040
 * and not an area called "EA0508,15". It is read by taking the earliest break
 * whose right-hand side is a number, which gets that line right and leaves
 * "Shefa, North,120" - a category with a comma in it, unquoted - right too.
 */
function split(line: string): string[] {
  if (line.includes('\t')) return twoOf(line.split('\t'))
  if (line.includes(';')) return twoOf(line.split(';'))
  if (line.includes(',')) {
    const fields = splitCsv(line)
    if (fields.length === 2) return fields
    for (let at = 1; at < fields.length; at += 1) {
      const tail = fields.slice(at).join(',')
      if (asNumber(tail) !== null) return [fields.slice(0, at).join(','), tail]
    }
    return twoOf(fields)
  }
  // One column, or a category and a number with a space between them.
  const spaced = line.trim().match(/^(.*\S)\s+(\S+)$/)
  return spaced ? [spaced[1], spaced[2]] : [line]
}

/** Everything but the last field as the category, the last as the quota. */
function twoOf(fields: string[]): string[] {
  if (fields.length < 2) return fields
  return [fields.slice(0, -1).join(' '), fields[fields.length - 1]]
}

/** A comma-separated line, honouring quotes so "Shefa, North",120 survives. */
function splitCsv(line: string): string[] {
  const fields: string[] = []
  let field = ''
  let quoted = false
  for (let at = 0; at < line.length; at += 1) {
    const char = line[at]
    if (char === '"') {
      // A doubled quote inside a quoted field is one quote.
      if (quoted && line[at + 1] === '"') {
        field += '"'
        at += 1
      } else {
        quoted = !quoted
      }
    } else if (char === ',' && !quoted) {
      fields.push(field)
      field = ''
    } else {
      field += char
    }
  }
  fields.push(field)
  return fields
}

/** A number as a spreadsheet writes one: 1,234 and 1 234 and 1234.0 are one. */
export function asNumber(text: string): number | null {
  const cleaned = String(text ?? '')
    .replace(/[\s'’]/g, '')
    .replace(/,(?=\d{3}\b)/g, '')
    .trim()
  if (!cleaned) return null
  const number = Number(cleaned)
  return Number.isFinite(number) ? number : null
}

function clean(text: string): string {
  const trimmed = String(text ?? '').trim()
  // Excel quotes a field that holds a comma, and the quotes are not the value.
  return trimmed.replace(/^"(.*)"$/s, '$1').trim()
}

/**
 * A pasted block as rows of category and quota.
 *
 * `order` is the categories as the screen lists them, used only by the
 * one-column shape. Without it a single column has nothing to attach to and
 * comes back empty rather than guessing.
 */
export function parsePasted(text: string, order: string[] = []): Parsed {
  const lines = String(text ?? '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  if (!lines.length) return { rows: [], skipped: [], header: '' }

  const parts = lines.map(split)
  const pairs = parts.some((fields) => fields.length > 1)

  let header = ''
  let body = parts
  if (pairs) {
    // A header is a first line whose number column is not a number. Dropped
    // rather than reported, because "EA_Id,target" is not a mistake.
    const first = body[0]
    if (first.length > 1 && asNumber(first[1]) === null) {
      header = lines[0]
      body = body.slice(1)
    }
  }

  const rows: ParsedRow[] = []
  const skipped: string[] = []
  const seen = new Map<string, number>()

  body.forEach((fields, index) => {
    if (pairs) {
      const target = asNumber(fields[1] ?? '')
      const category = clean(fields[0] ?? '')
      if (target === null || !category) {
        skipped.push(lines[index + (header ? 1 : 0)])
        return
      }
      seen.set(category, target)
      return
    }
    // One column: the numbers land on the categories in the order given.
    const target = asNumber(fields[0])
    const category = order[index]
    if (target === null || category === undefined) {
      skipped.push(lines[index])
      return
    }
    seen.set(category, target)
  })

  for (const [category, target] of seen) rows.push({ category, target })
  return { rows, skipped, header }
}

export interface Match {
  /** Pasted categories that are values the data actually holds. */
  matched: string[]
  /** Pasted categories the data has no such value for. */
  unknown: string[]
  /** Values in the data that the paste said nothing about. */
  missing: string[]
}

/**
 * What a pasted list has to say about the data it is for.
 *
 * Excel drops the leading zero from 0508 and a quota list keyed 508 against
 * data keyed 0508 matches nothing at all - silently, at two thousand rows.
 * So the paste is held up against the variable's own values and the three
 * answers are reported before anything is saved.
 */
export function matchAgainst(categories: string[], values: string[]): Match {
  const known = new Set(values.map((value) => String(value)))
  const pasted = new Set(categories.map((category) => String(category)))
  return {
    matched: categories.filter((category) => known.has(String(category))),
    unknown: categories.filter((category) => !known.has(String(category))),
    missing: values.map(String).filter((value) => !pasted.has(value)),
  }
}
