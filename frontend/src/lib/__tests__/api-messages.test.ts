/**
 * What a rejected request says on screen.
 *
 * The server validates with pydantic, which prefixes a message written for a
 * reader with the name of the exception that carried it. "Value error, the
 * formula uses 'part_2', which is not one of its parts" is a sentence somebody
 * can act on with three words of library noise in front of it, under a form
 * where every other line was written to be read.
 */
import { describe, expect, it } from 'vitest'
import { allPages, plainly, withoutWords } from '@/lib/api'

describe('plainly', () => {
  it('drops the prefix a validator puts in front of its message', () => {
    expect(plainly("Value error, the formula uses 'part_2', which is not one of its parts"))
      .toBe("the formula uses 'part_2', which is not one of its parts")
  })

  it('drops the other two the same library writes', () => {
    expect(plainly('Type error, a number was expected')).toBe('a number was expected')
    expect(plainly('Assertion error, that cannot be')).toBe('that cannot be')
  })

  it('leaves a message that was written as one alone', () => {
    expect(plainly('Dataset is not available')).toBe('Dataset is not available')
    // Not a prefix: the sentence is about a value error, it does not open with
    // the library's label for one.
    expect(plainly('A value error is not what happened')).toBe(
      'A value error is not what happened',
    )
  })

  it('is not upset by an empty message', () => {
    expect(plainly('')).toBe('')
  })
})

describe('a refusal that carried no words of its own', () => {
  it('says a bare 413 came from a proxy in front, not from SurveyHQ', () => {
    // SurveyHQ's own limit always names the size and the limit, so this one
    // was a host nginx at its 1 MB default, a Caddy limit, or a CDN.
    const said = withoutWords(413)
    expect(said).toMatch(/refused before it reached SurveyHQ/)
    expect(said).toMatch(/Troubleshooting/)
  })

  it('leaves every other status as it was', () => {
    expect(withoutWords(500)).toBe('Request failed with status 500')
  })
})

describe('every page of a list', () => {
  const rows = Array.from({ length: 450 }, (_, i) => i)
  const server = async (path: string) => {
    const url = new URL(path, 'http://x')
    const offset = Number(url.searchParams.get('offset'))
    const limit = Number(url.searchParams.get('limit'))
    return { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset }
  }

  it('walks past the first 200 rather than stopping there', async () => {
    const all = await allPages('/datasets?status=ready', server)
    expect(all.items).toHaveLength(450)
    expect(all.total).toBe(450)
  })

  it('keeps the filters it was asked for', async () => {
    const asked: string[] = []
    await allPages('/datasets?status=ready', async (path) => {
      asked.push(path)
      return server(path)
    })
    expect(asked.every((one) => one.includes('status=ready'))).toBe(true)
  })

  it('stops on a short page even if the total said there were more', async () => {
    const shrinking = async (path: string) => ({ ...(await server(path)), total: 10_000 })
    const all = await allPages('/datasets', shrinking)
    expect(all.items).toHaveLength(450)
  })
})
