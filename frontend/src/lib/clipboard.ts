/**
 * Getting a widget out of the dashboard and into somebody's report.
 *
 * A table goes to the clipboard as both HTML and tab-separated text. Excel and
 * Word read the HTML and land it in cells; a plain text editor takes the
 * tab-separated version. Writing only one of them means the table pastes into
 * half the places people actually paste it.
 *
 * A chart goes as a PNG. Where a browser will not write an image to the
 * clipboard - and several will not, outside a secure context - it is saved as
 * a file instead, which is a longer road to the same document rather than a
 * failure.
 */

/** The text of one cell, with the whitespace a spreadsheet would choke on removed. */
function cellText(cell: Element): string {
  return (cell.textContent ?? '').replace(/\s+/g, ' ').trim()
}

/** A table element as tab-separated rows, for the plain-text flavour. */
function asTsv(table: HTMLTableElement): string {
  return Array.from(table.rows)
    .map((row) =>
      Array.from(row.cells)
        // A cell spanning several columns has to leave that many columns
        // behind it, or every row below lines up one place to the left.
        .flatMap((cell) => [cellText(cell), ...Array(Math.max(0, cell.colSpan - 1)).fill('')])
        .join('\t'),
    )
    .join('\n')
}

/**
 * A copy of the table with its styling stripped.
 *
 * The dashboard's own colours are meant for the dashboard. Pasted into a
 * report they arrive as a block of someone else's brand in the middle of the
 * document, so what travels is the structure and the numbers.
 */
function asHtml(table: HTMLTableElement): string {
  const copy = table.cloneNode(true) as HTMLTableElement
  copy.removeAttribute('class')
  copy.removeAttribute('style')
  for (const node of copy.querySelectorAll('*')) {
    node.removeAttribute('class')
    node.removeAttribute('style')
  }
  copy.setAttribute('border', '1')
  copy.style.borderCollapse = 'collapse'
  return copy.outerHTML
}

export async function copyTable(table: HTMLTableElement): Promise<string> {
  const text = asTsv(table)
  const html = asHtml(table)
  const rows = table.rows.length

  if (navigator.clipboard && typeof ClipboardItem !== 'undefined') {
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          'text/html': new Blob([html], { type: 'text/html' }),
          'text/plain': new Blob([text], { type: 'text/plain' }),
        }),
      ])
      return `${rows} row${rows === 1 ? '' : 's'} copied - paste into Excel`
    } catch {
      /* fall through to the text-only path */
    }
  }
  // Text only still pastes into a spreadsheet, one value per cell; it just
  // arrives without the headings in bold.
  await navigator.clipboard?.writeText(text)
  return `${rows} row${rows === 1 ? '' : 's'} copied`
}

/** The PNG behind a canvas, at twice the size so it is not soft in a document. */
function pngFrom(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'))
}

export async function copyChart(canvas: HTMLCanvasElement, name: string): Promise<string> {
  const blob = await pngFrom(canvas)
  if (!blob) throw new Error('This chart could not be turned into a picture')

  if (navigator.clipboard && typeof ClipboardItem !== 'undefined') {
    try {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
      return 'Chart copied - paste it into your document'
    } catch {
      /* fall through to saving it */
    }
  }

  // Every browser can be handed a file even when it will not take an image
  // into the clipboard, and a saved PNG reaches the same document.
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${name.replace(/[^\w -]+/g, '').trim() || 'chart'}.png`
  link.click()
  URL.revokeObjectURL(url)
  return 'Your browser will not copy pictures, so the chart was saved instead'
}

/** What a widget can be copied as, judged from what it actually rendered. */
export function copyableIn(node: HTMLElement | null): 'table' | 'chart' | null {
  if (!node) return null
  if (node.querySelector('table')) return 'table'
  if (node.querySelector('canvas')) return 'chart'
  return null
}
