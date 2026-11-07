/**
 * What the Overview's panels may claim from what their requests returned.
 *
 * The page used to read a failed request as an empty one: a failed indicator
 * request showed "No indicators yet", and a failed alerts request beside an
 * empty problems list showed "Nothing is flagged right now". These pin the
 * rule that replaced that: "nothing here" only after the request succeeded.
 */
import { describe, expect, it } from 'vitest'

import { attentionPanel, panelState, type QuerySnapshot } from '@/lib/panel-state'

const failure = new Error('Request failed with status 500')
const isEmpty = (rows: number[]) => rows.length === 0

const loading = <T>(): QuerySnapshot<T> => ({ data: undefined, error: null })
const failed = <T>(): QuerySnapshot<T> => ({ data: undefined, error: failure })
const ok = <T>(data: T, at = 1_000): QuerySnapshot<T> => ({ data, error: null, dataUpdatedAt: at })
/** What TanStack Query keeps when a refresh fails: the old data and the new error. */
const staleAfterFailure = <T>(data: T, at = 1_000): QuerySnapshot<T> => ({
  data,
  error: failure,
  dataUpdatedAt: at,
})

describe('a panel fed by one request', () => {
  it('is loading until the first answer arrives', () => {
    expect(panelState(loading<number[]>(), isEmpty)).toEqual({ state: 'loading' })
  })

  it('reports a failed first request as a failure, never as empty', () => {
    expect(panelState(failed<number[]>(), isEmpty)).toEqual({ state: 'error', error: failure })
  })

  it('is empty only when the request succeeded with nothing in it', () => {
    expect(panelState(ok<number[]>([]), isEmpty)).toEqual({ state: 'empty' })
  })

  it('shows what came back', () => {
    expect(panelState(ok([1, 2]), isEmpty)).toEqual({ state: 'ready', data: [1, 2] })
  })

  it('keeps earlier figures after a failed refresh, marked as out of date', () => {
    expect(panelState(staleAfterFailure([1, 2], 5_000), isEmpty)).toEqual({
      state: 'stale',
      data: [1, 2],
      error: failure,
      updatedAt: 5_000,
    })
  })

  it('does not show an earlier empty result as current after a failed refresh', () => {
    expect(panelState(staleAfterFailure<number[]>([]), isEmpty)).toEqual({
      state: 'error',
      error: failure,
    })
  })
})

describe('Needs attention, fed by problems and open alerts', () => {
  const problems = (query: QuerySnapshot<string[]>) => ({ label: 'problems', query })
  const alerts = (query: QuerySnapshot<number[]>) => ({ label: 'open alerts', query })

  it('waits for both before saying anything', () => {
    expect(attentionPanel(problems(loading()), alerts(loading()))).toEqual({ state: 'loading' })
    expect(attentionPanel(problems(ok([])), alerts(loading()))).toEqual({ state: 'loading' })
  })

  it('gives the all-clear only when both answered with nothing', () => {
    expect(attentionPanel(problems(ok([])), alerts(ok([])))).toEqual({ state: 'clear' })
  })

  it('is a failure, not an all-clear, when the alerts request fails', () => {
    expect(attentionPanel(problems(ok([])), alerts(failed()))).toEqual({
      state: 'error',
      error: failure,
      failed: ['open alerts'],
    })
  })

  it('is a failure, not an all-clear, when the problems request fails', () => {
    expect(attentionPanel(problems(failed()), alerts(ok([])))).toEqual({
      state: 'error',
      error: failure,
      failed: ['problems'],
    })
  })

  it('names both when both fail', () => {
    const panel = attentionPanel(problems(failed()), alerts(failed()))
    expect(panel).toMatchObject({ state: 'error', failed: ['problems', 'open alerts'] })
  })

  it('lists what it has and says the list may be incomplete when one source failed', () => {
    expect(attentionPanel(problems(ok(['check failing'])), alerts(failed()))).toEqual({
      state: 'items',
      first: ['check failing'],
      second: [],
      failed: ['open alerts'],
      stale: false,
    })
  })

  it('marks items kept from before a failed refresh as stale', () => {
    const panel = attentionPanel(problems(ok([])), alerts(staleAfterFailure([7])))
    expect(panel).toEqual({ state: 'items', first: [], second: [7], failed: ['open alerts'], stale: true })
  })

  it('shows what one source found while the other is still loading', () => {
    expect(attentionPanel(problems(ok(['import failed'])), alerts(loading()))).toEqual({
      state: 'items',
      first: ['import failed'],
      second: [],
      failed: [],
      stale: false,
    })
  })
})
