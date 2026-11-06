/**
 * Every row in the side navigation has its own icon.
 *
 * Targets shipped wearing the Indicators radar, because adding a row means
 * naming an icon and the nearest existing name is always right there. Two
 * identical tiles one above the other read as one page listed twice, and a
 * reader who finds the icons unreliable stops using them at all.
 */
import { describe, expect, it } from 'vitest'
import { NAV_GROUPS } from '@/components/Layout'

const rows = NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => ({ ...item, group: group.label })),
)

describe('the side navigation', () => {
  it('gives each row an icon of its own', () => {
    const seen = new Map<string, string>()
    for (const row of rows) {
      const already = seen.get(row.icon)
      expect(already, `${row.label} and ${already} share the "${row.icon}" icon`).toBeUndefined()
      seen.set(row.icon, row.label)
    }
  })

  it('sends each row somewhere of its own', () => {
    const paths = rows.map((row) => row.to)

    expect(new Set(paths).size).toBe(paths.length)
  })

  it('names a page for every row, so none of them is a dead link', () => {
    for (const row of rows) {
      expect(row.label.trim(), `${row.to} has no label`).toBeTruthy()
    }
  })
})
