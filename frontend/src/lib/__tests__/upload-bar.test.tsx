/**
 * What the bar actually renders. The arithmetic is tested beside this; these
 * pin what somebody staring at a four gigabyte upload is shown, because a bar
 * that is right in principle and stuck at 0% on screen is still a spinner.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { UploadBar } from '@/pages/Datasets'

const render = (progress: {
  sent: number
  total: number
  rate: number
  remaining: number | null
}) => renderToStaticMarkup(<UploadBar progress={progress} />)

/** The words alone. Asserting on markup catches "/s" inside every </span>. */
const words = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

describe('the upload bar', () => {
  it('fills in proportion to what has been sent', () => {
    const html = render({ sent: 1_000_000_000, total: 4_000_000_000, rate: 1e7, remaining: 300 })
    expect(html).toContain('width:25.0%')
    expect(html).toContain('25%')
  })

  it('shows the size, the rate and the time left', () => {
    const html = render({ sent: 2_100_000_000, total: 4_000_000_000, rate: 18_000_000, remaining: 105 })
    expect(html).toContain('2.0 GB')
    expect(html).toContain('3.7 GB')
    expect(html).toContain('17.2 MB/s')
    expect(html).toContain('about 2 minutes left')
  })

  it('offers no rate or estimate before there is one, rather than 0 B/s', () => {
    // The first tick can arrive before any time has passed. "0 B/s, about 0
    // seconds left" on a four gigabyte upload is worse than saying nothing.
    const html = render({ sent: 0, total: 4_000_000_000, rate: 0, remaining: null })
    expect(words(html)).toContain('0%')
    expect(words(html)).not.toContain('/s')
    expect(words(html)).not.toContain('left')
  })

  it('stops promising a transfer once the last byte is across', () => {
    // Every byte is at the server and it is now reading the file. No rate
    // describes that, and a bar sitting at 100% for another five minutes is
    // how people conclude the thing has hung.
    const html = render({ sent: 4_000_000_000, total: 4_000_000_000, rate: 1.8e7, remaining: 0 })
    expect(words(html)).toContain('Reading it now')
    expect(words(html)).not.toContain('/s')
    expect(html).toContain('width:100.0%')
  })

  it('never overflows the bar if the browser reports more than the total', () => {
    const html = render({ sent: 4_200_000_000, total: 4_000_000_000, rate: 1e7, remaining: 0 })
    expect(html).toContain('width:100.0%')
  })
})
