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

/**
 * Put text on the clipboard, on a plain HTTP deployment as well as on HTTPS.
 *
 * `navigator.clipboard` exists only in a secure context - HTTPS, or localhost.
 * A platform installed on a ministry LAN and reached at http://10.0.0.4 has no
 * such thing, and every copy button in the interface used to be written as
 * `navigator.clipboard?.writeText(text).then(...)`. Optional chaining
 * short-circuits the whole chain, so on those deployments that expression was
 * `undefined`: nothing was copied, no handler ran, and no error was raised
 * either. The button did nothing at all, silently, which is the hardest kind
 * of broken to report.
 *
 * The old way still works everywhere: a textarea off screen, selected, and
 * `execCommand`. It is deprecated and it is what the deprecation replaced it
 * with cannot do, so it stays as the fallback.
 */
function copyNow(text: string, html?: string): boolean {
  let holder: HTMLTextAreaElement | null = null
  const dress = (event: ClipboardEvent) => {
    if (!event.clipboardData) return
    // Both flavours from the one copy: Excel and Word read the HTML and land
    // the table in cells, a plain editor takes the tab-separated version.
    if (html) event.clipboardData.setData('text/html', html)
    event.clipboardData.setData('text/plain', text)
    event.preventDefault()
  }
  try {
    // Something has to be selected or execCommand does nothing at all, so the
    // text goes into a textarea off screen. Off screen rather than hidden: a
    // display:none element cannot be selected, and the page must not scroll.
    holder = document.createElement('textarea')
    holder.value = text
    holder.setAttribute('readonly', '')
    holder.style.position = 'fixed'
    holder.style.top = '-1000px'
    holder.style.opacity = '0'
    document.body.appendChild(holder)
    holder.select()
    holder.setSelectionRange(0, text.length)
    document.addEventListener('copy', dress, true)
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    document.removeEventListener('copy', dress, true)
    holder?.remove()
  }
}

export async function copyText(text: string): Promise<boolean> {
  if (copyNow(text)) return true
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      /* nothing else to try */
    }
  }
  return false
}

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
  const done = `${rows} row${rows === 1 ? '' : 's'} copied - paste into Excel`

  // The synchronous way first, and not as a fallback.
  //
  // A browser only allows a copy while the click that asked for it is still
  // the thing being handled. The asynchronous clipboard API is allowed to take
  // its time, so trying it first and falling back meant the fallback ran after
  // several awaits, by which point the permission it needed was gone - and a
  // refused copy reports nothing, so the button looked simply dead. This path
  // asks for nothing, needs no secure context, and carries the HTML that makes
  // a table arrive in cells.
  if (copyNow(text, html)) return done

  if (navigator.clipboard && typeof ClipboardItem !== 'undefined') {
    try {
      await navigator.clipboard.write([
        new ClipboardItem({
          'text/html': new Blob([html], { type: 'text/html' }),
          'text/plain': new Blob([text], { type: 'text/plain' }),
        }),
      ])
      return done
    } catch {
      /* one last try, plain text only */
    }
  }
  if (!(await copyText(text))) {
    throw new Error('This browser would not let the table be copied')
  }
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
