/**
 * What a set of per-group quotas adds up to, and whether that is the headline.
 *
 * A broken-down indicator's groups each carry their own quota - so many
 * interviews in this enumeration area, so many in that one - and the headline
 * target is what those add up to. Nothing enforces it, because a survey often
 * has quotas for some groups and not others and the headline may legitimately
 * be the national figure while only a few areas are being watched.
 *
 * But a form with sixty number boxes in it is exactly where a digit gets
 * dropped, and nothing else in the platform would ever mention it. So the sum
 * is said under the list, in words, next to what it was supposed to be.
 */
export interface QuotaSummary {
  /** How many groups carry a quota of their own. */
  set: number
  /** What those quotas add up to. */
  total: number
  /** The headline, where one is set. */
  headline: number | null
  /** total - headline, or null where there is no headline to compare with. */
  difference: number | null
}

/** A number as typed into one of the boxes, or null where it is not one. */
function typed(value: string | number | undefined | null): number | null {
  if (value === undefined || value === null || String(value).trim() === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

export function quotaSummary(
  targets: Record<string, string | number | undefined>,
  headline: string | number | undefined,
): QuotaSummary {
  let set = 0
  let total = 0
  for (const raw of Object.values(targets ?? {})) {
    const number = typed(raw)
    if (number === null) continue
    set += 1
    total += number
  }
  const whole = typed(headline)
  return {
    set,
    total,
    headline: whole,
    // Rounded because a sum of decimals can land on 14999.999999999998, and a
    // note saying the quotas are 0.000000000002 short of the target is worse
    // than no note at all.
    difference: whole === null ? null : Math.round((total - whole) * 100) / 100,
  }
}
