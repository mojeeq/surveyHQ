/**
 * The hooks aero.css hangs the page-tab gloss on.
 *
 * `page-tabs`, `page-tab` and `page-tab-on` do nothing on the flat surface,
 * which is what makes them easy to delete in a tidy-up - and the Aero surface
 * would go on being offered while the tabs quietly stopped answering it. That
 * has already happened once to the whole theme, so the markup is pinned here.
 *
 * The stylesheet half cannot be checked from a unit test: vitest returns an
 * empty module for a CSS import, `?raw` included. Anyone renaming these in
 * aero.css has to rename them here too, which these failures will say.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { PageTabs } from '@/components/dashboard/PageTabs'

const noop = () => {}

const render = (active: number) =>
  renderToStaticMarkup(
    <PageTabs
      pages={[{ name: 'Demographic' }, { name: 'Housing' }]}
      active={active}
      count={2}
      canEdit
      widgetsOnPage={0}
      onDark={false}
      onSelect={noop}
      onChange={noop}
      onMove={noop}
      onRemove={noop}
    />,
  )

/** Every class on every element, as the browser would see them. */
const classesIn = (html: string) =>
  [...html.matchAll(/class="([^"]*)"/g)].map((match) => match[1].split(/\s+/).filter(Boolean))

describe('the page tab hooks', () => {
  it('names the strip', () => {
    expect(classesIn(render(0))[0]).toContain('page-tabs')
  })

  it('names every tab, and the open one only', () => {
    const tabs = classesIn(render(1)).filter((list) => list.includes('page-tab'))
    expect(tabs).toHaveLength(2)
    expect(tabs.filter((list) => list.includes('page-tab-on'))).toHaveLength(1)
    // The second page is the open one here, so marking them all - or marking
    // the wrong one - does not slip through on a count alone.
    expect(tabs[1]).toContain('page-tab-on')
  })

  it('keeps the page controls as ghost buttons, which the strip rules reach for', () => {
    expect(classesIn(render(0)).some((list) => list.includes('btn-ghost'))).toBe(true)
  })
})
