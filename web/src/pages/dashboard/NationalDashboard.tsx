/**
 * National dashboard — Docs/Frontend.md §4, Docs/APIs.md §3.10, Docs/rules.md C7.
 *
 * Every tile uses the problem statement's own wording, states the event
 * sequence it was computed at, and — where the server can explode it — carries
 * an Explain link that opens the contributing events and cases. That is the
 * whole argument of the product on one screen: these are not typed-in MIS
 * numbers, they are the ledger summed up, and you can walk back to the gazette.
 *
 * The response is read defensively. A field the API has not populated renders
 * as "—", never as a confident zero.
 */
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import DistrictsCard from '../../components/ui/DistrictsCard'
import Drawer from '../../components/ui/Drawer'
import { Empty, ErrorNote, Loading, Panel } from '../../components/ui/Feedback'
import KpiTile from '../../components/ui/KpiTile'
import { DaysLeft, LevelChip, StatuteBadge } from '../../components/ui/StatBadge'
import {
  formatCount,
  formatDay,
  formatHa,
  formatPct,
  listOf,
  moneyScale,
  num,
  present,
  titleize,
} from '../../components/ui/format'
import { api, formatINR } from '../../lib/api'
import ClockHealthChart from '../../components/charts/ClockHealthChart'
import CompensationChart from '../../components/charts/CompensationChart'
import StageFunnelChart from '../../components/charts/StageFunnelChart'
import { CLOCK_STATUS_ORDER } from '../../theme/charts'

/* --------------------------------------------------------------- API shapes */

interface Kpis {
  area_proposed_ha?: number | null
  area_notified_ha?: number | null
  area_acquired_ha?: number | null
  notifications_issued?: number | null
  awards_declared?: number | null
  comp_assessed_paise?: number | null
  comp_paid_paise?: number | null
  possession_pct?: number | null
  rr_progress_pct?: number | null
  families_affected?: number | null
  families_displaced?: number | null
  timeline_adherence_pct?: number | null
  clocks_by_status?: Record<string, number> | null
  case_count?: number | null
  sources?: Record<string, string> | null
}

interface SeriesPoint {
  month: string
  assessed_paise?: number | null
  paid_paise?: number | null
}

interface FunnelRow {
  stage: string
  count: number
}

interface RiskRow {
  case_id?: string | null
  case_no?: string | null
  project?: string | null
  statute_track?: string | null
  clock_id?: string | null
  basis?: string | null
  consequence?: string | null
  status?: string | null
  level?: string | null
  due_date?: string | null
  days_left?: number | null
}

interface DashboardResponse {
  level?: string | null
  scope_id?: string | null
  as_of_seq?: number | null
  as_of_date?: string | null
  filters?: Record<string, unknown> | null
  kpis?: Kpis | null
  series?: { assessed_vs_paid_monthly?: SeriesPoint[] | null } | null
  stage_funnel?: FunnelRow[] | null
  top_risk_cases?: RiskRow[] | null
}

interface ExplainCase {
  case_id?: string | null
  case_no?: string | null
  project?: string | null
  statute_track?: string | null
  state_code?: string | null
  event_ids?: string[] | null
  contribution?: number | null
  unit?: string | null
}

interface ExplainResponse {
  kpi?: string
  as_of_seq?: number | null
  as_of_date?: string | null
  event_types?: string[] | null
  event_ids?: string[] | null
  cases?: ExplainCase[] | null
}

/* -------------------------------------------------------------- tile config */

interface TileDef {
  /** Key in the `kpis` block. */
  key: keyof Kpis
  /** Exact PS wording (Docs/Frontend.md §4). */
  label: string
  labelHi: string
  format: (v: unknown) => string
  /** KPI name accepted by /dashboards/national/explain, when explainable. */
  explain?: string
}

const TILES: TileDef[] = [
  {
    key: 'area_notified_ha',
    label: 'Area notified',
    labelHi: 'अधिसूचित क्षेत्र',
    format: formatHa,
    explain: 'area_notified_ha',
  },
  {
    key: 'area_acquired_ha',
    label: 'Area acquired',
    labelHi: 'अर्जित क्षेत्र',
    format: formatHa,
    explain: 'area_acquired_ha',
  },
  {
    key: 'comp_assessed_paise',
    label: 'Compensation assessed',
    labelHi: 'निर्धारित मुआवजा',
    format: (v) => (present(v) ? formatINR(num(v)) : '—'),
    explain: 'comp_assessed_paise',
  },
  {
    key: 'comp_paid_paise',
    label: 'Compensation paid',
    labelHi: 'भुगतान किया गया मुआवजा',
    format: (v) => (present(v) ? formatINR(num(v)) : '—'),
    explain: 'comp_paid_paise',
  },
  {
    key: 'families_affected',
    label: 'Affected families',
    labelHi: 'प्रभावित परिवार',
    format: formatCount,
  },
  {
    key: 'families_displaced',
    label: 'Displaced families',
    labelHi: 'विस्थापित परिवार',
    format: formatCount,
  },
  {
    key: 'rr_progress_pct',
    label: 'R&R status',
    labelHi: 'पुनर्वास एवं पुनर्व्यवस्थापन',
    format: formatPct,
  },
  {
    key: 'possession_pct',
    label: 'Possession status',
    labelHi: 'कब्जे की स्थिति',
    format: formatPct,
  },
  {
    key: 'timeline_adherence_pct',
    label: 'Timeline adherence',
    labelHi: 'समय-सीमा पालन',
    format: formatPct,
  },
]

/** Used only if GET /dashboards/explainable-kpis is not served. */
const FALLBACK_EXPLAINABLE = new Set([
  'area_notified_ha',
  'area_acquired_ha',
  'comp_assessed_paise',
  'comp_paid_paise',
])

const STATUTE_OPTIONS = [
  { value: '', label: 'All statute tracks' },
  { value: 'RFCTLARR_2013', label: 'RFCTLARR 2013' },
  { value: 'NH_ACT_1956', label: 'NH Act 1956' },
]

/* -------------------------------------------------------------- the screen */

export default function NationalDashboard() {
  const [sector, setSector] = useState('')
  const [statute, setStatute] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [cumulative, setCumulative] = useState(true)
  const [explainKpi, setExplainKpi] = useState<string | null>(null)

  const qs = new URLSearchParams()
  if (sector) qs.set('sector', sector)
  if (statute) qs.set('statute', statute)
  if (from) qs.set('from', from)
  if (to) qs.set('to', to)
  const suffix = qs.toString() ? `?${qs}` : ''

  const dash = useQuery({
    queryKey: ['dashboard', 'national', sector, statute, from, to],
    queryFn: () => api<DashboardResponse>(`/dashboards/national${suffix}`),
  })

  const explainable = useQuery({
    queryKey: ['explainableKpis'],
    queryFn: () => api<{ kpis?: string[] }>('/dashboards/explainable-kpis'),
    staleTime: 5 * 60_000,
    retry: false,
  })

  const explainableSet = explainable.data?.kpis
    ? new Set(explainable.data.kpis)
    : FALLBACK_EXPLAINABLE

  const d = dash.data
  const kpis = d?.kpis ?? {}
  const asOfSeq = d?.as_of_seq ?? null
  const sources = kpis.sources ?? {}

  const risk = listOf<RiskRow>(d?.top_risk_cases, 'top_risk_cases')
  // Only reach for /alerts when the dashboard did not carry its own risk queue.
  const alertsFallback = useQuery({
    queryKey: ['alerts', 'dashboardFallback'],
    queryFn: () => api<unknown>('/alerts?limit=10'),
    enabled: dash.isSuccess && risk.length === 0,
    retry: false,
  })
  const riskRows: RiskRow[] = risk.length
    ? risk
    : listOf<Record<string, unknown>>(alertsFallback.data, 'alerts').map((a) => ({
        case_id: (a.case_id as string) ?? null,
        case_no: (a.case_no as string) ?? null,
        project: (a.project as string) ?? (a.project_name as string) ?? null,
        statute_track: (a.statute_track as string) ?? null,
        clock_id: (a.clock_id as string) ?? null,
        basis: (a.basis as string) ?? null,
        consequence: (a.consequence as string) ?? null,
        status: (a.clock_status as string) ?? null,
        level: (a.level as string) ?? null,
        due_date: (a.due_date as string) ?? null,
        days_left: (a.days_left as number) ?? null,
      }))

  /* --- chart data ------------------------------------------------------- */

  const rawSeries = listOf<SeriesPoint>(d?.series?.assessed_vs_paid_monthly)
  const maxPaise = rawSeries.reduce(
    (m, p) => Math.max(m, num(p.assessed_paise), num(p.paid_paise)),
    0,
  )
  const scale = moneyScale(cumulative ? rawSeries.reduce((s, p) => s + num(p.assessed_paise), 0) : maxPaise)
  let runningAssessed = 0
  let runningPaid = 0
  const series = rawSeries.map((p) => {
    runningAssessed += num(p.assessed_paise)
    runningPaid += num(p.paid_paise)
    const a = cumulative ? runningAssessed : num(p.assessed_paise)
    const b = cumulative ? runningPaid : num(p.paid_paise)
    return {
      month: p.month,
      Assessed: a / scale.divisor,
      Paid: b / scale.divisor,
      assessedPaise: a,
      paidPaise: b,
    }
  })

  const funnel = listOf<FunnelRow>(d?.stage_funnel, 'stage_funnel').map((r) => ({
    stage: titleize(r.stage),
    count: num(r.count),
  }))

  const clockRecord = kpis.clocks_by_status ?? {}
  const clockKeys = [
    ...CLOCK_STATUS_ORDER.filter((k) => k in clockRecord),
    ...Object.keys(clockRecord).filter((k) => !CLOCK_STATUS_ORDER.includes(k)),
  ]
  const clockData = clockKeys.map((k) => ({
    status: titleize(k),
    key: k,
    count: num(clockRecord[k]),
  }))
  const clockTotal = clockData.reduce((s, r) => s + r.count, 0)

  /* --- tile subtitles --------------------------------------------------- */

  function subFor(key: keyof Kpis): string | null {
    switch (key) {
      case 'area_notified_ha':
        return present(kpis.notifications_issued)
          ? `${formatCount(kpis.notifications_issued)} notifications · s.11 / 3A`
          : 's.11 / 3A'
      case 'area_acquired_ha':
        return present(kpis.area_notified_ha) && num(kpis.area_notified_ha) > 0
          ? `of ${formatHa(kpis.area_notified_ha)} notified · s.38 / 3E`
          : 's.38 / 3E possession'
      case 'comp_assessed_paise':
        return present(kpis.awards_declared)
          ? `${formatCount(kpis.awards_declared)} awards · ss.26–30 + First Schedule`
          : 'ss.26–30 + First Schedule'
      case 'comp_paid_paise': {
        if (!present(kpis.comp_assessed_paise) || !present(kpis.comp_paid_paise)) return null
        const outstanding = num(kpis.comp_assessed_paise) - num(kpis.comp_paid_paise)
        return `Outstanding ${formatINR(Math.max(outstanding, 0))}`
      }
      case 'families_affected':
        return present(kpis.case_count) ? `across ${formatCount(kpis.case_count)} cases` : null
      case 'families_displaced':
        return present(kpis.families_affected) && num(kpis.families_affected) > 0
          ? `${formatPct((100 * num(kpis.families_displaced)) / num(kpis.families_affected))} of affected`
          : 'Second Schedule entitlements'
      case 'rr_progress_pct':
        return 'entitlements delivered · s.31, Second/Third Schedule'
      case 'possession_pct':
        return 'area acquired ÷ area notified'
      case 'timeline_adherence_pct':
        return clockTotal
          ? `${formatCount(clockTotal)} statutory clocks tracked`
          : 'statutory clocks on time'
      default:
        return null
    }
  }

  /* --- render ----------------------------------------------------------- */

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">
            National dashboard <span className="font-normal text-muted">/ राष्ट्रीय डैशबोर्ड</span>
          </h1>
          <p className="text-xs text-muted">
            Every figure is the ledger summed to{' '}
            <strong className="font-semibold">
              {asOfSeq === null ? 'an unknown sequence' : `sequence ${asOfSeq}`}
            </strong>
            {d?.as_of_date ? ` as at ${formatDay(d.as_of_date)}` : ''} — Docs/rules.md C7.
          </p>
        </div>

        <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => e.preventDefault()}>
          <label className="flex flex-col gap-0.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted">
              Statute
            </span>
            <select
              className="rounded border border-border bg-bg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              value={statute}
              onChange={(e) => setStatute(e.target.value)}
            >
              {STATUTE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted">
              Sector
            </span>
            <input
              className="w-40 rounded border border-border bg-bg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              value={sector}
              placeholder="e.g. National Highways"
              onChange={(e) => setSector(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted">
              From
            </span>
            <input
              type="date"
              className="rounded border border-border bg-bg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-0.5">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted">To</span>
            <input
              type="date"
              className="rounded border border-border bg-bg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              value={to}
              onChange={(e) => setTo(e.target.value)}
            />
          </label>
          {sector || statute || from || to ? (
            <button
              type="button"
              className="btn"
              onClick={() => {
                setSector('')
                setStatute('')
                setFrom('')
                setTo('')
              }}
            >
              Clear
            </button>
          ) : null}
        </form>
      </header>

      {(from || to) && d?.filters && 'window_applies_to' in (d.filters ?? {}) ? (
        <div className="rounded border border-amber bg-amber/5 px-3 py-1.5 text-xs text-[#8A5300]">
          The date range clips the assessed-vs-paid series only. KPI tiles are
          cumulative statutory positions — area notified to date, money outstanding
          today — and a windowed version of them would not be a fact about anything.
        </div>
      ) : null}

      {dash.isLoading ? <Loading label="Loading national figures…" /> : null}
      {dash.isError ? <ErrorNote error={dash.error} what="National dashboard" /> : null}

      {dash.isSuccess ? (
        <>
          {/* --- KPI tiles --- */}
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {TILES.map((t) => {
              const canExplain = Boolean(t.explain && explainableSet.has(t.explain))
              return (
                <KpiTile
                  key={String(t.key)}
                  label={t.label}
                  labelHi={t.labelHi}
                  value={t.format(kpis[t.key])}
                  sub={subFor(t.key)}
                  asOfSeq={asOfSeq}
                  source={sources[String(t.key)] ?? null}
                  onExplain={
                    canExplain && t.explain ? () => setExplainKpi(t.explain as string) : undefined
                  }
                />
              )
            })}
          </div>

          <Panel
            title="Top-risk cases"
            right={risk.length ? 'nearest statutory deadline first' : 'from the alert queue'}
          >
            {alertsFallback.isError && risk.length === 0 ? (
              <ErrorNote error={alertsFallback.error} what="Risk queue" />
            ) : riskRows.length === 0 ? (
              <Empty>No open clocks approaching their statutory due date.</Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="gov dense">
                  <thead>
                    <tr>
                      <th>Case</th>
                      <th>Project</th>
                      <th>Clock</th>
                      <th>Status</th>
                      <th>Due</th>
                      <th>Days</th>
                    </tr>
                  </thead>
                  <tbody>
                    {riskRows.map((r, i) => (
                      <tr key={`${r.case_id ?? 'row'}-${r.clock_id ?? i}`}>
                        <td className="whitespace-nowrap">
                          {r.case_id ? (
                            <Link
                              className="text-accent underline decoration-dotted underline-offset-2"
                              to={`/cases/${r.case_id}`}
                            >
                              {r.case_no || 'Open case'}
                            </Link>
                          ) : (
                            r.case_no || '—'
                          )}
                        </td>
                        <td className="max-w-[16rem] truncate" title={r.project ?? undefined}>
                          {r.project || '—'}
                        </td>
                        <td title={r.consequence ?? undefined}>
                          {titleize(r.clock_id)}
                          {r.basis ? (
                            <span className="ml-1 text-xs text-muted">({r.basis})</span>
                          ) : null}
                        </td>
                        <td>
                          <LevelChip
                            level={r.level ?? r.status}
                            title={r.consequence ?? undefined}
                          />
                        </td>
                        <td className="whitespace-nowrap">{formatDay(r.due_date)}</td>
                        <td className="whitespace-nowrap">
                          <DaysLeft days={r.days_left} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          {/* --- charts --- */}
          {/* Each chart ships its own text-equivalent table and keyboard
              legend (Docs/design.md §4); see components/charts/. */}
          <div className="grid gap-5 xl:grid-cols-2">
            <CompensationChart
              series={series}
              scale={scale}
              right={
                <label className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={cumulative}
                    onChange={(e) => setCumulative(e.target.checked)}
                  />
                  Cumulative
                </label>
              }
              caption="Gap between the lines is money owed to landowners under s.30 — interest at 12% p.a. accrues on it (s.30(3))."
            />

            <StageFunnelChart funnel={funnel} />

            <ClockHealthChart
              data={clockData}
              right={clockTotal ? `${formatCount(clockTotal)} clocks` : undefined}
              caption="Breached and lapsed are distinct: a breach is a missed deadline, a lapse is the statutory consequence of one (s.25 / s.19(7))."
            />


            {/* Drill-down: each district re-computes its own figures server-side. */}
            <DistrictsCard rows={riskRows} />
          </div>
        </>
      ) : null}

      <ExplainDrawer kpi={explainKpi} query={suffix} onClose={() => setExplainKpi(null)} />
    </div>
  )
}

/* ------------------------------------------------------------ explain drawer */

const KPI_TITLE: Record<string, string> = {
  area_notified_ha: 'Area notified',
  area_acquired_ha: 'Area acquired',
  area_proposed_ha: 'Area proposed',
  comp_assessed_paise: 'Compensation assessed',
  comp_paid_paise: 'Compensation paid',
  notifications_issued: 'Notifications issued',
  awards_declared: 'Awards declared',
}

function contributionText(unit: string | null | undefined, value: number): string {
  if (unit === 'paise') return formatINR(value)
  if (unit === 'ha') return formatHa(value)
  return formatCount(value)
}

function ExplainDrawer({
  kpi,
  query,
  onClose,
}: {
  kpi: string | null
  query: string
  onClose: () => void
}) {
  // Only the filters the explain endpoint honours (sector, statute) are forwarded.
  const params = new URLSearchParams(query.startsWith('?') ? query.slice(1) : query)
  const explainQs = new URLSearchParams()
  if (kpi) explainQs.set('kpi', kpi)
  for (const k of ['sector', 'statute']) {
    const v = params.get(k)
    if (v) explainQs.set(k, v)
  }

  const q = useQuery({
    queryKey: ['explain', kpi, explainQs.toString()],
    queryFn: () => api<ExplainResponse>(`/dashboards/national/explain?${explainQs}`),
    enabled: Boolean(kpi),
  })

  const cases = listOf<ExplainCase>(q.data?.cases, 'cases')
  const eventIds = listOf<string>(q.data?.event_ids, 'event_ids')

  return (
    <Drawer
      open={Boolean(kpi)}
      title={`Explain — ${KPI_TITLE[kpi ?? ''] ?? titleize(kpi)}`}
      subtitle={
        q.data
          ? `as of seq ${q.data.as_of_seq ?? '—'} · ${eventIds.length} contributing events across ${cases.length} cases`
          : 'Contributing events from the ledger'
      }
      onClose={onClose}
    >
      {q.isLoading ? <Loading label="Reading the ledger…" /> : null}
      {q.isError ? <ErrorNote error={q.error} what="Explain" /> : null}

      {q.isSuccess ? (
        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap gap-1">
            {listOf<string>(q.data?.event_types, 'event_types').map((t) => (
              <span key={t} className="badge bg-surface text-muted border border-border">
                {t}
              </span>
            ))}
          </div>

          {cases.length === 0 ? (
            <Empty>No events contribute to this figure in the current scope.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="gov dense">
                <thead>
                  <tr>
                    <th>Case</th>
                    <th>Project</th>
                    <th>Statute</th>
                    <th className="text-right">Contribution</th>
                    <th className="text-right">Events</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((c, i) => (
                    <tr key={c.case_id ?? i}>
                      <td className="whitespace-nowrap">
                        {c.case_id ? (
                          <Link
                            className="text-accent underline decoration-dotted underline-offset-2"
                            to={`/cases/${c.case_id}`}
                          >
                            {c.case_no || 'Open case'}
                          </Link>
                        ) : (
                          c.case_no || '—'
                        )}
                      </td>
                      <td className="max-w-[14rem] truncate" title={c.project ?? undefined}>
                        {c.project || '—'}
                      </td>
                      <td>
                        <StatuteBadge track={c.statute_track} />
                      </td>
                      <td className="text-right tabular-nums">
                        {contributionText(c.unit, num(c.contribution))}
                      </td>
                      <td className="text-right tabular-nums">
                        {listOf<string>(c.event_ids, 'event_ids').length}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <details className="rounded border border-border bg-surface p-2 text-xs">
            <summary className="cursor-pointer font-semibold text-ink">
              Contributing event ids ({eventIds.length})
            </summary>
            <ul className="mt-2 max-h-64 overflow-auto font-mono text-xs leading-relaxed text-muted">
              {eventIds.map((id) => (
                <li key={id}>{id}</li>
              ))}
            </ul>
          </details>

          <p className="text-xs text-muted">
            Docs/rules.md C7 — every dashboard figure carries an &ldquo;as of&rdquo; sequence
            number and can be exploded to the events that produced it.
          </p>
        </div>
      ) : null}
    </Drawer>
  )
}
