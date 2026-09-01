/**
 * Badges and chips shared across dashboards, project pages and the alert centre.
 *
 * Docs/Frontend.md §9: colour is never the only signal. Every chip carries a
 * word — "Breached", "Critical", "Lapsed" — so the meaning survives greyscale
 * printing, colour-blindness and a projector with the contrast turned down.
 */
import type { ReactNode } from 'react'
import { titleize } from './format'

export type Tone = 'neutral' | 'accent' | 'ok' | 'amber' | 'red' | 'black' | 'saffron'

const TONE_CLS: Record<Tone, string> = {
  neutral: 'bg-surface text-muted border border-border',
  accent: 'bg-accent/10 text-accent border border-accent',
  ok: 'bg-ok/10 text-[#1B5E20] border border-ok',
  amber: 'bg-amber/10 text-[#8A5300] border border-amber',
  red: 'bg-red/10 text-[#8C1D18] border border-red',
  black: 'bg-breached text-white border border-breached',
  saffron: 'bg-accent2/10 text-[#7A4E09] border border-accent2',
}

export function StatBadge({
  tone = 'neutral',
  title,
  children,
}: {
  tone?: Tone
  title?: string
  children: ReactNode
}) {
  return (
    <span className={`badge ${TONE_CLS[tone]}`} title={title}>
      {children}
    </span>
  )
}

/* ------------------------------------------------------------------ statute */

const STATUTE_LABEL: Record<string, string> = {
  RFCTLARR_2013: 'RFCTLARR 2013',
  NH_ACT_1956: 'NH Act 1956',
  RAILWAYS_1989: 'Railways Act 1989',
  METRO_1978: 'Metro Railways 1978',
  CBA_1957: 'Coal Bearing Areas 1957',
  PMP_1962: 'Petroleum & Minerals Pipelines 1962',
  ELECTRICITY_2003: 'Electricity Act 2003',
}

export function statuteLabel(track?: string | null): string {
  if (!track) return '—'
  return STATUTE_LABEL[track] ?? titleize(track)
}

export function StatuteBadge({ track }: { track?: string | null }) {
  if (!track) return <span className="text-muted">—</span>
  return (
    <StatBadge tone="saffron" title={`Statute track: ${track}`}>
      {statuteLabel(track)}
    </StatBadge>
  )
}

/* -------------------------------------------------------------------- stage */

const STAGE_TONE: Record<string, Tone> = {
  PROPOSED: 'neutral',
  SIA: 'neutral',
  APPRAISED: 'neutral',
  NOTIFIED: 'accent',
  DECLARED: 'accent',
  AWARDED: 'ok',
  POSSESSED: 'ok',
  CLOSED: 'neutral',
  LAPSED: 'black',
  RESCINDED: 'black',
}

/** Statutory section that put the case into this stage — kept visible per §2. */
const STAGE_SECTION: Record<string, string> = {
  NOTIFIED: 's.11 / 3A',
  DECLARED: 's.19 / 3D',
  AWARDED: 's.23 / 3G',
  POSSESSED: 's.38 / 3E',
  LAPSED: 's.25 / s.19(7)',
}

export function StageBadge({ stage }: { stage?: string | null }) {
  if (!stage) return <span className="text-muted">—</span>
  const key = String(stage).toUpperCase()
  const section = STAGE_SECTION[key]
  return (
    <StatBadge tone={STAGE_TONE[key] ?? 'neutral'} title={section ? `Stage ${key} (${section})` : `Stage ${key}`}>
      {titleize(key)}
    </StatBadge>
  )
}

/* ------------------------------------------------------------ alert / clock */

export type AlertLevel = 'amber' | 'red' | 'breached' | 'lapsed' | 'closed' | 'suspended' | 'running'

const LEVEL_VIEW: Record<AlertLevel, { label: string; tone: Tone }> = {
  running: { label: 'On time', tone: 'ok' },
  amber: { label: 'Amber — 75% elapsed', tone: 'amber' },
  red: { label: 'Red — 90% elapsed', tone: 'red' },
  breached: { label: 'Breached', tone: 'black' },
  lapsed: { label: 'Lapsed', tone: 'black' },
  closed: { label: 'Closed', tone: 'neutral' },
  suspended: { label: 'Suspended (stay)', tone: 'saffron' },
}

export function levelView(level?: string | null): { label: string; tone: Tone } {
  const key = String(level ?? '').toLowerCase() as AlertLevel
  return LEVEL_VIEW[key] ?? { label: titleize(level) || 'Unknown', tone: 'neutral' }
}

export function LevelChip({ level, title }: { level?: string | null; title?: string }) {
  const view = levelView(level)
  return (
    <StatBadge tone={view.tone} title={title}>
      {view.label}
    </StatBadge>
  )
}

/**
 * Days-to-due as a signed chip. Overdue days are stated as such rather than
 * shown as a negative number an officer has to interpret.
 */
export function DaysLeft({ days }: { days?: number | null }) {
  if (days === null || days === undefined || !Number.isFinite(Number(days))) {
    return <span className="text-muted">—</span>
  }
  const d = Math.round(Number(days))
  if (d < 0) {
    return (
      <span className="font-semibold text-red" title="Statutory due date has passed">
        {Math.abs(d)} d overdue
      </span>
    )
  }
  const cls = d <= 30 ? 'font-semibold text-amber' : ''
  return <span className={cls}>{d} d left</span>
}

/** Risk score 0–100; text always accompanies the colour. */
export function RiskScore({ score }: { score?: number | string | null }) {
  if (score === null || score === undefined || !Number.isFinite(Number(score))) {
    return <span className="text-muted">—</span>
  }
  const n = Number(score)
  const tone: Tone = n >= 75 ? 'red' : n >= 50 ? 'amber' : 'ok'
  const word = n >= 75 ? 'High' : n >= 50 ? 'Medium' : 'Low'
  return (
    <StatBadge tone={tone} title={`Risk score ${n}`}>
      {word} {Math.round(n)}
    </StatBadge>
  )
}
