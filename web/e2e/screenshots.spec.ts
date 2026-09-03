/**
 * Screen capture pass — one full-page PNG per screen into e2e/screens/.
 *
 * Written so it is useful with or without a reachable backend: the login screen
 * renders from static markup, so it always captures. Everything behind auth is
 * skipped (not failed) when the API is unreachable, because a firewalled
 * teammate's machine is not a test failure.
 */
import { test, expect, type Page } from '@playwright/test'

const SHOTS = 'e2e/screens'

/**
 * Does the app's proxied API answer? Decides whether the authed shots run.
 *
 * Retried: the demo backend sits on a teammate's machine across Tailscale, and
 * the link renegotiates between a DERP relay and a direct path. A single probe
 * landing in that window would skip the whole authed suite for no good reason.
 */
async function apiUp(page: Page, attempts = 3): Promise<boolean> {
  for (let i = 0; i < attempts; i++) {
    try {
      const res = await page.request.get('/api/v1/health', { timeout: 15_000 })
      if (res.ok()) return true
    } catch {
      /* fall through to the next attempt */
    }
    if (i < attempts - 1) await page.waitForTimeout(2_000)
  }
  return false
}

/**
 * Navigate without waiting on the `load` event.
 *
 * index.html pulls Noto Sans from fonts.googleapis.com with a render-blocking
 * <link>. Where that host is unreachable — a locked-down network, an offline
 * demo floor — `load` never fires and every goto burns the full timeout. The
 * DOM is what we are capturing, so wait for that instead.
 */
async function visit(page: Page, path: string) {
  await page.goto(path, { waitUntil: 'domcontentloaded' })
  // Web fonts are decorative to the assertions but change every glyph in a
  // screenshot, so wait for them rather than capturing a fallback stack.
  await page.evaluate(() => document.fonts.ready).catch(() => {})
}

/**
 * Capture once the screen has actually settled.
 *
 * `networkidle` is no use here: dashboards poll every 30s so they are never
 * idle. Instead wait for every <Loading> (role="status") to clear. The budget is
 * generous because the demo backend is reached over a relayed Tailscale link,
 * where a round trip can take several seconds.
 */
async function settle(page: Page) {
  const spinners = page.getByRole('status')
  await expect
    .poll(async () => await spinners.count(), { timeout: 25_000, intervals: [250] })
    .toBe(0)
  // Let charts and map tiles paint after their data arrives.
  await page.waitForTimeout(600)
}

async function shoot(page: Page, name: string, opts: { tiles?: boolean } = {}) {
  await settle(page)
  if (opts.tiles) {
    // Leaflet fires tile requests after its container is laid out, which is
    // after the data spinners clear — without this the basemap is blank.
    await page
      .waitForResponse((r) => /tile\./.test(r.url()) && r.status() === 200, { timeout: 15_000 })
      .catch(() => {})
    await page.waitForTimeout(2_500)
  }
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true })
}

test.describe('screens', () => {
  test('login — and the accessibility controls', async ({ page }) => {
    await visit(page, '/login')
    await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible()
    await shoot(page, '01-login')

    // A+ scales the whole UI via the root font-size (src/lib/prefs.ts).
    await page.getByRole('button', { name: 'A+', exact: true }).click()
    await expect(page.locator('html')).toHaveAttribute('data-textsize', 'lg')
    await shoot(page, '02-login-large-text')

    await page.getByRole('button', { name: /contrast/i }).click()
    await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high')
    await shoot(page, '03-login-high-contrast')

    // Reset so the persisted prefs don't leak into the next capture.
    await page.getByRole('button', { name: 'A', exact: true }).click()
    await page.getByRole('button', { name: /contrast/i }).click()
  })

  test('authed screens', async ({ page }) => {
    await visit(page, '/login')
    test.skip(!(await apiUp(page)), 'API unreachable — skipping screens behind auth')

    await page.getByRole('button', { name: /Ministry \(DoLR\)/ }).click()
    await page.waitForURL(/\/national/, { timeout: 15_000 })
    await shoot(page, '10-national-dashboard')

    for (const [name, path] of [
      ['11-projects', '/projects'],
      ['12-alerts', '/alerts'],
      ['13-reports', '/reports'],
      ['14-admin-rulesets', '/admin/rulesets'],
    ] as const) {
      await visit(page, path)
      await shoot(page, name)
    }
  })

  test('case page — the product', async ({ page }) => {
    await visit(page, '/login')
    test.skip(!(await apiUp(page)), 'API unreachable — skipping screens behind auth')

    await page.getByRole('button', { name: /LAO \/ CALA/ }).click()
    await page.waitForURL(/\/(districts|projects|national)/, { timeout: 20_000 })

    // Reach a case from the risk queue rather than hard-coding a seeded id.
    await visit(page, '/alerts')
    await settle(page) // links only exist once the alert queue has loaded
    const firstCase = page.locator('a[href^="/cases/"]').first()
    test.skip((await firstCase.count()) === 0, 'no cases in the alert queue')
    await firstCase.click()
    await page.waitForURL(/\/cases\//, { timeout: 20_000 })
    await shoot(page, '30-case-page', { tiles: true })
  })

  test('public status — no sign-in', async ({ page }) => {
    await visit(page, '/public')
    await shoot(page, '20-public-status')
  })
})
