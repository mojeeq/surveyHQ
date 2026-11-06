import { describe, expect, it } from 'vitest'

import { gettingStarted, nextStep, showGettingStarted } from '@/lib/getting-started'

const states = (done: Record<string, boolean>) =>
  Object.entries(done).map(([key, value]) => ({ key, done: value }))

describe('the getting-started list', () => {
  it('words the steps the server sent, in its order', () => {
    const steps = gettingStarted(states({ project: true, data: false }))
    expect(steps.map((step) => step.title)).toEqual(['Create a project', 'Bring in your data'])
    expect(steps[1].to).toBe('/datasets')
  })

  it('leaves out a step it has no words for rather than showing a key', () => {
    expect(gettingStarted(states({ project: false, something_new: false }))).toHaveLength(1)
  })

  it('points at the first step not done', () => {
    const steps = gettingStarted(states({ project: true, data: false, quality: false }))
    expect(nextStep(steps)?.key).toBe('data')
  })

  it('shows while there is something left to do', () => {
    expect(showGettingStarted(gettingStarted(states({ project: true, data: false })), null)).toBe(
      true,
    )
  })

  it('goes once everything is done, as on a workspace set up before it existed', () => {
    expect(showGettingStarted(gettingStarted(states({ project: true, data: true })), null)).toBe(
      false,
    )
  })

  it('goes when put away, done or not', () => {
    expect(showGettingStarted(gettingStarted(states({ project: false })), true)).toBe(false)
  })

  it('has nothing to show for somebody given no steps', () => {
    expect(showGettingStarted([], null)).toBe(false)
  })
})
