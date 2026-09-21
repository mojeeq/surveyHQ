// Small presentational primitives shared across pages.

import { type CSSProperties, type ReactNode, useEffect, useRef, useState } from 'react'
import { confirmsOnEnter, enterContext } from '@/lib/keys'

export function Spinner({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg className={`animate-spin text-brand-600 ${className}`} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.2" />
      <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-14 text-ink-500 dark:text-dark-500">
      <Spinner />
      <span>{label}…</span>
    </div>
  )
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong'
  return (
    <div className="rounded-card border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900/40 dark:bg-red-950/30 dark:text-red-300">
      <div className="flex items-start gap-2">
        <span aria-hidden>⚠</span>
        <div className="flex-1">
          <p className="font-medium">{message}</p>
          {retry && (
            <button className="mt-2 text-xs font-semibold underline" onClick={retry}>
              Try again
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
  icon = '📄',
}: {
  title: string
  description?: string
  action?: ReactNode
  icon?: string
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div className="text-4xl" aria-hidden>
        {icon}
      </div>
      <h3 className="text-base font-semibold text-ink-800 dark:text-dark-800">{title}</h3>
      {description && <p className="max-w-md text-sm text-ink-500 dark:text-dark-500">{description}</p>}
      {action}
    </div>
  )
}

// A quiet border of the tone's own colour, which is what stops a square badge
// reading as a button.
const BADGE_TONES = {
  neutral: 'bg-ink-100 text-ink-700 border-ink-200 dark:bg-dark-200 dark:text-dark-700 dark:border-dark-300',
  info: 'bg-brand-50 text-brand-700 border-brand-200 dark:bg-brand-500/10 dark:text-brand-400 dark:border-brand-500/30',
  success: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/30',
  warning: 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-500/10 dark:text-amber-400 dark:border-amber-500/30',
  danger: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/30',
} as const

export type BadgeTone = keyof typeof BADGE_TONES

export function Badge({
  children,
  tone = 'neutral',
  icon,
}: {
  children: ReactNode
  tone?: BadgeTone
  icon?: string
}) {
  return (
    <span className={`chip ${BADGE_TONES[tone]}`}>
      {/* Icon + label so status never rests on colour alone */}
      {icon && <span aria-hidden>{icon}</span>}
      {children}
    </span>
  )
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = '',
  bodyClassName = 'card-body',
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-header">
          <div className="min-w-0">
            {title && <h2 className="truncate text-sm font-semibold text-ink-800 dark:text-dark-800">{title}</h2>}
            {subtitle && <p className="mt-0.5 truncate text-xs text-ink-500 dark:text-dark-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  )
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide = false,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  const panel = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  const wasOpen = useRef(false)

  /*
   * Who to give the focus back to, captured while it is still true.
   *
   * During render, not in the effect below. React focuses a child asking for
   * `autoFocus` when it commits, which is before any effect runs, so an effect
   * reading `document.activeElement` finds that child and never sees the
   * button that opened the dialog. Closing then tried to hand the focus to an
   * input that had just been removed from the page, and it landed on the body
   * instead - which is the new-dashboard dialog, among others.
   *
   * Render is the last moment before that commit, so this is where the
   * launcher is still the focused thing.
   */
  if (open && !wasOpen.current) {
    opener.current = document.activeElement as HTMLElement | null
  }
  wasOpen.current = open

  /**
   * A dialog takes the focus when it opens, and hands it back when it closes.
   *
   * It did neither. Focus stayed on whatever button opened the dialog, which
   * is now behind it and cannot be seen, and that had two consequences. The
   * obvious one is that a reader on a keyboard was still standing outside the
   * thing that had just appeared in front of them. The sharper one is that
   * Enter then re-pressed that hidden button rather than confirming the
   * dialog - so the dialog opened, and opened, and never saved.
   *
   * A child asking for `autoFocus` has already been focused by the time this
   * runs, so nothing is moved when the focus is inside the panel: the author's
   * choice wins over the default.
   */
  useEffect(() => {
    if (!open) return
    const dialog = panel.current
    if (dialog && !dialog.contains(document.activeElement)) takeFocus(dialog)
    return () => {
      // Back where it came from, but only if that is still on the page: a
      // dialog that deleted the row its own button sat in has nothing to
      // return to, and focusing a detached node drops focus onto the body.
      const back = opener.current
      opener.current = null
      if (back && back.isConnected) back.focus()
    }
  }, [open])

  /**
   * Put the focus on the first control that will actually take it.
   *
   * The first control in the *body*, not in the panel: first in the panel is
   * the header's close button, and a dialog that opens with the focus on its
   * own X is offering to undo itself before it has been read.
   *
   * Tried in turn rather than picked, because matching the selector is not the
   * same as being focusable. A control inside a folded `Section` is still in
   * the document and still matches - a closed `<details>` keeps its contents -
   * and focusing it does nothing at all. Taking the first match on trust left
   * the focus outside the dialog, back on the launcher, which is the bug this
   * was written to fix; the appearance and widget dialogs both remember which
   * of their sections were folded, so it is an ordinary state to open in.
   *
   * Whatever is left over - every candidate hidden, or none to begin with -
   * the panel takes the focus itself, which keeps the key handling and the
   * screen reader on the dialog either way.
   */
  const takeFocus = (dialog: HTMLElement) => {
    const candidates = content.current?.querySelectorAll<HTMLElement>(
      'input:not([disabled]):not([type="hidden"]), select:not([disabled]), ' +
        'textarea:not([disabled]), button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
    )
    for (const candidate of candidates ?? []) {
      candidate.focus()
      if (document.activeElement === candidate) return
    }
    dialog.focus()
  }

  /**
   * Whether this is the dialog a key is meant for.
   *
   * Every open Modal listens on the document, so a dialog opened over another
   * one leaves two listeners for the same key. Escape then closed whichever
   * had registered first - the one underneath - and left the one on top
   * stranded over an emptied page. Nothing in the app opens a dialog over a
   * dialog today, so this is a trap rather than a bug anybody hits; it is
   * worth closing while the key handling is being written, because the day
   * somebody nests two the failure is silent and reads as Escape being
   * ignored.
   *
   * Last in the document is the one on top: each dialog is appended as it
   * opens, and they all share one stacking context.
   */
  const topmost = () => {
    const all = document.querySelectorAll('[data-modal]')
    return all.length > 0 && all[all.length - 1] === panel.current
  }

  /**
   * Enter does what the dialog's own button does.
   *
   * Which button that is is not asked of the caller. It is the primary one in
   * the footer, read off the dialog when the key is pressed: every dialog
   * here already ends in one, and reading it live means a dialog that changes
   * its own footer - a Save that becomes Saving..., a button that appears
   * once a file is chosen - is still answered correctly. Pressing it rather
   * than calling a handler is also what keeps its own guards: a disabled
   * button is not pressed, and neither is a dialog with no footer, which is
   * right for the ones that only have a Close.
   *
   * A primary button in the *body* is left alone. The comments dialog has
   * one, under a textarea meant to hold a paragraph, and Enter there is a new
   * line rather than a post.
   *
   * When Enter should be ignored altogether is in `confirmsOnEnter`.
   */
  const confirm = (event: KeyboardEvent) => {
    if (!confirmsOnEnter(enterContext(event))) return

    const dialog = panel.current
    const target = event.target as HTMLElement | null
    // The key has to have been pressed in this dialog, or with nothing
    // focused at all.
    if (!dialog) return
    if (target && target !== document.body && !dialog.contains(target)) return

    const primary = dialog.querySelector<HTMLButtonElement>('footer button.btn-primary')
    if (!primary || primary.disabled) return
    // Stops the browser from also submitting a form the dialog happens to sit
    // in, which would send the same thing twice.
    event.preventDefault()
    primary.click()
  }

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (!topmost()) return
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key === 'Enter') confirm(event)
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex animate-[fade-in_150ms_ease-out] items-start justify-center overflow-y-auto bg-ink-900/40 p-4 pt-[6vh] dark:bg-black/60">
      <div
        className="absolute inset-0"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={panel}
        data-modal
        tabIndex={-1}
        className={`relative w-full ${wide ? 'max-w-4xl' : 'max-w-lg'} rounded-card bg-white shadow-pop dark:bg-dark-50`}
      >
        <header className="flex items-center justify-between border-b border-ink-200 px-5 py-4 dark:border-dark-200">
          <h2 className="text-base font-semibold text-ink-900 dark:text-dark-900">{title}</h2>
          <button className="btn-ghost btn-sm" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div ref={content} className="max-h-[70vh] overflow-y-auto px-5 py-4">
          {children}
        </div>
        {footer && (
          <footer className="flex justify-end gap-2 border-t border-ink-200 px-5 py-3 dark:border-dark-200">
            {footer}
          </footer>
        )}
      </div>
    </div>
  )
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string
  hint?: string
  error?: string
  children: ReactNode
}) {
  return (
    <div className="mb-4">
      <label className="label">{label}</label>
      {children}
      {hint && !error && <p className="mt-1 text-xs text-ink-500 dark:text-dark-500">{hint}</p>}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}

/**
 * One foldable part of a long settings dialog.
 *
 * Folding on its own only hides things: a reader who cannot see a field also
 * cannot see whether it is set, so they open every section in turn and are
 * worse off than with one long list. `summary` is what stops that - a few words
 * on the closed row saying what this section currently holds ("Harbour,
 * centred, 34px"), so the one you want is the one you open.
 *
 * `<details>` rather than state and a click handler: the browser gives it
 * keyboard operation, the right roles, and find-in-page that opens the section
 * it lands in, none of which is worth writing again.
 */
export function Section({
  title,
  summary,
  children,
  open,
  onToggle,
}: {
  title: string
  /** What is set in here, for when it is closed. Empty means nothing is. */
  summary?: string
  children: ReactNode
  open?: boolean
  onToggle?: (open: boolean) => void
}) {
  // Uncontrolled unless a parent asks to drive it, so a dialog that does not
  // care about remembering anything can use this with two props.
  const [ownOpen, setOwnOpen] = useState(Boolean(open))
  const isOpen = open ?? ownOpen

  return (
    <details
      open={isOpen}
      onToggle={(event) => {
        const next = (event.currentTarget as HTMLDetailsElement).open
        if (next === isOpen) return
        setOwnOpen(next)
        onToggle?.(next)
      }}
      className="border-b border-ink-200 last:border-b-0 dark:border-dark-200"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 py-3 text-xs font-semibold uppercase tracking-wide text-ink-500 hover:text-ink-700 dark:text-dark-500 dark:hover:text-dark-700">
        <span
          className={`shrink-0 text-[10px] leading-none transition-transform ${isOpen ? 'rotate-90' : ''}`}
          aria-hidden
        >
          ▶
        </span>
        <span className="shrink-0">{title}</span>
        {!isOpen && summary && (
          <span className="min-w-0 flex-1 truncate text-right font-normal normal-case tracking-normal text-ink-400 dark:text-dark-400">
            {summary}
          </span>
        )}
      </summary>
      <div className="pb-4">{children}</div>
    </details>
  )
}

/**
 * Which sections of a dialog are open, kept between visits.
 *
 * Somebody who only ever changes the canvas should find the canvas open. The
 * whole thing is wrapped because localStorage throws in a private window and
 * a settings dialog that will not open is worse than one that forgets.
 */
export function useOpenSections(
  key: string,
  fallback: string[],
): [Set<string>, (name: string, open: boolean) => void] {
  const [open, setOpen] = useState<Set<string>>(() => {
    try {
      const stored = localStorage.getItem(`surveyhq.sections.${key}`)
      if (stored) return new Set(JSON.parse(stored) as string[])
    } catch {
      /* private window, or nothing stored yet */
    }
    return new Set(fallback)
  })

  const toggle = (name: string, next: boolean) => {
    setOpen((was) => {
      const now = new Set(was)
      if (next) now.add(name)
      else now.delete(name)
      try {
        localStorage.setItem(`surveyhq.sections.${key}`, JSON.stringify([...now]))
      } catch {
        /* the dialog still works, it just will not remember */
      }
      return now
    })
  }

  return [open, toggle]
}

export function PageHeader({
  title,
  description,
  actions,
  /** A dashboard dresses its own header: logo, title size, face and colour. */
  logo,
  titleStyle,
  align = 'left',
  rule = false,
  onTitleClick,
  band,
  onBand = false,
  onDarkGround = false,
}: {
  title: string
  description?: string
  actions?: ReactNode
  logo?: ReactNode
  titleStyle?: CSSProperties
  align?: 'left' | 'center'
  rule?: boolean
  /** Makes the title itself the way in to styling it. */
  onTitleClick?: () => void
  /**
   * A coloured band to set the title on, which turns the header into a
   * masthead. Given one, the actions drop to a row of their own underneath:
   * a masthead is the board's name, and a line of buttons across it is a
   * toolbar with a name in it.
   */
  band?: CSSProperties
  /** Whether that band is dark enough to need light text on it. */
  onBand?: boolean
  /**
   * Whether the page behind the header is dark. Separate from the band,
   * because the two are different surfaces: a board can carry a pale band on
   * a navy page, and the buttons beside or below it sit on the page, not on
   * the band. Without this a dashboard on a navy ground had its title, and
   * then its whole toolbar, in near-black.
   */
  onDarkGround?: boolean
}) {
  const centred = align === 'center'

  // A band does the separating, so `rule` is not drawn on one: a hairline
  // under a coloured panel is a line under a line.
  if (band) {
    const heading = (
      <h1
        className={`text-[28px] font-semibold leading-tight ${
          onBand ? 'text-white' : 'text-ink-900'
        }`}
        style={titleStyle}
      >
        {title}
      </h1>
    )
    return (
      <div className="mb-6">
        <div
          className="rounded-card border px-6 py-7 lg:px-8"
          style={{
            ...band,
            // The band's own edge, taken from the light it is lit by rather
            // than from a token: a grey hairline reads as a seam on a colour,
            // and the same border has to sit on navy and on sand.
            borderColor: onBand ? 'rgba(255,255,255,0.14)' : 'rgba(0,0,0,0.10)',
          }}
        >
          <div
            className={
              centred
                ? 'flex flex-col items-center gap-3 text-center'
                : 'flex items-center gap-4'
            }
          >
            {logo}
            <div>
              {onTitleClick ? (
                <button
                  className="rounded-control text-left decoration-dotted underline-offset-4 hover:underline"
                  onClick={onTitleClick}
                  title="Change the title's size, font and colour"
                >
                  {heading}
                </button>
              ) : (
                heading
              )}
              {description && (
                <p
                  // 85 rather than the 75 a caption would take on paper. The
                  // band is any colour somebody picked, and on a mid-tone blue
                  // the quieter grey measures under 3:1 - the description is
                  // the line that says what the board is for, so it takes the
                  // contrast and gives up a little of the hierarchy.
                  className={`mt-1.5 text-sm ${onBand ? 'text-white/85' : 'text-ink-600'}`}
                >
                  {description}
                </p>
              )}
            </div>
          </div>
        </div>
        {actions && (
          <div
            className={`mt-3 flex flex-wrap items-center gap-2 ${
              onDarkGround ? 'on-dark' : ''
            }`}
          >
            {actions}
          </div>
        )}
      </div>
    )
  }

  return (
    <div
      className={`mb-6 flex flex-wrap items-start justify-between gap-3 ${
        rule ? 'border-b border-ink-200 pb-4 dark:border-dark-200' : ''
      } ${centred ? 'flex-col items-center text-center' : ''} ${
        onDarkGround ? 'on-dark' : ''
      }`}
    >
      <div className={centred ? 'flex flex-col items-center gap-2' : 'flex items-center gap-3'}>
        {logo}
        <div>
          {onTitleClick ? (
            // Everything that dresses the header lives behind the Appearance
            // button, which is not where a hand goes to change a title. It
            // goes to the title.
            <button
              className="rounded-control text-left decoration-dotted underline-offset-4 hover:underline"
              onClick={onTitleClick}
              title="Change the title's size, font and colour"
            >
              <h1 className="text-xl font-semibold text-ink-900 dark:text-dark-900" style={titleStyle}>
                {title}
              </h1>
            </button>
          ) : (
            <h1 className="text-xl font-semibold text-ink-900 dark:text-dark-900" style={titleStyle}>
              {title}
            </h1>
          )}
          {description && <p className="mt-1 text-sm text-ink-500 dark:text-dark-500">{description}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Stat({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: BadgeTone
}) {
  const accents: Record<BadgeTone, string> = {
    neutral: 'text-ink-900 dark:text-dark-900',
    info: 'text-brand-700 dark:text-brand-400',
    success: 'text-emerald-700 dark:text-emerald-400',
    warning: 'text-amber-700 dark:text-amber-400',
    danger: 'text-red-700 dark:text-red-400',
  }
  return (
    <div className="card px-5 py-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-dark-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${accents[tone]}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-500 dark:text-dark-500">{hint}</p>}
    </div>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label?: string
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative h-5 w-9 rounded-full transition-colors ${
          checked ? 'bg-brand-600' : 'bg-ink-300 dark:bg-dark-300'
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-4' : 'translate-x-0.5'
          }`}
        />
      </button>
      {label && <span className="text-sm text-ink-700 dark:text-dark-700">{label}</span>}
    </label>
  )
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: T; label: string; count?: number }[]
  active: T
  onChange: (id: T) => void
}) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-ink-200 dark:border-dark-200">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors ${
            active === tab.id
              ? 'border-brand-600 text-brand-700 dark:text-brand-400'
              : 'border-transparent text-ink-500 hover:text-ink-800 dark:text-dark-500 dark:hover:text-dark-800'
          }`}
        >
          {tab.label}
          {tab.count !== undefined && (
            <span className="ml-1.5 rounded-control bg-ink-100 px-1.5 py-0.5 text-xs text-ink-600 dark:bg-dark-200 dark:text-dark-600">
              {tab.count}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}
