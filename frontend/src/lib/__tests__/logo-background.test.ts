/**
 * A logo's plain background made transparent, and nothing else.
 *
 * The case that matters is a coat of arms on black whose emblem is outlined in
 * black too: the square behind it has to go and the outline has to stay.
 */
import { describe, expect, it } from 'vitest'

import { clearBackground, type Pixels } from '@/lib/logo'

type RGBA = [number, number, number, number]

/** A picture from rows of characters: each a colour from the key. */
function picture(rows: string[], key: Record<string, RGBA>): Pixels {
  const height = rows.length
  const width = rows[0].length
  const data = new Uint8ClampedArray(width * height * 4)
  rows.forEach((row, y) =>
    [...row].forEach((cell, x) => data.set(key[cell], (y * width + x) * 4)),
  )
  return { data, width, height }
}

const alpha = (image: Pixels, x: number, y: number) => image.data[(y * image.width + x) * 4 + 3]

const KEY: Record<string, RGBA> = {
  '.': [0, 0, 0, 255], // the black square
  '#': [200, 30, 40, 255], // the emblem
  'o': [0, 0, 0, 255], // a black outline inside the emblem: the same colour
  '~': [20, 20, 20, 255], // nearly black, as anti-aliasing leaves it
}

describe('clearing a logo\'s plain background', () => {
  it('clears the square and keeps the emblem, black inside it included', () => {
    const image = picture(
      [
        '.......',
        '.#####.',
        '.#ooo#.',
        '.#ooo#.',
        '.#####.',
        '.......',
      ],
      KEY,
    )
    expect(clearBackground(image)).toBe(22)
    expect(alpha(image, 0, 0)).toBe(0)
    expect(alpha(image, 6, 5)).toBe(0)
    expect(alpha(image, 1, 1)).toBe(255) // the emblem
    expect(alpha(image, 3, 2)).toBe(255) // the outline, unreachable from the edge
  })

  it('reaches into a bay that opens onto the edge', () => {
    const image = picture(['..#..', '.#.#.', '.#.#.', '.....'], KEY)
    clearBackground(image)
    expect(alpha(image, 2, 1)).toBe(0)
    expect(alpha(image, 1, 1)).toBe(255)
  })

  it('leaves a picture whose corners do not agree as it was', () => {
    const image = picture(['#....', '.....', '.....', '....#'], KEY)
    expect(clearBackground(image)).toBe(0)
    expect(alpha(image, 1, 1)).toBe(255)
  })

  it('leaves a picture that is already transparent as it was', () => {
    const image = picture(['....', '.##.', '....'], { ...KEY, '.': [0, 0, 0, 0] })
    expect(clearBackground(image)).toBe(0)
  })

  it('softens an anti-aliased edge rather than cutting it', () => {
    const image = picture(['.....', '.~##.', '.....'], KEY)
    clearBackground(image)
    // Twenty-odd away from black: inside the limit, but past the half where a
    // pixel is cleared outright, so it keeps some of its opacity.
    const soft = alpha(image, 1, 1)
    expect(soft).toBeGreaterThan(0)
    expect(soft).toBeLessThan(255)
  })
})
