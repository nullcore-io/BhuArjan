/**
 * KPI tile — Docs/Frontend.md §4, Docs/rules.md C7.
 *
 * Two non-negotiables live here: every tile states the event sequence it was
 * computed at ("as of seq N"), and every tile whose figure can be exploded
 * back to its events carries an Explain link. A number without a provenance
 * line is a number nobody can defend in an audit.
 */
import type { ReactNode } from 'react'

export interface KpiTileProps {
  /** English label — exact PS wording. */
  label: string
  /** Hindi label, shown under the English one (Docs/Frontend.md §9). */
  labelHi?: string
  /** Pre-formatted value, or null/undefined when the API did not send it. */
  value: ReactNode
  /** Secondary line: denominator, share, statutory basis. */
  sub?: ReactNode
  /** `as_of_seq` from the dashboard response. */
  asOfSeq?: number | null
  /** Present only for KPIs the server can explain. */
  onExplain?: () => void
  /** Where the figure came from (`kpis.sources[key]`), shown as a tooltip. */
  source?: string | null
}

export default function KpiTile({
  label,
  labelHi,
  value,
  sub,
  asOfSeq,
  onExplain,
  source,
}: KpiTileProps) {
  const missing = value === null || value === undefined || value === '—'
  return (
    <div className="card flex flex-col gap-1 p-3">
      <div className="leading-tight">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</div>
        {labelHi ? <div className="text-xs text-muted">{labelHi}</div> : null}
      </div>
      <div
        className={`text-2xl font-bold tabular-nums ${missing ? 'text-muted' : 'text-ink'}`}
        title={source ? `Source: ${source}` : undefined}
      >
        {missing ? '—' : value}
      </div>
      {sub ? <div className="text-xs text-muted">{sub}</div> : null}
      <div className="mt-auto flex items-center justify-between gap-2 pt-1 text-[11px] text-muted">
        <span title="Event sequence number this figure was computed at (Docs/rules.md C7)">
          {asOfSeq === null || asOfSeq === undefined ? 'as of —' : `as of seq ${asOfSeq}`}
        </span>
        {onExplain ? (
          <button
            type="button"
            onClick={onExplain}
            className="rounded text-accent underline decoration-dotted underline-offset-2 hover:text-ink focus:outline-none focus:ring-2 focus:ring-accent"
          >
            Explain
          </button>
        ) : (
          <span className="italic opacity-60" title="This KPI is derived, not event-explainable">
            derived
          </span>
        )}
      </div>
    </div>
  )
}
