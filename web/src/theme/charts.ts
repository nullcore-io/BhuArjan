/**
 * Chart theme — Docs/design.md §4.
 *
 * Colours come from palette.mjs, the same file Tailwind reads, so a mark can
 * never drift from its token.
 *
 * Two rules from the data-viz guidance shape what follows:
 *
 *  - Status colours are RESERVED. `ok` green means "clock running", so it must
 *    not also mean "the Paid series". The categorical pair below is blue+gold,
 *    which measured ΔE 27.2 under tritanopia against blue+green's 8.4.
 *  - The statutory status palette CANNOT be recoloured — red means breached and
 *    green means running as a matter of design.md §1 and of law. Measured, it
 *    fails CVD separation badly (lapsed↔running ΔE 2.8 under deuteranopia), so
 *    every status carries a texture and a word as well as a hue. Colour is
 *    never the only signal.
 */
import { palette } from './palette.mjs'

/** Categorical series identity. Fixed order, never cycled. */
export const SERIES = {
  assessed: palette.accent, //  #1F4E9C
  paid: palette.accent2, //     #B9770E
} as const

/** Shared axis / grid / tooltip styling. Gridlines stay recessive (§4). */
export const AXIS = {
  grid: palette.border,
  tick: { fontSize: 12, fill: palette.muted },
  tooltip: {
    fontSize: 12,
    borderRadius: 4,
    border: `1px solid ${palette.border}`,
    background: palette.bg,
    color: palette.ink,
  },
} as const

export interface StatusStyle {
  /** Hue — semantically fixed, see the note above. */
  colour: string
  /** The word that must accompany the hue everywhere it appears. */
  label: string
  /** id of the <pattern> in <ChartPatterns/>; null = solid fill. */
  pattern: string | null
}

/**
 * Clock statuses. Order is the statutory life-cycle, not an arbitrary sort.
 * `pattern` is the secondary encoding that makes the palette legal for
 * colour-blind readers and for greyscale printing.
 */
export const CLOCK_STATUS: Record<string, StatusStyle> = {
  running: { colour: palette.ok, label: 'Running', pattern: null },
  extended: { colour: palette.accent, label: 'Extended', pattern: 'diag-right' },
  suspended: { colour: palette.accent2, label: 'Suspended (stay)', pattern: 'diag-left' },
  closed: { colour: palette.muted, label: 'Closed', pattern: 'dots' },
  breached: { colour: palette.breached, label: 'Breached', pattern: 'grid' },
  lapsed: { colour: palette.red, label: 'Lapsed', pattern: 'horizontal' },
}

export const CLOCK_STATUS_ORDER: string[] = [
  'running',
  'extended',
  'suspended',
  'closed',
  'breached',
  'lapsed',
]

/** Fill for a status bar: the pattern where one exists, else the flat hue. */
export function statusFill(key: string): string {
  const s = CLOCK_STATUS[key]
  if (!s) return palette.muted
  return s.pattern ? `url(#pat-${s.pattern})` : s.colour
}

export function statusStyle(key: string): StatusStyle {
  return CLOCK_STATUS[key] ?? { colour: palette.muted, label: key, pattern: null }
}

export { palette }
