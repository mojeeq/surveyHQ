/* Where every page is loaded from, in one place.
 *
 * Two things need this list and they must not drift: App turns each into a
 * lazy route, and the navigation warms one the moment a pointer lands on its
 * link. A second copy of the imports would eventually disagree with this one,
 * and the symptom - one tab that still stalls - would look like anything but
 * a stale list.
 *
 * The specifiers have to be literal for the bundler to find them, which is why
 * this is a map of functions rather than something built from a path.
 */
export const PAGES = {
  '/': () => import('@/pages/Overview'),
  '/projects': () => import('@/pages/Projects'),
  '/datasets': () => import('@/pages/Datasets'),
  '/connections': () => import('@/pages/Connections'),
  '/explore': () => import('@/pages/Explore'),
  '/dashboards': () => import('@/pages/Dashboards'),
  '/monitoring': () => import('@/pages/Monitoring'),
  '/quality': () => import('@/pages/Quality'),
  '/alerts': () => import('@/pages/Alerts'),
  '/help': () => import('@/pages/Help'),
  '/admin': () => import('@/pages/Admin'),
} as const

export type PagePath = keyof typeof PAGES

/** Pages already asked for, so hovering a link twice costs nothing. */
const asked = new Set<string>()

/**
 * Start fetching a page's code before it is needed.
 *
 * Called when a pointer or the keyboard reaches a navigation link. By the time
 * a click lands the chunk is usually in memory, so the page renders without
 * waiting on the network - which is the difference between changing tab and
 * watching it load. Dashboards and Analyse pull the charting library too, a
 * megabyte that is very visible to wait for.
 *
 * Failure is ignored on purpose: this is an optimisation, and a chunk that
 * will not download here will be asked for again by the click, which is where
 * the error belongs.
 */
export function warm(path: string): void {
  if (asked.has(path)) return
  const load = PAGES[path as PagePath]
  if (!load) return
  asked.add(path)
  void load().catch(() => asked.delete(path))
}
