/**
 * The ink a side pane colour produces.
 *
 * The failure this guards is an unreadable shell: white text on a pale pane,
 * or near-black on a dark one. It cannot be caught by looking, because
 * whoever picked the colour sees their own choice and not the nine others.
 */
import { describe, expect, it } from 'vitest'

import { isDark } from '@/lib/colour'
import { DEFAULT_SIDEBAR, inkFor, nameOf, SIDEBAR_PRESETS } from '@/lib/sidebar'

/** Rec. 709 luma, the same measure isDark uses, as a number. */
const luma = (hex: string) => {
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.replace('#', '').slice(i, i + 2), 16))
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
}

describe('ink for a side pane colour', () => {
  it('puts light text on a dark pane and dark text on a light one', () => {
    expect(inkFor('#020617')['--sb-ink']).toBe('#ffffff')
    expect(inkFor('#e8ecf2')['--sb-ink']).toBe('#0f172a')
  })

  it('inverts the selected row against the pane, whichever way round', () => {
    for (const colour of ['#020617', '#e8ecf2']) {
      const ink = inkFor(colour)
      // The chip and its text must sit on opposite sides of the midpoint, or
      // the selected row is the one thing you cannot read.
      expect(luma(ink['--sb-active-bg']) > 0.5).toBe(luma(ink['--sb-active-ink']) < 0.5)
      // And the chip must contrast with the pane it sits on.
      expect(isDark(ink['--sb-active-bg'])).toBe(!isDark(colour))
    }
  })

  it('treats no choice as the colour the platform ships with', () => {
    expect(inkFor(null)).toEqual(inkFor(DEFAULT_SIDEBAR))
    expect(inkFor(null)['--sb-bg']).toBe(DEFAULT_SIDEBAR)
  })

  it('gives every preset readable ink', () => {
    for (const preset of SIDEBAR_PRESETS) {
      const colour = preset.value ?? DEFAULT_SIDEBAR
      const ink = inkFor(colour)
      // Pane and its primary text on opposite sides of the midpoint.
      expect(
        isDark(colour),
        `${preset.label} (${colour}) has ink ${ink['--sb-ink']}`,
      ).toBe(!isDark(ink['--sb-ink']))
    }
  })

  it('keeps every preset clear of the midpoint where neither ink suits', () => {
    // The ink is a binary flip, so a mid-tone pane is the one case it cannot
    // serve well: white gives about 3.9:1 on #808080 and near-black 5.3:1,
    // neither comfortable. A custom colour may land there and that is the
    // person's choice; a preset we ship should not. Today the darks top out
    // at 0.17 and the one pale shade is 0.92, so this has room to spare.
    for (const preset of SIDEBAR_PRESETS) {
      const value = preset.value ?? DEFAULT_SIDEBAR
      const brightness = luma(value)
      expect(
        brightness < 0.3 || brightness > 0.7,
        `${preset.label} (${value}) sits at ${brightness.toFixed(2)}, too near the flip`,
      ).toBe(true)
    }
  })

  it('ships at least one pale preset, so the flip is exercised by a real one', () => {
    // Without this the inversion above only ever runs one way in practice.
    const pale = SIDEBAR_PRESETS.filter((p) => p.value && !isDark(p.value))
    expect(pale.length).toBeGreaterThan(0)
  })

  it('sets every property the shell reads', () => {
    // A missing one resolves to nothing in CSS and the element loses that
    // colour silently, which looks like a styling bug rather than a gap here.
    expect(Object.keys(inkFor('#123456')).sort()).toEqual([
      '--sb-active-bg',
      '--sb-active-ink',
      '--sb-bg',
      '--sb-dim',
      '--sb-edge',
      '--sb-faint',
      '--sb-hover',
      '--sb-ink',
    ])
  })
})

describe('naming a colour', () => {
  it('uses the preset name when it is one', () => {
    expect(nameOf(null)).toBe('Default')
    expect(nameOf('#1e1b4b')).toBe('Indigo')
  })

  it('calls anything else Custom', () => {
    expect(nameOf('#abcdef')).toBe('Custom')
  })
})
