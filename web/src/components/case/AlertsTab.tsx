/**
 * AlertsTab — the alerts raised on this case.
 * `GET /alerts` is scope-wide (Docs/APIs.md §3.9); the case page filters it
 * client-side, since there is no per-case alert endpoint in the contract.
 * Sorted by days-to-due ascending, per Docs/Frontend.md §5.
 */
import { formatDate } from '../../lib/api'
import { CaseAlert, daysBetween, formatTs, titleize, today } from './caseApi'

const LEVEL: Record<string, { label: string; cls: string }> = {
  amber: { label: 'Amber — 75% elapsed', cls: 'bg-amber/10 text-[#8A5300] border border-amber' },
  red: { label: 'Red — 90% elapsed', cls: 'bg-red/10 text-[#8C1D18] border border-red' },
  black: { label: 'Black — breached', cls: 'bg-breached text-white border border-breached' },
  breached: { label: 'Breached', cls: 'bg-breached text-white border border-breached' },
  lapsed: { label: 'Lapsed', cls: 'bg-breached text-white border border-breached' },
  integrity: { label: 'Integrity', cls: 'bg-red/10 text-[#8C1D18] border border-red' },
}

function levelOf(a: CaseAlert) {
  return LEVEL[String(a.level ?? '').toLowerCase()] ?? {
    label: titleize(a.level) || 'Alert',
    cls: 'bg-surface text-muted border border-border',
  }
}

export default function AlertsTab({
  alerts,
  loading,
  error,
}: {
  alerts: CaseAlert[]
  loading?: boolean
  error?: unknown
}) {
  if (loading) return <p className="text-xs text-muted">Loading alerts…</p>
  if (error)
    return (
      <p role="alert" className="rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
        Could not load alerts: {error instanceof Error ? error.message : 'request failed'}
      </p>
    )

  const rows = [...alerts].sort((a, b) => {
    const da = daysBetween(today(), a.due_date) ?? Number.MAX_SAFE_INTEGER
    const db = daysBetween(today(), b.due_date) ?? Number.MAX_SAFE_INTEGER
    return da - db
  })

  if (rows.length === 0)
    return <p className="text-xs text-muted">No alerts are open on this case.</p>

  return (
    <div className="overflow-x-auto">
      <table className="gov">
        <caption className="sr-only">Alerts on this case, soonest due first</caption>
        <thead>
          <tr>
            <th scope="col">Level</th>
            <th scope="col">Clock</th>
            <th scope="col">Due</th>
            <th scope="col">Days to due</th>
            <th scope="col">Escalated to</th>
            <th scope="col">Raised</th>
            <th scope="col">Acknowledged</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => {
            const lv = levelOf(a)
            const left = daysBetween(today(), a.due_date)
            return (
              <tr key={a.id}>
                <td>
                  <span className={`badge ${lv.cls}`}>{lv.label}</span>
                </td>
                <td className="font-semibold">{titleize(a.clock_id)}</td>
                <td>{formatDate(a.due_date)}</td>
                <td className="tabular-nums">
                  {left == null ? '—' : left >= 0 ? `${left} days` : `${-left} days overdue`}
                </td>
                <td>{titleize(a.escalated_to_role)}</td>
                <td>{formatTs(a.raised_at)}</td>
                <td>
                  {a.acknowledged_at ? (
                    <span className="text-ok">{formatTs(a.acknowledged_at)}</span>
                  ) : (
                    <span className="text-muted">Not acknowledged</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-muted">
        Escalation ladder per Docs/rules.md C2: amber → LAO, red → Collector, breach → State,
        lapse → Ministry. Acknowledge from the Alert centre.
      </p>
    </div>
  )
}
