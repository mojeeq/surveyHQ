/**
 * The ready-made looks, checked for the ways a palette goes wrong quietly.
 *
 * A look is five surfaces that have to agree, and the failures are not crashes
 * - they are a board that went out with its page tabs invisible against their
 * own band, or a ground drawn against the wrong colour, or a look that set
 * four of the five fields and left the fifth carrying whatever the board had
 * before. Nothing throws; it just looks wrong on somebody's wall.
 */
import { describe, expect, it } from 'vitest'
import { BACKGROUNDS, ground } from '@/lib/backgrounds'
import { FAMILIES, LOOKS } from '@/lib/looks'
import { isDark } from '@/lib/colour'

/** Every field a look is responsible for, so none is left to the old board. */
const SURFACES = [
  'page_background',
  'header_background',
  'background_color',
  'background_pattern',
  'tab_background',
  'tab_color',
  'filter_background',
  'filter_color',
] as const

describe('the looks', () => {
  it('offers enough of them to be worth calling a list', () => {
    expect(LOOKS.length).toBeGreaterThanOrEqual(20)
  })

  it('names each one once', () => {
    expect(new Set(LOOKS.map((look) => look.key)).size).toBe(LOOKS.length)
    expect(new Set(LOOKS.map((look) => look.label)).size).toBe(LOOKS.length)
  })

  it('sets every surface it is responsible for, even to nothing', () => {
    for (const look of LOOKS) {
      for (const field of SURFACES) {
        expect(
          Object.prototype.hasOwnProperty.call(look.patch, field),
          `${look.key} leaves ${field} as whatever the board had before`,
        ).toBe(true)
      }
    }
  })

  it('puts light text on dark bands and dark text on light ones', () => {
    for (const look of LOOKS) {
      const { tab_background: tabs, tab_color: tabText } = look.patch
      const { filter_background: bar, filter_color: barText } = look.patch
      if (tabs && tabText) {
        expect(isDark(tabs), `${look.key}: page tabs are ${tabText} on ${tabs}`).toBe(
          !isDark(tabText),
        )
      }
      if (bar && barText) {
        expect(isDark(bar), `${look.key}: filter labels are ${barText} on ${bar}`).toBe(
          !isDark(barText),
        )
      }
    }
  })

  it('gives its ground a colour to be drawn against', () => {
    for (const look of LOOKS) {
      const chosen = ground(look.patch.background_pattern)
      if (!chosen) continue
      // A texture is translucent ink, so the look may carry its own colour
      // under it. A ground whose character is its colour cannot: the look
      // would be setting a colour that nothing ever shows.
      expect(look.patch.background_color, `${look.key} draws ${chosen.id} on nothing`).toBeTruthy()
      if (!chosen.tintable) {
        expect(
          look.patch.background_color,
          `${look.key} sets a colour ${chosen.id} paints over`,
        ).toBe(chosen.tint)
      }
    }
  })

  it('only names grounds this version has', () => {
    const known = new Set(BACKGROUNDS.map((one) => one.id))
    for (const look of LOOKS) {
      const named = look.patch.background_pattern
      if (named) expect(known.has(named), `${look.key} names ${named}`).toBe(true)
    }
  })

  it('files each look under a family the picker shows', () => {
    const families = new Set(FAMILIES.map((family) => family.id))
    for (const look of LOOKS) {
      expect(families.has(look.family), `${look.key} is filed under ${look.family}`).toBe(true)
    }
    // Every band in the picker has something in it, or it is a heading over
    // nothing.
    for (const family of FAMILIES) {
      expect(LOOKS.some((look) => look.family === family.id), `${family.id} is empty`).toBe(true)
    }
  })

  it('is a patch, not a whole appearance', () => {
    // The grid, the logo, the title and the widget opacity belong to the
    // board. A look that carried them would undo somebody's layout.
    const theirs = ['columns', 'row_height', 'widget_opacity', 'logo_image', 'title_size', 'title_font']
    for (const look of LOOKS) {
      for (const field of theirs) {
        expect(
          Object.prototype.hasOwnProperty.call(look.patch, field),
          `${look.key} would overwrite ${field}`,
        ).toBe(false)
      }
    }
  })
})

describe('the ready-made grounds', () => {
  it('names each one once', () => {
    expect(new Set(BACKGROUNDS.map((one) => one.id)).size).toBe(BACKGROUNDS.length)
  })

  it('is drawn rather than fetched', () => {
    for (const one of BACKGROUNDS) {
      expect(one.layers, one.id).not.toContain('url(')
      expect(one.layers, one.id).toContain('gradient(')
    }
  })

  it('keeps a tintable ground to translucent ink', () => {
    // A single opaque stop and the colour underneath stops existing, which is
    // the whole promise of the flag.
    for (const one of BACKGROUNDS.filter((g) => g.tintable)) {
      expect(one.layers, `${one.id} paints over its own tint`).not.toMatch(/#[0-9a-f]{3,8}/i)
      expect(one.layers, one.id).toContain('rgba(')
    }
  })

  it('gives a repeating pattern the cell it repeats in', () => {
    // A squared or dotted ground with no background-size draws one line across
    // the top of the board and nothing else.
    for (const one of BACKGROUNDS) {
      const repeats = /^(linear|radial)-gradient\([^)]*\b1(\.\d+)?px/.test(one.layers)
      if (repeats) expect(one.size, `${one.id} has no cell to repeat in`).toBeTruthy()
    }
  })

  it('has a tint that is a colour', () => {
    for (const one of BACKGROUNDS) {
      expect(one.tint, one.id).toMatch(/^#[0-9a-f]{6}$/)
    }
  })

  it('finds a ground by id and nothing by a name it does not have', () => {
    expect(ground('graph')?.label).toBe('Graph paper')
    expect(ground('ziggurat')).toBeUndefined()
    expect(ground('')).toBeUndefined()
    expect(ground(undefined)).toBeUndefined()
  })
})
