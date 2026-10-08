/**
 * The upload talks to the API through XMLHttpRequest rather than fetch, because
 * fetch cannot report how far a transfer has got. That means a second code path
 * to the same API, hand-written, and a second code path that answers
 * differently is worse than no progress bar: an expired session that does not
 * sign you out, or a 422 whose reason never reaches the screen.
 *
 * These pin the contract the rest of the client already offers.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, ApiError, tokenStore } from '@/lib/api'

type Sent = { loaded: number; total: number }

class FakeXHR {
  static last: FakeXHR
  status = 200
  responseText = '{}'
  headers: Record<string, string> = {}
  sentBody: unknown = null
  upload = { onprogress: null as ((event: Sent & { lengthComputable: boolean }) => void) | null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  method = ''
  url = ''

  constructor() {
    FakeXHR.last = this
  }
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  setRequestHeader(key: string, value: string) {
    this.headers[key] = value
  }
  send(body: unknown) {
    this.sentBody = body
  }
  /** Drive the transfer, then the response, the way a browser would. */
  deliver(chunks: Sent[]) {
    for (const chunk of chunks) {
      this.upload.onprogress?.({ ...chunk, lengthComputable: true })
    }
  }
  finish(status: number, body: unknown) {
    this.status = status
    this.responseText = body === undefined ? '' : JSON.stringify(body)
    this.onload?.()
  }
}

beforeEach(() => {
  vi.stubGlobal('XMLHttpRequest', FakeXHR)
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  })
  vi.stubGlobal('sessionStorage', { getItem: () => null, setItem: () => {} })
  vi.stubGlobal('location', { pathname: '/datasets', href: '/datasets' })
})

afterEach(() => vi.unstubAllGlobals())

describe('uploading with progress', () => {
  it('carries the signed-in token, as every other call does', async () => {
    tokenStore.set('a-token')
    const pending = api.upload('/datasets/upload', new FormData())
    FakeXHR.last.finish(200, { id: 'd1' })
    await pending
    expect(FakeXHR.last.headers.Authorization).toBe('Bearer a-token')
    expect(FakeXHR.last.method).toBe('POST')
    expect(FakeXHR.last.url).toBe('/api/v1/datasets/upload')
  })

  it('never sets Content-Type, which would break the multipart body', async () => {
    // The browser writes it with the boundary. Ours would have no boundary and
    // the server would fail to parse a request that looked perfectly fine.
    const pending = api.upload('/datasets/upload', new FormData())
    FakeXHR.last.finish(200, {})
    await pending
    expect(Object.keys(FakeXHR.last.headers)).not.toContain('Content-Type')
  })

  it('works out the rate and the time left from the clock', async () => {
    // A controlled clock, because the arithmetic is the whole point: a bar
    // that says "about 2 minutes" when it means twenty is worse than silence.
    let now = 1_000_000
    vi.spyOn(Date, 'now').mockImplementation(() => now)

    const seen: { sent: number; rate: number; remaining: number | null }[] = []
    const pending = api.upload('/datasets/upload', new FormData(), (p) =>
      seen.push({ sent: p.sent, rate: p.rate, remaining: p.remaining }),
    )

    now += 1_000 // one second in
    FakeXHR.last.deliver([{ loaded: 1_000, total: 4_000 }])
    now += 1_000 // two seconds in
    FakeXHR.last.deliver([{ loaded: 2_000, total: 4_000 }])
    FakeXHR.last.finish(200, {})
    await pending

    expect(seen[0].rate).toBe(1_000)
    expect(seen[0].remaining).toBe(3) // 3,000 bytes to go at 1,000 a second
    expect(seen[1].rate).toBe(1_000) // 2,000 bytes in two seconds
    expect(seen[1].remaining).toBe(2)
  })

  it('offers no estimate rather than a made-up one before any time has passed', async () => {
    // The first event can arrive in the same millisecond the request opened.
    // There is no rate to be had from that, and inventing one puts a number on
    // the screen that is wrong by a factor of anything.
    let now = 1_000_000
    vi.spyOn(Date, 'now').mockImplementation(() => now)
    const seen: (number | null)[] = []
    const pending = api.upload('/datasets/upload', new FormData(), (p) =>
      seen.push(p.remaining),
    )
    FakeXHR.last.deliver([{ loaded: 10, total: 4_000 }])
    FakeXHR.last.finish(200, {})
    await pending
    expect(seen).toEqual([null])
  })

  it('passes the server its own words on a refusal', async () => {
    // The upload route's 422s explain what to do instead - upload the files one
    // at a time, drop the version column. A generic "request failed" wastes it.
    const pending = api.upload('/datasets/upload', new FormData())
    FakeXHR.last.finish(422, { detail: 'These files each become their own dataset' })
    await expect(pending).rejects.toThrow('These files each become their own dataset')
  })

  it('reads a validation error list the way the rest of the client does', async () => {
    const pending = api.upload('/datasets/upload', new FormData())
    FakeXHR.last.finish(422, { detail: [{ msg: 'file is required' }] })
    await expect(pending).rejects.toThrow('file is required')
  })

  it('signs out an expired session, as every other call does', async () => {
    tokenStore.set('stale')
    const pending = api.upload('/datasets/upload', new FormData())
    FakeXHR.last.finish(401, { detail: 'nope' })
    await expect(pending).rejects.toBeInstanceOf(ApiError)
    expect(tokenStore.get()).toBeNull()
  })

  it('does not sign anybody out when a locked shared link asks for its password', async () => {
    // A 401 there means "this link wants a password", not "your session died".
    // Clearing the token would sign out a signed-in user for opening a link.
    tokenStore.set('a-token')
    const pending = api.upload('/public/dashboards/abc/upload', new FormData())
    FakeXHR.last.finish(401, { detail: 'Password required' })
    await expect(pending).rejects.toThrow('Password required')
    expect(tokenStore.get()).toBe('a-token')
  })

  it('says the server is unreachable rather than failing silently', async () => {
    const pending = api.upload('/datasets/upload', new FormData())
    FakeXHR.last.onerror?.()
    await expect(pending).rejects.toThrow('Could not reach the server')
  })
})
