import { useState } from 'react'

/**
 * One small choice about a page, kept between visits.
 *
 * How somebody wants a list shown - cards or rows, and in what order - is a
 * preference, not a navigation state: having to set it again on every visit is
 * the reason people stop using the control at all. There is nothing
 * confidential in it, so it lives in the browser rather than on the account.
 *
 * Wrapped in try/catch throughout because localStorage throws in a private
 * window and in some embedded browsers. A page that cannot remember still
 * works; it just opens on the fallback.
 */
export function useRemembered<T extends string>(
  key: string,
  fallback: T,
  allowed: readonly T[],
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(`surveyhq.${key}`)
      // Checked against the list rather than trusted: a stored value can
      // outlive the option it named, and a sort key nothing reads any more
      // would leave the list in no order at all.
      if (stored && (allowed as readonly string[]).includes(stored)) return stored as T
    } catch {
      /* private window, or nothing stored yet */
    }
    return fallback
  })

  const remember = (next: T) => {
    setValue(next)
    try {
      localStorage.setItem(`surveyhq.${key}`, next)
    } catch {
      /* the page still works, it just will not remember */
    }
  }

  return [value, remember]
}
