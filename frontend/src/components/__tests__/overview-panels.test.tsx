/**
 * What the Overview's panels actually say in each state.
 *
 * The state rules are pinned in lib/__tests__/panel-state.test.ts; these check
 * the words a reader sees, because the bug was in the words: a failure read as
 * "No indicators yet" or "Nothing is flagged right now".
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { NeedsAttentionBody, PanelBody, type AttentionItem } from '@/components/overview/OverviewPanels'
import { attentionPanel, panelState, type QuerySnapshot } from '@/lib/panel-state'
import type { Alert } from '@/lib/types'

const failure = new Error('Request failed with status 502')
const noop = () => {}

const indicators = (query: QuerySnapshot<string[]>) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <PanelBody
        panel={panelState(query, (rows) => rows.length === 0)}
        what="indicators"
        retry={noop}
        empty={<p>No indicators yet</p>}
      >
        {(rows) => <ul>{rows.map((row) => <li key={row}>{row}</li>)}</ul>}
      </PanelBody>
    </MemoryRouter>,
  )

const attention = (problems: QuerySnapshot<AttentionItem[]>, alerts: QuerySnapshot<Alert[]>) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <NeedsAttentionBody
        panel={attentionPanel(
          { label: 'problems', query: problems },
          { label: 'open alerts', query: alerts },
        )}
        retry={noop}
      />
    </MemoryRouter>,
  )

const problem: AttentionItem = {
  kind: 'quality',
  severity: 'warning',
  title: 'Data quality: Missing GPS',
  detail: '224 rows fail',
  link: '/quality',
  at: null,
}

describe('the Indicators panel', () => {
  it('says the request failed, with a retry, instead of "No indicators yet"', () => {
    const html = indicators({ data: undefined, error: failure })
    expect(html).toContain("Couldn&#x27;t load indicators.")
    expect(html).toContain('Request failed with status 502')
    expect(html).toContain('Try again')
    expect(html).not.toContain('No indicators yet')
  })

  it('shows the onboarding empty state after a successful empty answer', () => {
    expect(indicators({ data: [], error: null })).toContain('No indicators yet')
  })

  it('shows a loading state before the first answer', () => {
    const html = indicators({ data: undefined, error: null })
    expect(html).toContain('Loading')
    expect(html).not.toContain('No indicators yet')
  })

  it('keeps earlier tiles after a failed refresh and says they are out of date', () => {
    const html = indicators({
      data: ['Completed interviews'],
      error: failure,
      dataUpdatedAt: Date.now() - 5 * 60_000,
    })
    expect(html).toContain('Completed interviews')
    expect(html).toContain("Couldn&#x27;t refresh indicators. Showing what was loaded 5 min ago.")
    expect(html).toContain('Try again')
  })
})

describe('the Needs attention panel', () => {
  it('does not say "Nothing is flagged" when the alerts request failed', () => {
    const html = attention({ data: [], error: null }, { data: undefined, error: failure })
    expect(html).not.toContain('Nothing is flagged')
    expect(html).toContain('Couldn&#x27;t check for open alerts.')
    expect(html).toContain('Try again')
  })

  it('does not say "Nothing is flagged" when the problems request failed', () => {
    const html = attention({ data: undefined, error: failure }, { data: [], error: null })
    expect(html).not.toContain('Nothing is flagged')
    expect(html).toContain('Couldn&#x27;t check for problems.')
  })

  it('says "Nothing is flagged" when both answered with nothing', () => {
    expect(attention({ data: [], error: null }, { data: [], error: null })).toContain(
      'Nothing is flagged right now.',
    )
  })

  it('lists what it found and warns that the list may be incomplete', () => {
    const html = attention({ data: [problem], error: null }, { data: undefined, error: failure })
    expect(html).toContain('Data quality: Missing GPS')
    expect(html).toContain('Couldn&#x27;t check for open alerts.')
    expect(html).toContain('This list may not be complete.')
  })
})
