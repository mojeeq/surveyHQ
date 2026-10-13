/**
 * What sits where above a dashboard's widgets.
 *
 * The tab strip is above the filter bar, and that order is load-bearing
 * rather than taste. A page's filters belong to that page, so their number
 * changes from page to page; with the bar above, the tabs moved up and down
 * under the pointer as somebody clicked along them - a row of buttons that
 * will not hold still while it is being used.
 *
 * Read off the source because the view itself cannot be rendered here: it
 * reaches a map library that wants a browser. The order is one line apart in
 * one file, which is exactly the kind of thing a tidy-up moves back.
 */
import { describe, expect, it } from 'vitest'

import view from '@/pages/DashboardView.tsx?raw'

describe('the bars above a dashboard', () => {
  it('puts the page tabs above the filter bar', () => {
    const tabs = view.indexOf('<PageTabs')
    const filters = view.indexOf('<DashboardFilters')

    expect(tabs).toBeGreaterThan(-1)
    expect(filters).toBeGreaterThan(-1)
    expect(tabs).toBeLessThan(filters)
  })

  it('still draws both of them', () => {
    // A guard that passes because one of them is gone would be worse than none.
    expect(view).toContain('controls={pageControls}')
    expect(view).toContain('onSelect={setActivePage}')
  })
})
