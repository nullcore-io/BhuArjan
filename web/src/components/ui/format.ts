/**
 * Formatting and shape-tolerance helpers shared by the dashboard, project,
 * alert, login and public screens.
 *
 * Two rules run through this file:
 *  - a figure that is genuinely absent renders as "—", never as 0. A government
 *    dashboard that silently shows zero for a missing projection is lying;
 *  - list endpoints are read through `listOf`, so a router that returns
 *    `{items}`, `{projects}` or a bare array all render rather than blanking
 *    the screen (Docs/APIs.md §1 pagination envelope).
 */

/** Numeric coercion that never yields NaN. */
export function num(v: unknown, fallback = 0): number {
  const n = Number(v ?? fallback)
  return Number.isFinite(n) ? n : fallback
}

/** True when the value is a real number the API actually sent. */
export function present(v: unknown): boolean {
  if (v === null || v === undefined || v === '') return false
  return Number.isFinite(Number(v))
}

const DASH = '—'

/** Hectares to 2 dp with Indian grouping (Docs/APIs.md §1: areas as hectares). */
export function formatHa(v: unknown): string {
  if (!present(v)) return DASH
  return `${num(v).toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} ha`
}

/** Whole counts with Indian grouping. */
export function formatCount(v: unknown): string {
  if (!present(v)) return DASH
  return Math.round(num(v)).toLocaleString('en-IN')
}

/** Percentages to 1 dp. */
export function formatPct(v: unknown): string {
  if (!present(v)) return DASH
  return `${num(v).toFixed(1)}%`
}

/** `PRELIM_NOTIFICATION_S11` → `PRELIM NOTIFICATION S11`. */
export function titleize(s?: string | null): string {
  if (!s) return DASH
  return String(s).replace(/_/g, ' ')
}

/** `2026-11-30` → `30-11-2026`; anything unparseable comes back untouched. */
export function formatDay(d?: string | null): string {
  if (!d) return DASH
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(d))
  if (!m) return String(d)
  return `${m[3]}-${m[2]}-${m[1]}`
}

/** `2026-11` → `Nov 2026`; used for the citizen page's due month. */
export function formatMonth(m?: string | null): string {
  if (!m) return DASH
  const parts = String(m).split('-')
  const y = Number(parts[0])
  const mm = Number(parts[1])
  if (!Number.isFinite(y) || !Number.isFinite(mm) || mm < 1 || mm > 12) return String(m)
  const names = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ]
  return `${names[mm - 1]} ${y}`
}

/**
 * Pull the array out of a paginated envelope. Accepts a bare array,
 * `{items}`, `{results}`, `{data}` or any caller-named key.
 */
export function listOf<T>(raw: unknown, ...keys: string[]): T[] {
  if (Array.isArray(raw)) return raw as T[]
  const o = (raw ?? {}) as Record<string, unknown>
  for (const k of ['items', ...keys, 'results', 'data']) {
    const v = o[k]
    if (Array.isArray(v)) return v as T[]
  }
  return []
}

/** First non-empty value among several candidate field names. */
export function firstOf(row: Record<string, unknown> | null | undefined, ...keys: string[]): unknown {
  if (!row) return undefined
  for (const k of keys) {
    const v = row[k]
    if (v !== null && v !== undefined && v !== '') return v
  }
  return undefined
}

/** Same, narrowed to a printable string. */
export function textOf(
  row: Record<string, unknown> | null | undefined,
  ...keys: string[]
): string | null {
  const v = firstOf(row, ...keys)
  if (v === undefined) return null
  if (typeof v === 'string') return v
  if (typeof v === 'number') return String(v)
  if (v && typeof v === 'object') {
    const name = (v as Record<string, unknown>).name
    if (typeof name === 'string') return name
  }
  return null
}

/** RFC 7807 detail off an ApiError, or a plain message. */
export function errorText(err: unknown): string {
  const problem = (err as { problem?: Record<string, unknown> } | null)?.problem
  const detail = problem?.detail ?? problem?.title
  if (typeof detail === 'string') return detail
  return err instanceof Error ? err.message : 'Request failed'
}

export function httpStatus(err: unknown): number | null {
  const s = (err as { status?: unknown } | null)?.status
  return typeof s === 'number' ? s : null
}

/**
 * Choose one money unit for a whole axis. Per-point switching (which
 * `formatINR` does, correctly, for a single figure) makes a chart unreadable.
 */
export interface MoneyScale {
  /** Divide paise by this to get the plotted number. */
  divisor: number
  /** Axis unit label. */
  unit: string
}

export function moneyScale(maxPaise: number): MoneyScale {
  const rupees = Math.abs(maxPaise) / 100
  if (rupees >= 1e7) return { divisor: 1e9, unit: '₹ crore' }
  if (rupees >= 1e5) return { divisor: 1e7, unit: '₹ lakh' }
  return { divisor: 100, unit: '₹' }
}

export const EM_DASH = DASH
