import { describe, expect, it } from 'vitest'

import { fitSize, fitTile } from '../useFittedText'

/** A tile 200px tall whose text is `lines` lines of 1.5 × the size, plus fixed bits. */
const tile = (lines: number, fixed = 0, room = 200) => (size: number) => ({
  content: lines * size * 1.5 + fixed,
  room,
})

describe('fitting a tile\'s text to the tile', () => {
  it('keeps the size chosen where it fits', () => {
    expect(fitSize(14, 10, tile(6))).toBe(14)
  })

  it('brings it down until it fits', () => {
    // Six lines at 28px is 252px in a 200px tile.
    const size = fitSize(28, 10, tile(6))
    expect(size).toBeLessThan(28)
    expect(6 * size * 1.5).toBeLessThanOrEqual(201)
  })

  it('accounts for what does not scale, a progress bar say', () => {
    const size = fitSize(28, 10, tile(6, 40))
    expect(6 * size * 1.5 + 40).toBeLessThanOrEqual(201)
  })

  it('stops at the smallest readable size rather than vanishing', () => {
    expect(fitSize(28, 10, tile(40))).toBe(10)
  })

  it('never goes above the size chosen, however much room there is', () => {
    expect(fitSize(12, 10, tile(1, 0, 2000))).toBe(12)
  })
})

/**
 * A tile 200px tall: the number and its variance, always there, then parts
 * that can be left out, each this many lines tall, the first to go first.
 */
const parts = (kept: number, droppable: number[], room = 200) => (size: number, dropped: number) => ({
  content: (kept + droppable.slice(dropped).reduce((sum, lines) => sum + lines, 0)) * size * 1.5,
  room,
})

describe('fitting a tile by leaving parts out', () => {
  it('leaves everything in, at the size chosen, where it all fits', () => {
    expect(fitTile(14, 10, 3, parts(3, [1, 1, 1]))).toEqual({ size: 14, dropped: 0 })
  })

  it('leaves parts out before the text comes down at all', () => {
    // At 14px a line is 21px: 3 kept and 7 droppable is 210px, two over.
    const fit = fitTile(14, 10, 3, parts(3, [2, 3, 2]))
    expect(fit.size).toBe(14)
    // The two-line part goes, and 168px fits.
    expect(fit.dropped).toBe(1)
  })

  it('leaves out as few as it can, in the order given', () => {
    // 3 + 2 + 3 + 2 lines = 210px; without the first two, 105px.
    expect(fitTile(14, 10, 3, parts(3, [2, 3, 2])).dropped).toBe(1)
    expect(fitTile(14, 10, 3, parts(3, [2, 3, 2], 120)).dropped).toBe(2)
  })

  it('brings the text down only when everything that can go has gone', () => {
    // The number alone is 8 lines, 336px at 28px, in a 200px tile.
    const fit = fitTile(28, 10, 2, parts(8, [1, 1]))
    expect(fit.dropped).toBe(2)
    expect(fit.size).toBeLessThan(28)
    expect(8 * fit.size * 1.5).toBeLessThanOrEqual(201)
  })

  it('with nothing it may leave out, fits as the text alone did', () => {
    expect(fitTile(28, 10, 0, (size) => tile(6)(size))).toEqual({
      size: fitSize(28, 10, tile(6)),
      dropped: 0,
    })
  })
})
