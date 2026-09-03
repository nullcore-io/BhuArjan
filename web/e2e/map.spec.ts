/**
 * Land view regressions.
 *
 * Both cases here were reported from the running app:
 *  - every parcel drew FOUR locator dots, because a circle layer places one
 *    circle per vertex and the plots are rectangles;
 *  - clicking a dot selected nothing, because the click landed on a polygon
 *    corner rather than a feature carrying the parcel.
 *
 * They share one cause, so they share one fix (a derived centroid source) and
 * are guarded together.
 */
import { expect, test, type Page } from '@playwright/test'

async function openMap(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  const health = await page.request.get('/api/v1/health', { timeout: 15_000 }).catch(() => null)
  test.skip(!health?.ok(), 'API unreachable')

  await page.getByRole('button', { name: /Ministry \(DoLR\)/ }).click()
  await page.waitForURL(/\/national/, { timeout: 20_000 })
  await page.goto('/map', { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => !!(window as any).__bhuarjanMap, null, { timeout: 30_000 })
  // Wait for the GeoJSON worker to finish tiling the source.
  await page.waitForFunction(
    () => (window as any).__bhuarjanMap.isSourceLoaded('parcel-centres'),
    null,
    { timeout: 30_000 },
  )
  await page.waitForTimeout(1_500)
}

/** Halt the orbit so a projected coordinate is still valid when the click lands. */
async function stopSpin(page: Page) {
  const box = page.getByRole('checkbox', { name: /Rotate globe/i })
  if (await box.isChecked()) await box.uncheck()
  await page.waitForTimeout(500)
}

test('one locator dot per parcel, not one per polygon vertex', async ({ page }) => {
  await openMap(page)
  await stopSpin(page)

  const { rows, dots } = await page.evaluate(() => {
    const m = (window as any).__bhuarjanMap
    const src = m.querySourceFeatures('parcel-centres')
    // Dedupe: a feature straddling a tile boundary is returned once per tile.
    const ids = new Set(src.map((f: any) => f.properties?.parcel_id))
    return {
      rows: document.querySelectorAll('table.gov tbody tr').length,
      dots: ids.size,
    }
  })

  expect(rows).toBeGreaterThan(0)
  expect(dots, 'one point feature per parcel in the register').toBe(rows)
})

test('clicking a parcel on the globe selects that parcel', async ({ page }) => {
  await openMap(page)
  await stopSpin(page)

  // Project a parcel's dot to screen coordinates, then ask MapLibre which
  // feature is actually topmost at that pixel. Neighbouring plots overlap at
  // low zoom, so "the first feature in tile order" is not the one a click hits
  // — the contract is that the panel shows whatever is under the cursor.
  const target = await page.evaluate(() => {
    const m = (window as any).__bhuarjanMap
    const seed = m.querySourceFeatures('parcel-centres')[0]
    if (!seed) return null
    const pt = m.project(seed.geometry.coordinates)
    const hit = m.queryRenderedFeatures(pt, { layers: ['parcel-point', 'parcel-fill'] })[0]
    if (!hit) return null
    const box = m.getCanvas().getBoundingClientRect()
    return { x: box.left + pt.x, y: box.top + pt.y, survey: hit.properties?.survey_no }
  })
  expect(target, 'expected at least one parcel centre').not.toBeNull()

  await page.mouse.click(target!.x, target!.y)
  await page.waitForTimeout(500)

  // The details panel must name the parcel that was clicked.
  const panel = page.locator('section', { hasText: 'Selected parcel' }).first()
  await expect(panel).toBeVisible()
  await expect(panel).toContainText(String(target!.survey))
})
