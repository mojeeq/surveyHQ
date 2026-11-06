/**
 * A tile whose contents fit the box it is in.
 *
 * Every size in a number tile is a share of one base size, so a tile set to a
 * large text size for a board on a wall grew everything at once: the headline,
 * the "430 behind target" under it, the "no change since yesterday" under
 * that. In a tile of ordinary height the lines at the bottom ran out of the
 * tile and were cut off.
 *
 * The first answer was to bring the text down until it fitted, and on a board
 * of busy tiles that meant every line at 10px - smaller than anybody chose,
 * and still with a scroll bar. The size chosen is now kept. What a short tile
 * cannot hold is left out instead, least needed first (the parts marked
 * `data-fit`, in the order given), and only a tile too short even for its
 * number has its text brought down.
 */
import { useLayoutEffect, useRef, useState } from 'react'

/** How tall the content is at a size, against the room there is for it. */
export type Measure = (size: number) => { content: number; room: number }

/**
 * The largest size, at most `preferred` and at least `minimum`, at which the
 * content fits. Stepped rather than solved, because not everything in a tile
 * scales with the text - a progress bar and a sparkline are fixed in pixels -
 * so shrinking by the overflow ratio once can still leave it a little over.
 */
export function fitSize(preferred: number, minimum: number, measure: Measure): number {
  const floor = Math.min(minimum, preferred)
  let size = preferred
  for (let step = 0; step < 8; step++) {
    const { content, room } = measure(size)
    if (content <= room + 1 || size <= floor) break
    const ratio = Math.max(0.5, Math.min(0.95, room / content))
    size = Math.max(floor, Math.floor(size * ratio * 10) / 10)
  }
  return size
}

/** How tall the content is at a size with the first `dropped` parts left out. */
export type TileMeasure = (size: number, dropped: number) => { content: number; room: number }

/**
 * At the size chosen, the fewest of `parts` left out for the rest to fit. Only
 * where all of them out is still too tall does the size come down, and then
 * as far as `fitSize` takes it.
 */
export function fitTile(
  preferred: number,
  minimum: number,
  parts: number,
  measure: TileMeasure,
): { size: number; dropped: number } {
  for (let dropped = 0; dropped <= parts; dropped++) {
    const { content, room } = measure(preferred, dropped)
    if (content <= room + 1) return { size: preferred, dropped }
  }
  return {
    size: fitSize(preferred, minimum, (size) => measure(size, parts)),
    dropped: parts,
  }
}

/** Show or hide each marked part: the first `dropped` names in `order` go. */
function leaveOut(node: HTMLElement, order: readonly string[], dropped: number) {
  order.forEach((name, index) => {
    node.querySelectorAll<HTMLElement>(`[data-fit="${name}"]`).forEach((part) => {
      part.style.display = index < dropped ? 'none' : ''
    })
  })
}

/**
 * Attach the returned ref to the box whose contents should fit, and set its
 * font size from the returned size. `drop` names the parts that may be left
 * out, marked `data-fit="name"` inside the box, the first to go first.
 * Measured again whenever the box changes size and whenever anything in
 * `watch` changes - the numbers inside it, say.
 */
export function useFittedText<T extends HTMLElement>(
  preferred: number,
  minimum = 11,
  watch: unknown[] = [],
  drop: readonly string[] = [],
): [React.RefObject<T>, number] {
  const ref = useRef<T>(null)
  const [size, setSize] = useState(preferred)
  const dropped = useRef(0)

  // The parts left out are hidden on the elements themselves rather than by
  // rendering, so measuring can try each in turn without a render apiece.
  // Put back after every render, in case one drew a part afresh.
  useLayoutEffect(() => {
    if (ref.current) leaveOut(ref.current, drop, dropped.current)
  })

  useLayoutEffect(() => {
    const node = ref.current
    if (!node || typeof ResizeObserver === 'undefined') {
      setSize(preferred)
      return
    }
    const fit = () => {
      const next = fitTile(preferred, minimum, drop.length, (candidate, count) => {
        node.style.fontSize = `${candidate}px`
        leaveOut(node, drop, count)
        return { content: node.scrollHeight, room: node.clientHeight }
      })
      node.style.fontSize = `${next.size}px`
      leaveOut(node, drop, next.dropped)
      dropped.current = next.dropped
      setSize(next.size)
    }
    fit()
    // Only a change of the box's own size refits. The fit itself changes
    // what is inside, and refitting on that would chase its own tail.
    let last = `${node.clientWidth}x${node.clientHeight}`
    const observer = new ResizeObserver(() => {
      const now = `${node.clientWidth}x${node.clientHeight}`
      if (now === last) return
      last = now
      fit()
    })
    observer.observe(node)
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preferred, minimum, drop.join(' '), ...watch])

  return [ref, size]
}

/** The height of a box, kept up to date as it changes. */
export function useHeight<T extends HTMLElement>(
  watch: unknown[] = [],
): [React.RefObject<T>, number | null] {
  const ref = useRef<T>(null)
  const [height, setHeight] = useState<number | null>(null)
  useLayoutEffect(() => {
    const node = ref.current
    if (!node || typeof ResizeObserver === 'undefined') return
    setHeight(node.clientHeight)
    const observer = new ResizeObserver(() => setHeight(node.clientHeight))
    observer.observe(node)
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, watch)
  return [ref, height]
}
