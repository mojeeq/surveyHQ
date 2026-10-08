/**
 * The provider is invisible until something asks.
 *
 * It wraps the whole app, so anything it renders unprompted appears on every
 * page. The rest of its behaviour - the clash message that keeps what you
 * typed, the red button on a destructive confirm, Escape settling the promise
 * so the next dialog still opens - needs a live DOM and is checked against the
 * running app instead; there is no DOM testing library here.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { DialogProvider } from '@/hooks/useDialog'

const words = (html: string) => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()

describe('the dialog provider', () => {
  it('renders its children and nothing else', () => {
    const html = renderToStaticMarkup(
      <DialogProvider>
        <p>the app</p>
      </DialogProvider>,
    )
    expect(words(html)).toBe('the app')
    expect(html).not.toContain('data-modal')
  })
})
