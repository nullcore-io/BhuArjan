/**
 * Presentation preferences that GIGW 3.0 requires every government page to
 * expose: text size (A- / A / A+) and a high-contrast mode.
 *
 * They are applied as data attributes on <html> and read by src/styles/index.css,
 * so no component has to thread them through props. Persisted per browser.
 */

export type TextSize = 'sm' | 'md' | 'lg'
export type Contrast = 'normal' | 'high'

const TEXT_KEY = 'bhuarjan.textsize'
const CONTRAST_KEY = 'bhuarjan.contrast'

function read<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const v = localStorage.getItem(key) as T | null
    return v && allowed.includes(v) ? v : fallback
  } catch {
    return fallback // private mode / storage disabled
  }
}

export function getTextSize(): TextSize {
  return read(TEXT_KEY, ['sm', 'md', 'lg'] as const, 'md')
}

export function getContrast(): Contrast {
  return read(CONTRAST_KEY, ['normal', 'high'] as const, 'normal')
}

export function setTextSize(v: TextSize) {
  try {
    localStorage.setItem(TEXT_KEY, v)
  } catch {
    /* non-fatal: the attribute below still applies for this page view */
  }
  document.documentElement.dataset.textsize = v
}

export function setContrast(v: Contrast) {
  try {
    localStorage.setItem(CONTRAST_KEY, v)
  } catch {
    /* non-fatal */
  }
  document.documentElement.dataset.contrast = v
}

/** Call once at boot, before first paint, so the page never flashes unstyled. */
export function applyStoredPrefs() {
  document.documentElement.dataset.textsize = getTextSize()
  document.documentElement.dataset.contrast = getContrast()
}
