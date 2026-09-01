/**
 * Alert centre — Docs/Frontend.md §5, Docs/APIs.md §3.9, Docs/rules.md C2.
 *
 * The list is the officer's work queue, so it is sorted by days-to-due
 * ascending: the clock nearest its statutory deadline is the one that has to be
 * worked first. Every row states the section the clock runs under and the
 * consequence of breaching it, because an alert without its consequence is just
 * a colour.
 *
 * Acknowledging is an operational act — it records who saw the alert. It never
 * touches the ledger and it never stops the clock.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Empty, ErrorNote, Loading } from '../../components/ui/Feedback'
import { DaysLeft, LevelChip, levelView } from '../../components/ui/StatBadge'
import { errorText, formatCount, formatDay, listOf, titleize } from '../../components/ui/format'
import { api } from '../../lib/api'
import type { Me } from '../../lib/auth'

interface AlertRow {
  id: string
  case_id?: string | null
  case_no?: string | null
  project?: string | null
  project_name?: string | null
  state_code?: string | null
  statute_track?: string | null
  clock_id?: string | null
  level?: string | null
  basis?: string | null
  consequence?: string | null
  clock_status?: string | null
  start_date?: string | null
  due_date?: string | null
  days_left?: number | null
  raised_at?: string | null
  age_days?: number | null
  escalated_to_role?: string | null
  escalated_to?: string | null
  acknowledged_by?: string | null
  acknowledged_at?: string | null
  acknowledged?: boolean | null
}

interface AlertsResponse {
  items?: AlertRow[]
  alerts?: AlertRow[]
  total?: number | null
  next_cursor?: string | null
  as_of_date?: string | null
}

/** Ladder from Docs/rules.md C2 — always offered in full so a zero reads as zero. */
const LEVELS = ['amber', 'red', 'breached', 'lapsed'] as const

/** Escalation ladder; shown when the row does not name a role itself. */
const ESCALATION: Record<string, string> = {
  amber: 'LAO',
  red: 'COLLECTOR',
  breached: 'STATE_REVENUE',
  lapsed: 'MINISTRY',
}

const ACK_DENIED_ROLES = ['AUDITOR', 'RB']

/** Nulls sort last: a clock with no due date is not urgent, it is unknown. */
function byDaysToDue(a: AlertRow, b: AlertRow): number {
  const da = a.days_left
  const db = b.days_left
  const ma = da === null || da === undefined || !Number.isFinite(Number(da))
  const mb = db === null || db === undefined || !Number.isFinite(Number(db))
  if (ma && mb) return String(b.raised_at ?? '').localeCompare(String(a.raised_at ?? ''))
  if (ma) return 1
  if (mb) return -1
  return Number(da) - Number(db)
}

export default function AlertCentre() {
  const queryClient = useQueryClient()
  const [level, setLevel] = useState('')
  const [unackOnly, setUnackOnly] = useState(false)

  const me = useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/auth/me'), retry: false })
  const canAck = !(me.data?.roles ?? []).some((r) => ACK_DENIED_ROLES.includes(r))

  const qs = new URLSearchParams({ limit: '200' })
  if (level) qs.set('level', level)
  if (unackOnly) qs.set('acknowledged', 'false')

  const alerts = useQuery({
    queryKey: ['alerts', level, unackOnly],
    queryFn: () => api<AlertsResponse>(`/alerts?${qs}`),
  })

  const summary = useQuery({
    queryKey: ['alertSummary'],
    queryFn: () => api<{ counts?: Record<string, number>; unacknowledged?: number }>(
      '/alerts/summary',
    ),
    retry: false,
  })

  const ack = useMutation({
    mutationFn: (id: string) => api(`/alerts/${id}/ack`, { method: 'POST' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] })
      void queryClient.invalidateQueries({ queryKey: ['alertSummary'] })
    },
  })

  const rows = useMemo(
    () => listOf<AlertRow>(alerts.data, 'alerts').slice().sort(byDaysToDue),
    [alerts.data],
  )

  const counts = summary.data?.counts ?? {}

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-ink">
            Alert centre <span className="font-normal text-muted">/ अलर्ट केंद्र</span>
          </h1>
          <p className="text-xs text-muted">
            Sorted by days to the statutory due date. Amber at 75% elapsed, red at 90%,
            black on breach — thresholds come from the rule-set, not from code
            (Docs/rules.md C2).
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-0.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">
              Level
            </span>
            <select
              className="rounded border border-border bg-bg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              value={level}
              onChange={(e) => setLevel(e.target.value)}
            >
              <option value="">All levels</option>
              {LEVELS.map((l) => (
                <option key={l} value={l}>
                  {levelView(l).label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1.5 pb-1.5 text-sm">
            <input
              type="checkbox"
              checked={unackOnly}
              onChange={(e) => setUnackOnly(e.target.checked)}
            />
            Unacknowledged only
          </label>
        </div>
      </header>

      {/* --- ladder summary --- */}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {LEVELS.map((l) => (
          <button
            key={l}
            type="button"
            onClick={() => setLevel(level === l ? '' : l)}
            className={`card flex items-center justify-between p-3 text-left hover:border-accent focus:outline-none focus:ring-2 focus:ring-accent ${
              level === l ? 'border-accent' : ''
            }`}
          >
            <span className="flex flex-col gap-1">
              <LevelChip level={l} />
              <span className="text-[11px] text-muted">escalates to {ESCALATION[l]}</span>
            </span>
            <span className="text-2xl font-bold tabular-nums text-ink">
              {formatCount(counts[l] ?? 0)}
            </span>
          </button>
        ))}
      </div>

      {ack.isError ? <ErrorNote error={ack.error} what="Acknowledgement" /> : null}

      {alerts.isLoading ? <Loading label="Loading alerts…" /> : null}
      {alerts.isError ? <ErrorNote error={alerts.error} what="Alert centre" /> : null}

      {alerts.isSuccess ? (
        rows.length === 0 ? (
          <Empty>
            No alerts in your jurisdiction
            {level ? ` at level “${levelView(level).label}”` : ''}
            {unackOnly ? ' awaiting acknowledgement' : ''}. Every tracked clock is inside its
            statutory window.
          </Empty>
        ) : (
          <div className="card overflow-x-auto p-0">
            <table className="gov">
              <thead>
                <tr>
                  <th>Level</th>
                  <th>Case</th>
                  <th>Clock</th>
                  <th>Due</th>
                  <th>Days</th>
                  <th>Escalated to</th>
                  <th>Age</th>
                  <th>Acknowledged</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => {
                  const escalated =
                    a.escalated_to_role ??
                    a.escalated_to ??
                    ESCALATION[String(a.level ?? '').toLowerCase()] ??
                    null
                  return (
                    <tr key={a.id} className="hover:bg-surface">
                      <td>
                        <LevelChip level={a.level} title={a.consequence ?? undefined} />
                      </td>
                      <td className="whitespace-nowrap">
                        {a.case_id ? (
                          <Link
                            to={`/cases/${a.case_id}`}
                            className="font-medium text-accent underline decoration-dotted underline-offset-2"
                          >
                            {a.case_no || 'Open case'}
                          </Link>
                        ) : (
                          a.case_no || '—'
                        )}
                        <div className="max-w-[16rem] truncate text-[11px] text-muted">
                          {a.project || a.project_name || ''}
                        </div>
                      </td>
                      <td className="max-w-[22rem]">
                        <div className="font-medium">{titleize(a.clock_id)}</div>
                        <div className="text-[11px] text-muted">
                          {a.basis ? <span className="font-semibold">{a.basis} · </span> : null}
                          {a.consequence || 'Consequence not recorded in the rule-set'}
                        </div>
                      </td>
                      <td className="whitespace-nowrap">{formatDay(a.due_date)}</td>
                      <td className="whitespace-nowrap">
                        <DaysLeft days={a.days_left} />
                      </td>
                      <td className="whitespace-nowrap">{titleize(escalated)}</td>
                      <td className="whitespace-nowrap">
                        {a.age_days === null || a.age_days === undefined
                          ? '—'
                          : `${formatCount(a.age_days)} d`}
                      </td>
                      <td className="whitespace-nowrap">
                        {a.acknowledged_at ? (
                          <span className="text-xs text-muted">
                            {formatDay(String(a.acknowledged_at).slice(0, 10))}
                          </span>
                        ) : canAck ? (
                          <button
                            type="button"
                            className="btn"
                            disabled={ack.isPending && ack.variables === a.id}
                            onClick={() => ack.mutate(a.id)}
                          >
                            {ack.isPending && ack.variables === a.id
                              ? 'Acknowledging…'
                              : 'Acknowledge'}
                          </button>
                        ) : (
                          <span className="text-xs text-muted" title="Read-only role">
                            read-only
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )
      ) : null}

      <p className="text-[11px] text-muted">
        Acknowledgement records <code>acknowledged_by</code> against the alert and is
        written to the administrative audit trail. It does not extend, suspend or close
        the statutory clock — only an <code>EXTENSION_GRANTED</code> or a terminating
        event does that.
        {alerts.data?.total !== undefined && alerts.data?.total !== null
          ? ` ${formatCount(alerts.data.total)} alerts in scope.`
          : ''}
        {ack.isError ? ` ${errorText(ack.error)}` : ''}
      </p>
    </div>
  )
}
