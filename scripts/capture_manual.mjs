/**
 * Capture the screenshots the user manual is built from.
 *
 * Every picture in the manual is of a running instance carrying a demonstration
 * survey, rather than a mock-up, so it has to be re-captured whenever the
 * interface changes. Point this at an instance holding data worth showing:
 *
 *   node scripts/capture_manual.mjs \
 *     --url http://localhost:5173 \
 *     --email admin@example.com --password ... \
 *     --dashboard <dashboard id> --dataset <dataset id>
 *
 * Needs playwright and a Chromium it can find (PLAYWRIGHT_BROWSERS_PATH, or
 * pass --chromium). Writes into docs/manual/, at twice the pixel size so the
 * pictures stay sharp when Word scales them onto a page.
 */
import { chromium } from 'playwright'
import { mkdirSync } from 'fs'
import { dirname, resolve } from 'path'
import { fileURLToPath } from 'url'

const argument = (name, fallback = '') => {
  const at = process.argv.indexOf(`--${name}`)
  return at > -1 ? process.argv[at + 1] : fallback
}

const BASE = argument('url', 'http://127.0.0.1:5173').replace(/\/$/, '')
const EMAIL = argument('email', 'admin@example.com')
const PASSWORD = argument('password')
const BOARD = argument('dashboard')
const DATASET = argument('dataset')
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'docs', 'manual')

if (!PASSWORD || !BOARD || !DATASET) {
  console.error('Needs --password, --dashboard and --dataset. See the comment at the top.')
  process.exit(1)
}
mkdirSync(OUT, { recursive: true })

const launch = { executablePath: argument('chromium') || undefined }
const browser = await chromium.launch(launch)
const view = { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 }
const page = await browser.newPage(view)

/** Park the pointer off the content: hover-only controls should not be in a manual. */
const park = () => page.mouse.move(4, 880)
const shot = async (name, options = {}) => {
  await park()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${OUT}/${name}.png`, ...options })
  console.log('  captured', name)
}
const visit = async (path, settle = 3000) => {
  await page.goto(BASE + path, { waitUntil: 'networkidle' })
  await page.waitForTimeout(settle)
}

await visit('/login', 1500)
await shot('01-sign-in')
await page.fill('input[type=email]', EMAIL)
await page.fill('input[type=password]', PASSWORD)
await page.click('button.btn-primary')
await page.waitForURL((url) => !url.pathname.includes('login'), { timeout: 20000 })
await page.waitForTimeout(4000)
await shot('02-overview', { fullPage: true })

for (const [name, path, settle, full] of [
  ['03-projects', '/projects', 2500, false],
  ['04-datasets', '/datasets', 3000, false],
  ['06-dashboards', '/dashboards', 2500, false],
  ['09-monitoring', '/monitoring', 4500, true],
  ['10-quality', '/quality', 4000, true],
  ['11-alerts', '/alerts', 2500, false],
  ['12-connections', '/connections', 2500, false],
]) {
  await visit(path, settle)
  await shot(name, full ? { fullPage: true } : {})
}

await visit(`/datasets/${DATASET}`, 3000)
await shot('04b-dataset-detail')

// Explore, with something actually on screen: an empty result page teaches nothing.
await visit('/explore', 3000)
const suggestion = page.locator('[class*=chip], button').filter({ hasText: /^Distribution of / }).first()
if (await suggestion.count()) {
  await suggestion.click()
  await page.waitForTimeout(4000)
}
await shot('05-explore')
await page.locator('button:has-text("Cross-tabulation")').first().click().catch(() => {})
await page.waitForTimeout(3500)
await shot('05b-crosstab')

// The boundary library sits under the datasets.
await visit('/datasets', 3000)
const boundaries = page.locator('section', { hasText: 'Boundaries' }).last()
await boundaries.scrollIntoViewIfNeeded()
await page.waitForTimeout(1200)
await shot('18-boundaries', { clip: await boundaries.boundingBox() })

// The dashboard, its dialogs, and the map.
await visit(`/dashboards/${BOARD}`, 7000)
await shot('07-dashboard', { fullPage: true })

const map = page.locator('.react-grid-item').filter({ hasText: /map|fieldwork|location/i }).first()
if (await map.count()) {
  await map.scrollIntoViewIfNeeded()
  await page.waitForTimeout(4000)
  await shot('07b-map-widget', { clip: await map.boundingBox() })
  await map.hover()
  await page.waitForTimeout(600)
  const expand = map.locator('button[aria-label^="Expand "]')
  if (await expand.count()) {
    await expand.click()
    await page.waitForTimeout(5000)
    await shot('20-fullscreen-map')
    await page.locator('button:has-text("Close")').first().click()
    await page.waitForTimeout(1200)
  }
}

for (const [name, button] of [
  ['13-filters-dialog', 'Filters'],
  ['14-appearance-dialog', 'Appearance'],
  ['15-add-widget', 'Add widget'],
  ['16-share-links', 'Share'],
]) {
  await page.locator(`button:has-text("${button}")`).first().click()
  await page.waitForTimeout(2500)
  await shot(name)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(900)
}

const first = page.locator('.react-grid-item').first()
await first.hover()
await page.waitForTimeout(600)
await first.locator('button[aria-label^="Edit "]').click()
await page.waitForTimeout(2500)
await shot('17-widget-settings')
await page.keyboard.press('Escape')

console.log(`\nwrote ${OUT}`)
console.log('The shared-link pictures need a link and a browser with no account;')
console.log('capture 21-shared-dashboard and 22-password-door by hand if they change.')
await browser.close()
