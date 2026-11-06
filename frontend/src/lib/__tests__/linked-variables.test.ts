import { describe, expect, it } from 'vitest'

import { broughtFrom, describeLink, offers, ownVariables, type LinkedVariables } from '../linked-variables'
import type { Variable } from '../types'

const variable = (name: string, label = ''): Variable => ({ name, label }) as Variable

const link: LinkedVariables = {
  id: 'l1',
  source_id: 'h',
  source_name: 'households',
  source_exists: true,
  keys: [{ here: 'hhid', there: 'hhid' }],
  key_match: 'exact',
  variables: ['size'],
  status: {},
}

describe('a link in a sentence', () => {
  it('names what comes in, from where, and on what', () => {
    expect(describeLink(link)).toBe('size from households, matched on hhid')
    expect(
      describeLink({
        ...link,
        variables: ['district', 'region'],
        keys: [{ here: 'hhid', there: 'code' }],
        key_match: 'number',
      }),
    ).toBe('district, region from households, matched on hhid = code (as numbers)')
  })
})

describe('what the form offers', () => {
  const target = [variable('pid'), variable('hhid'), variable('age'), variable('size')]
  const source = [variable('hhid'), variable('size'), variable('province', 'Province'), variable('size__mv')]

  it('leaves out the key and the hidden companions', () => {
    const names = offers(source, target, [{ here: 'hhid', there: 'hhid' }], []).map((one) => one.name)
    expect(names).toEqual(['size', 'province'])
  })

  it('shows a variable this dataset already has, but not as a choice', () => {
    const size = offers(source, target, [{ here: 'hhid', there: 'hhid' }], []).find((one) => one.name === 'size')
    expect(size?.unavailable).toBe('size is already in this dataset')
  })

  it('says which one was brought in already, and from where', () => {
    const size = offers(source, target, [{ here: 'hhid', there: 'hhid' }], [link]).find((one) => one.name === 'size')
    expect(size?.unavailable).toBe('Already brought in from households')
  })

  it('matches only on the dataset own variables', () => {
    expect(ownVariables(target, [link]).map((one) => one.name)).toEqual(['pid', 'hhid', 'age'])
    expect(broughtFrom([link])).toEqual({ size: 'households' })
  })
})
