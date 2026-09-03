/**
 * Playwright config — Docs/Frontend.md stack ("Vitest + Playwright").
 *
 * Points at the Vite dev server on 3016. `reuseExistingServer` is on outside CI
 * so a dev server you already have running is used as-is rather than fighting
 * for the port; in CI Playwright starts its own.
 *
 * The API origin is whatever web/.env.local's VITE_API_PROXY points at — these
 * tests never talk to the backend directly, only through the app.
 */
import { defineConfig, devices } from '@playwright/test'

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3016'

export default defineConfig({
  testDir: './e2e',
  outputDir: './e2e/.artifacts',
  // Generous: the demo API is reached over a relayed Tailscale link.
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list']],

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // Officers run this on department desktops, not phones.
    viewport: { width: 1440, height: 900 },
    locale: 'en-IN',
    timezoneId: 'Asia/Kolkata',
  },

  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],

  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
