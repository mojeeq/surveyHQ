import { isDark } from '@/lib/colour'

/**
 * The colours the side pane can be painted, and the ink that follows.
 *
 * A sidebar is white text on near-black today. Let somebody pick their own
 * colour and that stops being safe: a pale one leaves white text on white.
 * So nothing here hard-codes the ink. Every shade is derived from whether the
 * chosen colour is dark, which means a light sidebar works as well as a dark
 * one and a custom colour cannot produce an unreadable shell.
 */

/** A chosen colour, or null for the one the platform ships with. */
export type SidebarColour = string | null

/** `null` is the default, which is slate-950 and what the shell always was. */
export const DEFAULT_SIDEBAR = '#020617'

export const SIDEBAR_PRESETS: { id: string; label: string; value: SidebarColour }[] = [
  { id: 'default', label: 'Default', value: null },
  { id: 'graphite', label: 'Graphite', value: '#1d2026' },
  { id: 'navy', label: 'Navy', value: '#111c33' },
  { id: 'indigo', label: 'Indigo', value: '#1e1b4b' },
  { id: 'teal', label: 'Teal', value: '#0b3538' },
  { id: 'forest', label: 'Forest', value: '#14301f' },
  { id: 'plum', label: 'Plum', value: '#2c1530' },
  { id: 'clay', label: 'Clay', value: '#3a2419' },
  // One light shade, both because somebody will want it and because it is the
  // case that proves the ink follows the colour rather than being assumed.
  { id: 'paper', label: 'Paper', value: '#e8ecf2' },
]

/** The custom properties the shell sets on the side pane for a given colour. */
export type SidebarInk = Record<string, string>

/**
 * Ink for a background, as CSS custom properties.
 *
 * The selected row is always the inverse of the pane: a light chip on a dark
 * pane, a dark chip on a light one. That is what the shell already did with
 * white on slate-950, and it is the one treatment that stays legible at both
 * ends without a second rule.
 */
export function inkFor(colour: SidebarColour): SidebarInk {
  const background = colour ?? DEFAULT_SIDEBAR
  const dark = isDark(background)
  // Mixed with the pane rather than with white or black, so the dim shades
  // keep a little of the colour instead of going grey on a saturated pane.
  const over = (alpha: number) =>
    dark ? `rgba(255,255,255,${alpha})` : `rgba(15,23,42,${alpha})`
  return {
    '--sb-bg': background,
    '--sb-ink': dark ? '#ffffff' : '#0f172a',
    '--sb-dim': over(0.62),
    '--sb-faint': over(0.4),
    '--sb-hover': over(dark ? 0.08 : 0.06),
    '--sb-edge': over(dark ? 0.08 : 0.1),
    '--sb-active-bg': dark ? '#ffffff' : '#0f172a',
    '--sb-active-ink': dark ? '#0f172a' : '#ffffff',
  }
}

/** The label under the swatch, for a colour that is not one of the presets. */
export function nameOf(colour: SidebarColour): string {
  return SIDEBAR_PRESETS.find((p) => p.value === colour)?.label ?? 'Custom'
}
