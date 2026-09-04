// Small presentational primitives shared across pages.

import { type CSSProperties, type ReactNode, useEffect } from 'react'

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
    <div className="flex items-center justify-center gap-3 py-14 text-ink-500">
      <Spinner />
      <span>{label}…</span>
    </div>
  )
}

export function ErrorNote({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong'
  return (
    <div className="rounded-card border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
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
      <h3 className="text-base font-semibold text-ink-800">{title}</h3>
      {description && <p className="max-w-md text-sm text-ink-500">{description}</p>}
      {action}
    </div>
  )
}

const BADGE_TONES = {
  neutral: 'bg-ink-100 text-ink-700',
  info: 'bg-brand-50 text-brand-700',
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-800',
  danger: 'bg-red-50 text-red-700',
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
            {title && <h2 className="truncate text-sm font-semibold text-ink-800">{title}</h2>}
            {subtitle && <p className="mt-0.5 truncate text-xs text-ink-500">{subtitle}</p>}
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
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink-900/40 p-4 pt-[6vh]">
      <div
        className="absolute inset-0"
        onClick={onClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`relative w-full ${wide ? 'max-w-4xl' : 'max-w-lg'} rounded-card bg-white shadow-pop`}
      >
        <header className="flex items-center justify-between border-b border-ink-200 px-5 py-4">
          <h2 className="text-base font-semibold text-ink-900">{title}</h2>
          <button className="btn-ghost btn-sm" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <footer className="flex justify-end gap-2 border-t border-ink-200 px-5 py-3">
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
      {hint && !error && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
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
}) {
  const centred = align === 'center'
  return (
    <div
      className={`mb-6 flex flex-wrap items-start justify-between gap-3 ${
        rule ? 'border-b border-ink-200 pb-4' : ''
      } ${centred ? 'flex-col items-center text-center' : ''}`}
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
              <h1 className="text-xl font-semibold text-ink-900" style={titleStyle}>
                {title}
              </h1>
            </button>
          ) : (
            <h1 className="text-xl font-semibold text-ink-900" style={titleStyle}>
              {title}
            </h1>
          )}
          {description && <p className="mt-1 text-sm text-ink-500">{description}</p>}
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
    neutral: 'text-ink-900',
    info: 'text-brand-700',
    success: 'text-emerald-700',
    warning: 'text-amber-700',
    danger: 'text-red-700',
  }
  return (
    <div className="card px-5 py-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${accents[tone]}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
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
          checked ? 'bg-brand-600' : 'bg-ink-300'
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? 'translate-x-4' : 'translate-x-0.5'
          }`}
        />
      </button>
      {label && <span className="text-sm text-ink-700">{label}</span>}
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
    <div className="flex gap-1 overflow-x-auto border-b border-ink-200">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => onChange(tab.id)}
          className={`whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors ${
            active === tab.id
              ? 'border-brand-600 text-brand-700'
              : 'border-transparent text-ink-500 hover:text-ink-800'
          }`}
        >
          {tab.label}
          {tab.count !== undefined && (
            <span className="ml-1.5 rounded-full bg-ink-100 px-1.5 py-0.5 text-xs text-ink-600">
              {tab.count}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}
