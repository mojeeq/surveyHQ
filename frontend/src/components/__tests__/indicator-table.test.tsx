/**
 * The breakdown as lines of figures rather than as a chart.
 *
 * Sixty bars in a tile the size of a postcard is a smear: the labels collide,
 * nothing can be quoted and a reader looking up one area reads every bar to
 * find it. The same sixty as a table is a list somebody can read down. Both
 * forms are drawn from the same numbers, so these pin what the table says -
 * the group, its value, its own quota and its share of that quota - and the
 * two cases that are easy to get wrong: a group with no quota, which is not
 * nought per cent of anything, and a breakdown with no quotas at all, where
 * two columns of hyphens would say nothing worth the width.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { BreakdownTable } from '@/components/dashboard/BreakdownTable'
import { breakdownRows, orderBreakdown, type BreakdownOrder } from '@/lib/breakdown-order'
import { STATUS_COLORS } from '@/lib/charts'

const breakdown: Record<string, number> = { Northern: 103, Highland: 100, Southern: 97 }

const progress = {
  Northern: { value: 103, target: 150, percent: 68.67, status: 'warning' },
  Highland: { value: 100, target: 100, percent: 100, status: 'ok' },
}

/** The tile's own arithmetic, so the test reads what the widget would show. */
const render = (
  options: {
    order?: BreakdownOrder
    progress?: Record<string, { value: number; target: number | null; percent: number | null; status?: string }>
    lowerIsBetter?: boolean
  } = {},
) => {
  const report = options.progress ?? progress
  return renderToStaticMarkup(
    <BreakdownTable
      rows={breakdownRows(orderBreakdown(Object.entries(breakdown), report, options.order), report)}
      variable="province"
      name="Interviews done"
      valueFormat="number"
      lowerIsBetter={options.lowerIsBetter}
    />,
  )
}

/** The words alone, so a class name cannot stand in for a figure. */
const words = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

describe('a breakdown drawn as a table', () => {
  it('names the variable it is broken down by and what is being counted', () => {
    expect(words(render())).toContain('province Interviews done Target Done')
  })

  it('gives each group its value, its own quota and its share of it', () => {
    const read = words(render())

    expect(read).toContain('Northern 103 150 69%')
    expect(read).toContain('Highland 100 100 100%')
  })

  it('leaves the quota columns empty for a group that has none', () => {
    // Not nought per cent: there is no quota to be nought of.
    expect(words(render())).toContain('Southern 97 - -')
  })

  it('reads a limit as a share of the limit', () => {
    expect(words(render({ lowerIsBetter: true }))).toContain('Of limit')
  })

  it('colours each share the way that group is coloured anywhere else', () => {
    const html = render()

    // Northern is behind and Highland is not, so the two figures cannot be one ink.
    expect(html).toContain(`color:${STATUS_COLORS.warning}`)
    expect(html).toContain(`color:${STATUS_COLORS.ok}`)
    expect(STATUS_COLORS.warning).not.toBe(STATUS_COLORS.ok)
  })

  it('reads in the order the widget was set to', () => {
    const named = words(render({ order: 'name' }))
    const behind = words(render())

    expect(named.indexOf('Highland')).toBeLessThan(named.indexOf('Northern'))
    // The default asks who is behind, which is Northern at 69% of its quota.
    expect(behind.indexOf('Northern')).toBeLessThan(behind.indexOf('Highland'))
  })

  it('drops the quota columns where no group has a quota', () => {
    const read = words(render({ progress: {} }))

    expect(read).toContain('province Interviews done')
    expect(read).not.toContain('Target')
    expect(read).toContain('Northern 103')
  })
})
