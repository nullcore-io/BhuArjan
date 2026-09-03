/**
 * Docs/design.md §4 as executable checks.
 *
 * These exist because §4's requirements are the kind that decay silently: a
 * chart added without a table, a legend that stops being a <button>, a series
 * colour nudged below contrast. Each rule below failed at least once during
 * implementation, so each is worth guarding.
 */
import { expect, test, type Page } from '@playwright/test'
import { palette } from '../src/theme/palette.mjs'

/* ------------------------------------------------------------ colour maths */

function luminance(hex: string): number {
  const h = hex.replace('#', '')
  const ch = [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
}

function contrast(a: string, b: string): number {
  const [x, y] = [luminance(a), luminance(b)]
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

test.describe('design.md §4 — colour', () => {
  // "data lines/bars against background >= 3:1"
  const MARKS = ['accent', 'accent2', 'ok', 'red', 'amber', 'breached', 'muted'] as const
  for (const key of MARKS) {
    test(`mark ${key} is >= 3:1 against the chart surface`, () => {
      expect(contrast(palette[key], palette.surface)).toBeGreaterThanOrEqual(3)
    })
  }

  // "any text label on a chart >= 4.5:1"
  for (const key of ['muted', 'ink', 'hint'] as const) {
    test(`chart text ${key} is >= 4.5:1 against the chart surface`, () => {
      expect(contrast(palette[key], palette.surface)).toBeGreaterThanOrEqual(4.5)
    })
  }

  // The two series must not be the same hue family, and neither may be a
  // reserved status colour (ok/red/amber mean clock states).
  test('series colours are not reserved status colours', () => {
    const series = [palette.accent, palette.accent2]
    for (const s of series) {
      expect([palette.ok, palette.red, palette.amber, palette.breached]).not.toContain(s)
    }
    expect(series[0]).not.toBe(series[1])
  })
})

/* ------------------------------------------------------------------ in-app */

async function signIn(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  const health = await page.request.get('/api/v1/health', { timeout: 15_000 }).catch(() => null)
  test.skip(!health?.ok(), 'API unreachable')
  await page.getByRole('button', { name: /Ministry \(DoLR\)/ }).click()
  await page.waitForURL(/\/national/, { timeout: 20_000 })
  await expect
    .poll(async () => await page.getByRole('status').count(), { timeout: 25_000 })
    .toBe(0)
}

test.describe('design.md §4 — in the page', () => {
  test('every chart ships a text-equivalent table with rows', async ({ page }) => {
    await signIn(page)
    const disclosures = page.locator('details', { hasText: 'text equivalent of the chart' })
    const n = await disclosures.count()
    expect(n, 'expected one text equivalent per chart').toBeGreaterThanOrEqual(3)

    for (let i = 0; i < n; i++) {
      const d = disclosures.nth(i)
      await d.locator('summary').click()
      const table = d.locator('table.gov')
      await expect(table).toBeVisible()
      // A table alternative with no rows is not an alternative.
      expect(await table.locator('tbody tr').count()).toBeGreaterThan(0)
    }
  })

  test('legend items are real buttons and toggle their series', async ({ page }) => {
    await signIn(page)
    const legend = page.getByRole('group', { name: 'Compensation series' })
    const paid = legend.getByRole('button', { name: /Paid/ })

    // Keyboard-operable and state-announcing, not a click-only <li>.
    await expect(paid).toHaveAttribute('aria-pressed', 'true')
    await paid.click()
    await expect(paid).toHaveAttribute('aria-pressed', 'false')
    await paid.click()
    await expect(paid).toHaveAttribute('aria-pressed', 'true')
  })

  test('clock statuses carry a word, not colour alone', async ({ page }) => {
    await signIn(page)
    const legend = page.getByRole('group', { name: 'Clock states' })
    await expect(legend).toBeVisible()
    // Every legend entry must render text; a bare swatch would be colour-only.
    for (const btn of await legend.getByRole('button').all()) {
      expect((await btn.innerText()).trim().length).toBeGreaterThan(0)
    }
  })
})
