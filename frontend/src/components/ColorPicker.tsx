import { useEffect, useState } from 'react'

/**
 * One colour control, used everywhere a colour is chosen.
 *
 * Before this there were five fixed swatches per place and no way to type a
 * colour, so an office with a brand palette could not use it. Three ways in,
 * because people arrive with the colour in different forms: a swatch when you
 * just want a reasonable one, a hex box when the brand book gives you
 * "#1F4E79", and the system picker when you want to nudge it by eye.
 */

/**
 * Rows of hues: pale enough for a panel, solid enough for a mark, dark for text.
 *
 * The middle row is not an arbitrary set of nice colours. It is the "High
 * separation" chart theme in its own order, so the swatches offered for a
 * chart are hues already checked to stay apart for colour-blind readers -
 * worst adjacent pair ΔE 15.3 (deutan), 20.8 with normal vision. Ordering it
 * any other way fails: red beside orange comes out at 7.1, which almost nobody
 * can read as two series. Re-run the palette validator before changing it.
 */
export const PICKER_SWATCHES: string[] = [
  // Pale - backgrounds and panels
  '#ffffff', '#f7f8f9', '#eef2f6', '#e8eef5', '#f5f0e6', '#e9f1ea', '#fdeaea', '#f3eafc',
  // Mid - marks and accents, in validated separation order
  '#e87ba4', '#008300', '#eda100', '#e34948', '#4a3aa7', '#1baf7a', '#2a78d6', '#eb6834',
  // Ink - text and dark panels
  '#0b0b0b', '#333333', '#595959', '#898781', '#c3c2b7', '#334155', '#1e293b', '#0f172a',
]

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i

/** Normalise what someone typed or pasted: "1F4E79", "#1f4e79", " #FFF " all work. */
export function normaliseHex(input: string): string | null {
  const trimmed = input.trim()
  if (!trimmed) return null
  const withHash = trimmed.startsWith('#') ? trimmed : `#${trimmed}`
  if (!HEX.test(withHash)) return null
  if (withHash.length === 4) {
    // #abc means #aabbcc; the native colour input will not accept the short form.
    const [, r, g, b] = withHash
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase()
  }
  return withHash.toLowerCase()
}

export default function ColorPicker({
  value,
  onChange,
  swatches = PICKER_SWATCHES,
  allowNone = false,
  noneLabel = 'No colour',
  label = '',
}: {
  value: string
  onChange: (value: string) => void
  swatches?: string[]
  /** Offer a "not set" choice, which falls back to whatever the theme says. */
  allowNone?: boolean
  noneLabel?: string
  /** What this picker colours, e.g. "Map point".
   *
   *  A dialog often carries several of these - the widget's background, its
   *  text, its map pins - and without it every one of them announces itself as
   *  "Colour code", so a reader who cannot see the heading above it has no way
   *  to tell which is which.
   */
  label?: string
}) {
  const [typed, setTyped] = useState(value)
  // Keep the box in step when the colour changes from a swatch or the picker,
  // without fighting what is being typed into it.
  useEffect(() => setTyped(value), [value])

  const commit = (raw: string) => {
    setTyped(raw)
    const hex = normaliseHex(raw)
    if (hex) onChange(hex)
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {allowNone && (
          <button
            type="button"
            title={noneLabel}
            aria-label={noneLabel}
            aria-pressed={!value}
            onClick={() => onChange('')}
            className={`h-7 w-7 rounded-control border-2 bg-white transition ${
              !value ? 'border-brand-600 ring-2 ring-brand-200' : 'border-ink-200'
            }`}
            style={{
              backgroundImage:
                'linear-gradient(45deg,transparent 45%,#ef4444 45%,#ef4444 55%,transparent 55%)',
            }}
          />
        )}
        {swatches.map((swatch) => (
          <button
            key={swatch}
            type="button"
            title={swatch}
            aria-label={swatch}
            aria-pressed={value.toLowerCase() === swatch.toLowerCase()}
            onClick={() => onChange(swatch)}
            className={`h-7 w-7 rounded-control border-2 transition ${
              value.toLowerCase() === swatch.toLowerCase()
                ? 'border-brand-600 ring-2 ring-brand-200'
                : 'border-ink-200'
            }`}
            style={{ backgroundColor: swatch }}
          />
        ))}
      </div>
      <div className="flex items-center gap-2">
        <input
          className="input w-28 font-mono text-xs"
          value={typed}
          placeholder="#1f4e79"
          aria-label={label ? `${label} colour code` : 'Colour code'}
          spellCheck={false}
          onChange={(event) => commit(event.target.value)}
          onBlur={() => setTyped(value)}
        />
        <input
          type="color"
          className="h-8 w-12 cursor-pointer rounded-control border border-ink-200 bg-white"
          title="Pick any colour"
          aria-label={label ? `Pick any ${label.toLowerCase()} colour` : 'Pick any colour'}
          value={normaliseHex(value) ?? '#ffffff'}
          onChange={(event) => onChange(event.target.value)}
        />
        {typed && !normaliseHex(typed) && (
          <span className="text-xs text-red-600">Not a colour code</span>
        )}
      </div>
    </div>
  )
}
