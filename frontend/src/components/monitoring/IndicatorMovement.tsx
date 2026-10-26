/*
 * The lines under an indicator's number: how it has moved and where that
 * leads. Worded in lib/movement, so every place an indicator is shown says it
 * the same way.
 */
import { movementLines } from '@/lib/movement'
import type { Movement } from '@/lib/movement'

const TONES = {
  good: 'text-emerald-700 dark:text-emerald-400',
  bad: 'text-rose-700 dark:text-rose-400',
  plain: 'text-ink-500 dark:text-dark-500',
} as const

export default function IndicatorMovement({
  movement,
  format,
  unit,
  direction,
  target,
}: {
  movement?: Movement
  format: string
  unit: string
  direction: string
  target: number | null | undefined
}) {
  const lines = movementLines(movement, { format, unit, direction, target: target ?? null })
  if (!lines.length) return null
  return (
    <div className="mt-1 space-y-0.5">
      {lines.map((line) => (
        <p key={line.text} className={`text-xs ${TONES[line.tone]}`}>
          {line.text}
        </p>
      ))}
    </div>
  )
}
