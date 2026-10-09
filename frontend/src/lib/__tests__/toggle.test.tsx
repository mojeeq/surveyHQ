/**
 * The switch's knob, which has to stay on the switch.
 *
 * It is positioned absolutely with no `left` of its own in the broken
 * version, so it falls back to its static position. A button centres its
 * content, which puts that position at the middle of the track rather than
 * its start, and the travel was then measured from 18px instead of 0: checked
 * the knob finished 14px past the right edge and sat on top of the label,
 * unchecked it was pinned to the right edge and read as switched on.
 *
 * Classes rather than pixels, because there is no DOM here to measure in. The
 * arithmetic they stand for is in the component's comment and was checked in
 * a browser: track 36, knob 16, 2 either side, travel exactly 16.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Toggle } from '@/components/ui'

const knobOf = (checked: boolean) => {
  const html = renderToStaticMarkup(<Toggle checked={checked} onChange={() => {}} label="x" />)
  const found = html.match(/<span class="([^"]*absolute[^"]*)"/)
  expect(found, 'the knob is not in the markup').toBeTruthy()
  return found![1].split(/\s+/)
}

describe('the switch knob', () => {
  it('says where its left edge is, in both states', () => {
    // The whole bug. Without this the browser picks the position, and picks
    // the middle of the track.
    for (const checked of [true, false]) {
      expect(knobOf(checked).some((c) => /^left-/.test(c)), `checked=${checked}`).toBe(true)
    }
  })

  it('starts at the left and travels right', () => {
    expect(knobOf(false)).toContain('translate-x-0')
    expect(knobOf(true)).toContain('translate-x-4')
  })

  it('travels exactly the width of the track less the knob and its margins', () => {
    // 36 - 16 - 2 - 2 = 16, which is translate-x-4. A knob that travels
    // further leaves the track; one that travels less stops short of the end
    // and the switch reads as half on.
    const track = renderToStaticMarkup(<Toggle checked onChange={() => {}} />)
    expect(track).toContain('w-9')
    expect(track).toContain('h-5')
    const knob = knobOf(true)
    expect(knob).toContain('w-4')
    expect(knob).toContain('left-0.5')
    expect(knob).toContain('translate-x-4')
  })

  it('is still a switch to a screen reader, in both states', () => {
    expect(renderToStaticMarkup(<Toggle checked onChange={() => {}} />)).toContain(
      'role="switch" aria-checked="true"',
    )
    expect(renderToStaticMarkup(<Toggle checked={false} onChange={() => {}} />)).toContain(
      'role="switch" aria-checked="false"',
    )
  })
})
