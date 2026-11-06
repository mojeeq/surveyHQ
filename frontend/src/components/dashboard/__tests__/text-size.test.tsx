/**
 * One text size for a widget, reaching everything it draws.
 *
 * It was offered on charts and quality panels only, and on a chart it reached
 * the axes and nothing else: an indicator's number, a cross-tab and a table
 * stayed the size they were, however far across the room the board was read.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import IndicatorMovement from '@/components/monitoring/IndicatorMovement'
import {
  DEFAULT_CHART_TEXT,
  DEFAULT_PANEL_TEXT,
  DEFAULT_TILE_TEXT,
  SIZED_KINDS,
  panelDefault,
} from '@/components/dashboard/shared'

describe('the text size control', () => {
  it('is offered on every widget whose text is the point of it', () => {
    for (const kind of ['chart', 'indicator', 'quality', 'text', 'countdown']) {
      expect(SIZED_KINDS.has(kind), kind).toBe(true)
    }
    for (const kind of ['map', 'html', 'freshness']) {
      expect(SIZED_KINDS.has(kind), kind).toBe(false)
    }
  })

  it('starts where each kind of widget is drawn by default', () => {
    expect(panelDefault('chart')).toBe(DEFAULT_CHART_TEXT)
    expect(panelDefault('quality')).toBe(DEFAULT_PANEL_TEXT)
    // A tile's lines are 14px and its number 15/7 of that, the 30px it was.
    expect(panelDefault('indicator')).toBe(DEFAULT_TILE_TEXT)
    expect(Math.round(DEFAULT_TILE_TEXT * 2.143)).toBe(30)
    expect(panelDefault('countdown')).toBe(DEFAULT_TILE_TEXT)
    expect(panelDefault('text')).toBe(DEFAULT_TILE_TEXT)
  })
})

describe('the lines under an indicator', () => {
  const movement = { change_day: -4, change_week: 12, pace_per_day: 3.7, pace_days: 7 }

  it('follow the tile when it is sized, and stay 12px everywhere else', () => {
    const scaled = renderToStaticMarkup(
      <IndicatorMovement movement={movement} format="number" unit="" direction="higher_is_better" target={null} scaled />,
    )
    const fixed = renderToStaticMarkup(
      <IndicatorMovement movement={movement} format="number" unit="" direction="higher_is_better" target={null} />,
    )
    expect(fixed, 'the movement should be worded as lines').toContain('since yesterday')
    expect(scaled).toContain('text-[0.857em]')
    expect(scaled).not.toContain('text-xs')
    expect(fixed).toContain('text-xs')
  })
})
