/**
 * Help: the platform's documentation, in the platform.
 *
 * The content is not written here. It is the markdown in docs/, rendered to
 * HTML at build time by scripts/build-help.mjs, which is the whole point: a
 * Help page written by hand would be a second copy of the documentation, and a
 * second copy is wrong by the next release - which is worse than no help page,
 * because somebody trusts it.
 *
 * So this file is only the way around it: a list of documents, an outline of
 * the one being read, and a search across every section of all of them.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { PageHeader } from '@/components/ui'
import { HELP_DOCUMENTS, type HelpDocument } from '@/help/content.generated'
import '@/help/help.css'

/** A section of a document that matched what was typed. */
interface Hit {
  doc: HelpDocument
  sectionId: string
  sectionTitle: string
  snippet: string
}

/** Enough words either side of the match to see why it matched. */
function snippetAround(text: string, term: string): string {
  const at = text.toLowerCase().indexOf(term)
  if (at < 0) return text.slice(0, 160)
  const from = Math.max(0, at - 70)
  const to = Math.min(text.length, at + term.length + 110)
  return (from > 0 ? '…' : '') + text.slice(from, to).trim() + (to < text.length ? '…' : '')
}

/** The snippet with the term marked, as parts rather than as HTML. */
function marked(snippet: string, term: string) {
  const parts: { text: string; hit: boolean }[] = []
  let rest = snippet
  let guard = 0
  while (rest && guard < 40) {
    const at = rest.toLowerCase().indexOf(term)
    if (at < 0) break
    if (at > 0) parts.push({ text: rest.slice(0, at), hit: false })
    parts.push({ text: rest.slice(at, at + term.length), hit: true })
    rest = rest.slice(at + term.length)
    guard += 1
  }
  if (rest) parts.push({ text: rest, hit: false })
  return parts
}

export default function Help() {
  const { docId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useState('')
  const body = useRef<HTMLDivElement>(null)

  // Every document, to every reader. Ordering does the work that hiding was
  // doing: the everyday guides come first.
  const documents = HELP_DOCUMENTS

  const current = documents.find((doc) => doc.id === docId) ?? documents[0]
  const term = query.trim().toLowerCase()

  const hits = useMemo<Hit[]>(() => {
    if (term.length < 2) return []
    const found: Hit[] = []
    for (const doc of documents) {
      for (const section of doc.sections) {
        const haystack = `${section.title}\n${section.text}`.toLowerCase()
        if (!haystack.includes(term)) continue
        found.push({
          doc,
          sectionId: section.id,
          sectionTitle: section.title,
          snippet: snippetAround(
            section.text || section.title,
            term,
          ),
        })
        if (found.length >= 60) return found
      }
    }
    return found
  }, [documents, term])

  // A link inside the rendered documentation is an ordinary anchor, so a
  // cross-reference to another document would reload the whole application.
  // Caught here and handed to the router instead, which is also what keeps
  // the reader's place in the sidebar.
  useEffect(() => {
    const container = body.current
    if (!container) return
    const onClick = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement).closest('a')
      if (!anchor) return
      const href = anchor.getAttribute('href') || ''
      if (href.startsWith('/help/')) {
        event.preventDefault()
        navigate(href)
      } else if (href.startsWith('#')) {
        event.preventDefault()
        document.getElementById(href.slice(1))?.scrollIntoView({ behavior: 'smooth' })
      }
    }
    container.addEventListener('click', onClick)
    return () => container.removeEventListener('click', onClick)
  }, [navigate])

  // Jump to the anchor once the document holding it is on the page. Without
  // the frame the element does not exist yet, because this runs on the render
  // that put it there.
  //
  // Keyed on the hash rather than on the document, because the case that
  // matters most is a search hit pointing into the document already open: the
  // id does not change then, and an effect watching only that never fires, so
  // the result opened the right page and left the reader at the top of it.
  // location.key changes on every navigation, which also covers clicking the
  // same result twice.
  useEffect(() => {
    if (!location.hash) {
      window.scrollTo({ top: 0 })
      return
    }
    const id = decodeURIComponent(location.hash.slice(1))
    const frame = requestAnimationFrame(() =>
      document.getElementById(id)?.scrollIntoView({ block: 'start' }),
    )
    return () => cancelAnimationFrame(frame)
  }, [current?.id, location.hash, location.key])

  const open = (doc: string, section?: string) => {
    setQuery('')
    navigate(`/help/${doc}${section ? `#${section}` : ''}`)
  }

  if (!current) {
    return (
      <>
        <PageHeader title="Help" description="No documentation is bundled with this build." />
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Help"
        description="Everything the platform does, from the same documentation that ships with it."
      />

      <div className="mt-4 grid gap-6 lg:grid-cols-[230px_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-4 lg:self-start">
          <label className="sr-only" htmlFor="help-search">
            Search the documentation
          </label>
          <input
            id="help-search"
            className="input"
            type="search"
            placeholder="Search all help"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoComplete="off"
          />

          <nav className="mt-4" aria-label="Documents">
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-400">
              Documents
            </p>
            <ul className="space-y-0.5">
              {documents.map((doc) => (
                <li key={doc.id}>
                  <button
                    type="button"
                    onClick={() => open(doc.id)}
                    className={`w-full rounded-lg px-2.5 py-1.5 text-left text-sm transition ${
                      doc.id === current.id
                        ? 'bg-brand-50 font-semibold text-brand-800 dark:bg-dark-200 dark:text-brand-300'
                        : 'text-ink-600 hover:bg-ink-100 dark:hover:bg-dark-200'
                    }`}
                  >
                    {doc.title}
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          {!term && current.headings.length > 0 && (
            <nav className="mt-5 border-t border-ink-200 pt-4 dark:border-dark-200" aria-label="On this page">
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-400">
                On this page
              </p>
              {/* Held to a short box on a phone, where the rail is stacked above
                  the reading and a fifty-entry outline would be a screen and a
                  half to scroll past before reaching the first paragraph. */}
              <ul className="max-h-56 space-y-0.5 overflow-y-auto pr-1 lg:max-h-[50vh]">
                {current.headings.map((heading) => (
                  <li key={heading.id}>
                    <a
                      href={`#${heading.id}`}
                      onClick={(event) => {
                        event.preventDefault()
                        document.getElementById(heading.id)?.scrollIntoView({ behavior: 'smooth' })
                        history.replaceState(null, '', `#${heading.id}`)
                      }}
                      className={`block rounded px-2 py-1 text-[13px] leading-snug text-ink-500 hover:bg-ink-100 hover:text-ink-800 dark:hover:bg-dark-200 ${
                        heading.level >= 3 ? 'pl-4 text-[12.5px]' : ''
                      }`}
                    >
                      {heading.title}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
          )}
        </aside>

        <main className="min-w-0">
          {term ? (
            <section>
              <p className="mb-3 text-sm text-ink-500">
                {hits.length === 0
                  ? `Nothing in the documentation mentions "${query.trim()}".`
                  : `${hits.length}${hits.length === 60 ? '+' : ''} section${
                      hits.length === 1 ? '' : 's'
                    } mention "${query.trim()}"`}
              </p>
              <ul className="space-y-1.5">
                {hits.map((hit) => (
                  <li key={`${hit.doc.id}-${hit.sectionId}`}>
                    <button
                      type="button"
                      onClick={() => open(hit.doc.id, hit.sectionId)}
                      className="w-full rounded-xl border border-ink-200 bg-white p-3 text-left transition hover:border-brand-400 dark:border-dark-200 dark:bg-dark-50"
                    >
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="text-sm font-semibold text-ink-800">
                          {hit.sectionTitle}
                        </span>
                        <span className="text-[11px] uppercase tracking-wide text-ink-400">
                          {hit.doc.title}
                        </span>
                      </div>
                      <p className="mt-1 text-[13px] leading-relaxed text-ink-600">
                        {marked(hit.snippet, term).map((part, index) =>
                          part.hit ? (
                            <mark key={index} className="doc-hit">
                              {part.text}
                            </mark>
                          ) : (
                            <span key={index}>{part.text}</span>
                          ),
                        )}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : (
            <article>
              <header className="mb-5">
                <h1 className="text-xl font-bold tracking-tight text-ink-900">
                  {current.title}
                </h1>
                <p className="mt-1 text-sm text-ink-500">{current.summary}</p>
              </header>
              <div
                ref={body}
                className="doc-body"
                // The documentation is this repository's own markdown, turned
                // to HTML at build time and shipped in the bundle. It carries
                // nothing a user typed, so there is no untrusted content here.
                dangerouslySetInnerHTML={{ __html: current.html }}
              />
              <p className="mt-10 border-t border-ink-200 pt-4 text-xs text-ink-400 dark:border-dark-200">
                From <code>docs/{current.source}</code> in the SurveyHQ repository, as of
                this build.
              </p>
            </article>
          )}
        </main>
      </div>
    </>
  )
}
