/**
 * A large upload sent in pieces, as the browser does it.
 *
 * Behind Cloudflare no single request may exceed 100 MB, so a census export
 * goes as pieces and the upload form names them. What is pinned: the pieces
 * cover the file exactly, in order; a dropped piece is resent rather than the
 * whole file; a refusal is not retried; and the bar runs once, empty to full,
 * across every file.
 */
import { describe, expect, it } from 'vitest'

import { ApiError, stagedUpload, withRetries } from '@/lib/api'
import type { StagingTransport, UploadProgress } from '@/lib/api'

const noWait = async () => {}

function fakeServer(chunk: number, failFirst = new Set<string>()) {
  const received = new Map<string, Blob[]>()
  const posted: FormData[] = []
  let next = 0
  const transport: StagingTransport = {
    start: async (file) => {
      const id = `u${next++}`
      received.set(id, [])
      return { id, chunk_size: chunk, pieces: Math.max(1, Math.ceil(file.size / chunk)) }
    },
    send: async (id, index, piece, onSent) => {
      const key = `${id}:${index}`
      if (failFirst.delete(key)) throw new ApiError(0, 'connection dropped')
      received.get(id)![index] = piece
      onSent(piece.size)
    },
    complete: async () => undefined,
    post: async <T,>(form: FormData) => {
      posted.push(form)
      return { ok: true } as T
    },
  }
  return { transport, received, posted }
}

async function text(blobs: Blob[]): Promise<string> {
  return (await Promise.all(blobs.map((one) => one.text()))).join('')
}

describe('a file sent in pieces', () => {
  it('arrives whole, in order, and the form names it instead of carrying it', async () => {
    const file = new File(['abcdefghij'], 'export.zip')
    const form = new FormData()
    form.append('file', file)
    form.append('project_id', 'p1')
    const server = fakeServer(4)

    await stagedUpload(form, [file], server.transport)

    expect(server.received.get('u0')).toHaveLength(3)
    expect(await text(server.received.get('u0')!)).toBe('abcdefghij')
    const sent = server.posted[0]
    expect(sent.getAll('file')).toEqual([])
    expect(sent.get('project_id')).toBe('p1')
    expect(JSON.parse(String(sent.get('staged')))).toEqual(['u0'])
  })

  it('keeps several files apart and in the order given', async () => {
    const one = new File(['1111'], 'v1.zip')
    const two = new File(['22222222'], 'v2.zip')
    const server = fakeServer(4)
    await stagedUpload(new FormData(), [one, two], server.transport)
    expect(JSON.parse(String(server.posted[0].get('staged')))).toEqual(['u0', 'u1'])
    expect(await text(server.received.get('u1')!)).toBe('22222222')
  })

  it('reports one bar from empty to full across every file', async () => {
    const seen: UploadProgress[] = []
    const server = fakeServer(4)
    await stagedUpload(
      new FormData(),
      [new File(['123456'], 'a.zip'), new File(['7890'], 'b.zip')],
      server.transport,
      (progress) => seen.push(progress),
    )
    expect(seen.every((one) => one.total === 10)).toBe(true)
    expect(seen.map((one) => one.sent)).toEqual([...seen.map((one) => one.sent)].sort((a, b) => a - b))
    expect(seen[seen.length - 1].sent).toBe(10)
  })
})

describe('a dropped connection', () => {
  it('resends the one piece, not the file', async () => {
    const file = new File(['abcdefghij'], 'export.zip')
    const server = fakeServer(4, new Set(['u0:1']))
    await stagedUpload(new FormData(), [file], server.transport)
    expect(await text(server.received.get('u0')!)).toBe('abcdefghij')
  })
})

describe('trying again', () => {
  it('resends a piece whose connection dropped', async () => {
    let calls = 0
    const value = await withRetries(
      async () => {
        calls += 1
        if (calls < 3) throw new ApiError(502, 'bad gateway')
        return 'sent'
      },
      4,
      noWait,
    )
    expect(value).toBe('sent')
    expect(calls).toBe(3)
  })

  it('does not retry a refusal, which would only be refused again', async () => {
    let calls = 0
    await expect(
      withRetries(
        async () => {
          calls += 1
          throw new ApiError(422, 'This upload has no piece 9')
        },
        4,
        noWait,
      ),
    ).rejects.toThrow('no piece 9')
    expect(calls).toBe(1)
  })

  it('gives up after the tries it was given', async () => {
    let calls = 0
    await expect(
      withRetries(
        async () => {
          calls += 1
          throw new ApiError(0, 'offline')
        },
        3,
        noWait,
      ),
    ).rejects.toThrow('offline')
    expect(calls).toBe(3)
  })
})
