import { useId } from 'react'

/**
 * The navigation icons, drawn as small Aero tiles.
 *
 * Redrawn as vectors rather than sliced out of the reference sheet: the sheet
 * is a raster mock-up at one size, on a checkerboard, through JPEG - so a slice
 * of it would arrive with compression fringes, a grey background where the
 * transparency was meant to be, and no way to be sharp on a retina screen or
 * at any size but the one it was drawn at. Everything here is geometry, so it
 * is exact at 16 pixels and at 64.
 *
 * Each icon is a tile rather than a bare glyph, which is what makes the set
 * read as a set: a dark rounded square, a gloss over its top half, a light
 * bevel around it, and a metallic glyph. That is the Windows Aero grammar the
 * reference is drawn in, and it is worth following exactly, because half of it
 * looks like a mistake.
 */
export type AppIconName =
  | 'overview'
  | 'projects'
  | 'datasets'
  | 'connections'
  | 'explore'
  | 'dashboards'
  | 'monitoring'
  | 'quality'
  | 'alerts'
  | 'admin'

/**
 * The glyph inside each tile, on a 24x24 grid with the tile at 2..22.
 *
 * Drawn as fills rather than strokes wherever the shape allows: a stroke of
 * one and a half pixels lands between the pixels at sidebar size and comes out
 * grey, while a filled shape keeps its edge.
 */
function glyph(name: AppIconName, fill: string, shadow: string) {
  switch (name) {
    case 'overview':
      // Four panes: the shape of a summary page.
      return (
        <g fill={fill}>
          <rect x="5.8" y="5.8" width="5.6" height="5.6" rx="1.2" />
          <rect x="12.6" y="5.8" width="5.6" height="5.6" rx="1.2" />
          <rect x="5.8" y="12.6" width="5.6" height="5.6" rx="1.2" />
          <rect x="12.6" y="12.6" width="5.6" height="5.6" rx="1.2" />
        </g>
      )
    case 'projects':
      // A folder, with the tab that says which way is up.
      return (
        <g fill={fill}>
          <path d="M5.6 8.2a1.3 1.3 0 0 1 1.3-1.3h3l1.5 1.6h5.1a1.3 1.3 0 0 1 1.3 1.3v.6H5.6Z" />
          <path d="M5.6 11.1h12.8a1 1 0 0 1 1 1.2l-1.1 4.3a1.4 1.4 0 0 1-1.35 1.05H6.95A1.35 1.35 0 0 1 5.6 16.3Z" />
        </g>
      )
    case 'datasets':
      // A table: a header row, then cells. What an export actually is.
      return (
        <g fill={fill}>
          <rect x="5" y="6" width="14" height="3.4" rx="0.9" />
          <rect x="5" y="10.6" width="4" height="3.1" rx="0.8" />
          <rect x="10" y="10.6" width="4" height="3.1" rx="0.8" />
          <rect x="15" y="10.6" width="4" height="3.1" rx="0.8" />
          <rect x="5" y="14.9" width="4" height="3.1" rx="0.8" />
          <rect x="10" y="14.9" width="4" height="3.1" rx="0.8" />
          <rect x="15" y="14.9" width="4" height="3.1" rx="0.8" />
        </g>
      )
    case 'connections':
      // Three nodes joined: one dataset related to another.
      return (
        <g fill={fill}>
          <path
            d="M12 6.2 5.6 17.2M12 6.2l6.4 11M5.6 17.2h12.8"
            stroke={fill}
            strokeWidth="1.7"
            strokeLinecap="round"
            fill="none"
          />
          <circle cx="12" cy="6.2" r="2.8" />
          <circle cx="5.6" cy="17.3" r="2.8" />
          <circle cx="18.4" cy="17.3" r="2.8" />
        </g>
      )
    case 'explore':
      // A compass: going to look for something rather than being shown it.
      return (
        <g>
          <circle cx="12" cy="12" r="7.1" fill="none" stroke={fill} strokeWidth="1.5" />
          <path d="M15.8 8.2 10.7 10.7 8.2 15.8 13.3 13.3Z" fill={fill} />
          <circle cx="12" cy="12" r="0.9" fill={shadow} />
        </g>
      )
    case 'dashboards':
      // The board itself: one tall widget, two stacked beside it.
      return (
        <g fill={fill}>
          <rect x="5.6" y="6" width="5.2" height="12" rx="1.1" />
          <rect x="12.2" y="6" width="6.2" height="5.2" rx="1.1" />
          <rect x="12.2" y="12.8" width="6.2" height="5.2" rx="1.1" />
        </g>
      )
    case 'monitoring':
      // A radar: watching something that is still happening.
      return (
        <g>
          <path d="M12 12 19.2 12A7.2 7.2 0 0 0 17.1 6.9Z" fill={fill} opacity="0.55" />
          <circle cx="12" cy="12" r="7.2" fill="none" stroke={fill} strokeWidth="1.5" />
          <circle cx="12" cy="12" r="4.2" fill="none" stroke={fill} strokeWidth="1.2" opacity="0.8" />
          <circle cx="12" cy="12" r="1.8" fill={fill} />
        </g>
      )
    case 'quality':
      // A tick, which is the only thing a check has to say when it passes.
      return (
        <path
          d="M6.2 12.4 10.2 16.4 17.9 7.7"
          fill="none"
          stroke={fill}
          strokeWidth="3.1"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )
    case 'alerts':
      // The bang, not a bell: an alert here is a rule that tripped.
      return (
        <g fill={fill}>
          <path d="M10.6 5.6h2.8l-.5 8.6h-1.8Z" />
          <circle cx="12" cy="17.3" r="1.75" />
        </g>
      )
    case 'admin':
      // A cog, drawn as one path so its teeth stay even at any size.
      return (
        <g fill={fill}>
          <path d="M12 4.4a1 1 0 0 1 .98.8l.28 1.42a5.9 5.9 0 0 1 1.35.78l1.36-.49a1 1 0 0 1 1.2.45l.9 1.56a1 1 0 0 1-.22 1.25l-1.09.93a5.9 5.9 0 0 1 0 1.56l1.09.93a1 1 0 0 1 .22 1.25l-.9 1.56a1 1 0 0 1-1.2.45l-1.36-.49a5.9 5.9 0 0 1-1.35.78l-.28 1.42a1 1 0 0 1-.98.8h-1.8a1 1 0 0 1-.98-.8l-.28-1.42a5.9 5.9 0 0 1-1.35-.78l-1.36.49a1 1 0 0 1-1.2-.45l-.9-1.56a1 1 0 0 1 .22-1.25l1.09-.93a5.9 5.9 0 0 1 0-1.56l-1.09-.93a1 1 0 0 1-.22-1.25l.9-1.56a1 1 0 0 1 1.2-.45l1.36.49a5.9 5.9 0 0 1 1.35-.78l.28-1.42a1 1 0 0 1 .98-.8Z" />
          <circle cx="11.1" cy="12" r="2.6" fill={shadow} />
        </g>
      )
  }
}

export default function AppIcon({
  name,
  size = 22,
  className = '',
  glow = true,
}: {
  name: AppIconName
  size?: number
  className?: string
  /** The blue halo under the tile. Off where the icon sits on a light ground. */
  glow?: boolean
}) {
  // Gradient ids have to be unique per instance: two icons on one page sharing
  // an id means the second one silently paints itself with the first one's
  // fill, and which of them wins depends on the order the DOM happens to be in.
  const id = useId().replace(/:/g, '')

  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      role="presentation"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        {/* The tile: near-black at the top, a shade lighter at the bottom, which
            is what makes it read as a physical button rather than a hole. */}
        <linearGradient id={`${id}-tile`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3b414d" />
          <stop offset="0.5" stopColor="#20242c" />
          <stop offset="0.5" stopColor="#181b21" />
          <stop offset="1" stopColor="#2a2f38" />
        </linearGradient>
        {/* The gloss over the top half. Aero's whole trick, and the reason the
            stop above is doubled at the halfway mark: the highlight ends on a
            hard line, not a fade. */}
        <linearGradient id={`${id}-gloss`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.22" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0.03" />
        </linearGradient>
        {/* The glyph, lit from above like brushed metal. */}
        <linearGradient id={`${id}-glyph`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="0.55" stopColor="#dfe6ee" />
          <stop offset="1" stopColor="#a8b3c2" />
        </linearGradient>
        <radialGradient id={`${id}-halo`} cx="0.5" cy="0.62" r="0.55">
          <stop offset="0" stopColor="#4db8ff" stopOpacity="0.75" />
          <stop offset="1" stopColor="#4db8ff" stopOpacity="0" />
        </radialGradient>
      </defs>

      {glow && <rect x="0" y="2" width="24" height="22" rx="7" fill={`url(#${id}-halo)`} />}

      <rect x="1.5" y="1.5" width="21" height="21" rx="5.4" fill={`url(#${id}-tile)`} />
      {/* The bevel: one hairline of light along the top, one of shadow around
          the rest, which is the whole of the raised look. */}
      <rect
        x="2.1"
        y="2.1"
        width="19.8"
        height="19.8"
        rx="4.9"
        fill="none"
        stroke="#ffffff"
        strokeOpacity="0.16"
      />
      <rect
        x="1.5"
        y="1.5"
        width="21"
        height="21"
        rx="5.4"
        fill="none"
        stroke="#05070a"
        strokeOpacity="0.85"
      />
      <path
        d="M2.1 7A4.9 4.9 0 0 1 7 2.1h10A4.9 4.9 0 0 1 21.9 7v3.4c-3 1.5-6.2 2.2-9.9 2.2s-6.9-.7-9.9-2.2Z"
        fill={`url(#${id}-gloss)`}
      />

      {glyph(name, `url(#${id}-glyph)`, '#20242c')}
    </svg>
  )
}
