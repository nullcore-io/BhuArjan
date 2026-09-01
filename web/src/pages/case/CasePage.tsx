/**
 * CasePage (/cases/:id) — the product. Docs/Frontend.md §2.
 *
 * Three columns on desktop, stacked below:
 *   left   clocks          GET /cases/{id}/clocks
 *   middle timeline+ledger GET /cases/{id}/events
 *   right  documents+map   GET /cases/{id}/documents · /parcels
 * Tabs underneath: Compensation · Alerts · Integrity.
 *
 * Every panel loads independently, so one dead endpoint degrades that panel
 * rather than the screen.
 */
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../lib/api'
import AlertsTab from '../../components/case/AlertsTab'
import ClockCard, { ExtendClockModal } from '../../components/case/ClockCard'
import CompensationTab from '../../components/case/CompensationTab'
import DocumentsPanel from '../../components/case/DocumentsPanel'
import IntegrityBadge, { IntegrityChip } from '../../components/case/IntegrityBadge'
import Ledger from '../../components/case/Ledger'
import ParcelMap from '../../components/case/ParcelMap'
import StatutoryTimeline from '../../components/case/StatutoryTimeline'
import {
  CaseAlert,
  Clock,
  LedgerEvent,
  clockLevel,
  errorText,
  fetchAlerts,
  fetchCase,
  fetchCaseDocuments,
  fetchClocks,
  fetchCompensation,
  fetchEvents,
  fetchIntegrity,
  fetchParcels,
  fetchRisk,
  titleize,
} from '../../components/case/caseApi'

const TABS = ['compensation', 'alerts', 'integrity'] as const
type Tab = (typeof TABS)[number]

const STAGE_TONE: Record<string, string> = {
  LAPSED: 'bg-breached text-white border border-breached',
  CLOSED: 'bg-surface text-muted border border-border',
  POSSESSED: 'bg-ok/10 text-[#1B5E20] border border-ok',
}

export default function CasePage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('compensation')
  const [extending, setExtending] = useState<Clock | null>(null)

  const caseQ = useQuery({ queryKey: ['case', id], queryFn: () => fetchCase(id), enabled: !!id })
  // Role gating per Docs/Frontend.md §2 — the API is the real enforcement point;
  // the UI just does not offer what the server would refuse.
  const meQ = useQuery<{ roles?: string[] }>({ queryKey: ['me'], queryFn: () => api('/auth/me') })
  const roles = meQ.data?.roles ?? []
  const canRecord = ['LAO', 'COLLECTOR', 'STATE_REVENUE'].some((r) => roles.includes(r))
  const canExtend = ['COLLECTOR', 'STATE_REVENUE'].some((r) => roles.includes(r))
  const clocksQ = useQuery({
    queryKey: ['case', id, 'clocks'],
    queryFn: () => fetchClocks(id),
    enabled: !!id,
  })
  const eventsQ = useInfiniteQuery({
    queryKey: ['case', id, 'events'],
    queryFn: ({ pageParam }) => fetchEvents(id, { cursor: pageParam, limit: 200 }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: !!id,
  })
  const integrityQ = useQuery({
    queryKey: ['case', id, 'integrity'],
    queryFn: () => fetchIntegrity(id),
    enabled: !!id,
  })
  const riskQ = useQuery({
    queryKey: ['case', id, 'risk'],
    queryFn: () => fetchRisk(id),
    enabled: !!id,
    retry: false,
  })
  const parcelsQ = useQuery({
    queryKey: ['case', id, 'parcels'],
    queryFn: () => fetchParcels(id),
    enabled: !!id,
  })
  const compQ = useQuery({
    queryKey: ['case', id, 'compensation'],
    queryFn: () => fetchCompensation(id),
    enabled: !!id,
  })
  const alertsQ = useQuery({ queryKey: ['alerts'], queryFn: fetchAlerts })

  const events: LedgerEvent[] = useMemo(() => {
    const all = eventsQ.data?.pages.flatMap((p) => p.items) ?? []
    return [...all].sort((a, b) => Number(b.seq ?? 0) - Number(a.seq ?? 0))
  }, [eventsQ.data])

  // Keyed on the case alone: "load older events" must not re-fetch every document.
  const docsQ = useQuery({
    queryKey: ['case', id, 'documents'],
    queryFn: () => fetchCaseDocuments(id, events),
    enabled: !!id && !eventsQ.isLoading,
  })

  const kase = caseQ.data
  // GET /cases/{id} already carries clocks[]; the dedicated endpoint wins when served.
  const clocks: Clock[] = clocksQ.data?.length ? clocksQ.data : (kase?.clocks ?? [])
  const stage = kase?.stage ?? kase?.case_state?.stage ?? null
  const risk = riskQ.data?.score ?? kase?.risk_score ?? kase?.case_state?.risk_score ?? null
  const caseAlerts: CaseAlert[] = (alertsQ.data?.items ?? []).filter(
    (a) => a.case_id === id || (kase?.case_no != null && a.case_no === kase.case_no),
  )

  const sortedClocks = useMemo(() => {
    const rank: Record<string, number> = {
      lapsed: 0,
      breached: 1,
      red: 2,
      amber: 3,
      suspended: 4,
      ok: 5,
      closed: 6,
    }
    return [...clocks].sort((a, b) => rank[clockLevel(a)] - rank[clockLevel(b)])
  }, [clocks])

  if (!id) return <p className="card">No case id in the URL.</p>

  if (caseQ.isLoading) {
    return <p className="card text-sm text-muted">Loading case…</p>
  }
  if (caseQ.isError) {
    return (
      <div className="card border-red" role="alert">
        <h1 className="text-base font-bold text-[#8C1D18]">Case not available</h1>
        <p className="mt-1 text-sm">{errorText(caseQ.error)}</p>
        <p className="mt-1 text-xs text-muted">
          A case outside your jurisdiction returns 404 by design (Docs/APIs.md §1).
        </p>
        <button type="button" className="btn mt-3" onClick={() => caseQ.refetch()}>
          Retry
        </button>
      </div>
    )
  }

  return (
    <div>
      {/* ───────────────────────────────────────────────────────────── header */}
      <header className="card mb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-bold text-ink">{kase?.case_no || 'Case'}</h1>
              <span className="badge border border-accent bg-accent/10 text-accent">
                {titleize(kase?.statute_track)}
              </span>
              <span
                className={`badge ${STAGE_TONE[String(stage ?? '')] ?? 'bg-ink text-white border border-ink'}`}
              >
                Stage: {titleize(stage) || 'Unknown'}
              </span>
              <IntegrityChip
                integrity={integrityQ.data}
                loading={integrityQ.isLoading}
                error={integrityQ.error}
              />
            </div>
            <p className="mt-1 text-sm text-muted">
              {kase?.project_id ? (
                <Link
                  to={`/projects/${kase.project_id}`}
                  className="text-accent underline-offset-2 hover:underline"
                >
                  {kase?.project_name || kase?.project?.name || 'Project'}
                </Link>
              ) : (
                (kase?.project_name ?? kase?.project?.name ?? 'Project')
              )}
              {kase?.district_name ? ` · ${kase.district_name}` : ''}
              {kase?.ruleset_version ? (
                <span className="ml-2 font-mono text-xs">
                  {kase.statute_track}@{kase.ruleset_version}
                </span>
              ) : null}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <div className="rounded border border-border bg-surface px-3 py-1.5 text-center">
              <p className="text-[11px] uppercase tracking-wide text-muted">Risk score</p>
              <p className="text-lg font-bold tabular-nums text-ink">
                {risk == null ? '—' : Number(risk).toFixed(0)}
              </p>
            </div>
            {canRecord ? (
              <Link to={`/cases/${id}/record`} className="btn-primary">
                Record event
              </Link>
            ) : null}
          </div>
        </div>
        {riskQ.data?.drivers?.length ? (
          <p className="mt-2 text-xs text-muted">
            Drivers:{' '}
            {riskQ.data.drivers
              .map((d) => (typeof d === 'string' ? d : (d.label ?? d.detail ?? '')))
              .filter(Boolean)
              .join(' · ')}
          </p>
        ) : null}
      </header>

      {/* ─────────────────────────────────────────────────────── three columns */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
        {/* left — clocks */}
        <div className="lg:col-span-3">
          <section className="card" aria-labelledby="clocks-h">
            <div className="flex items-baseline justify-between gap-2">
              <h2 id="clocks-h" className="text-sm font-bold uppercase tracking-wide text-muted">
                Statutory clocks
              </h2>
              <span className="text-xs text-muted">{sortedClocks.length}</span>
            </div>
            {clocksQ.isLoading && !clocks.length ? (
              <p className="mt-3 text-xs text-muted">Loading clocks…</p>
            ) : clocksQ.isError && !clocks.length ? (
              <p
                role="alert"
                className="mt-3 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]"
              >
                Could not load clocks: {errorText(clocksQ.error)}
              </p>
            ) : sortedClocks.length === 0 ? (
              <p className="mt-3 text-xs text-muted">
                No clocks are running — none has been started by an event yet.
              </p>
            ) : (
              <ul className="mt-2 space-y-2">
                {sortedClocks.map((c) => (
                  <ClockCard key={c.clock_id} clock={c} onExtend={canExtend ? setExtending : undefined} />
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* middle — timeline over ledger */}
        <div className="space-y-3 lg:col-span-6">
          <StatutoryTimeline
            track={kase?.statute_track}
            stage={stage}
            events={events}
            clocks={clocks}
          />
          <Ledger
            events={events}
            loading={eventsQ.isLoading}
            error={eventsQ.error}
            hasMore={eventsQ.hasNextPage}
            loadingMore={eventsQ.isFetchingNextPage}
            onLoadMore={() => eventsQ.fetchNextPage()}
          />
        </div>

        {/* right — documents over map */}
        <div className="space-y-3 lg:col-span-3">
          <DocumentsPanel
            documents={docsQ.data ?? []}
            loading={docsQ.isLoading}
            error={docsQ.error}
          />
          <ParcelMap data={parcelsQ.data} loading={parcelsQ.isLoading} error={parcelsQ.error} />
        </div>
      </div>

      {/* ──────────────────────────────────────────────────────────────── tabs */}
      <section className="card mt-3">
        <div role="tablist" aria-label="Case detail" className="flex gap-1 border-b border-border">
          {TABS.map((t) => (
            <button
              key={t}
              role="tab"
              id={`tab-${t}`}
              aria-selected={tab === t}
              aria-controls={`panel-${t}`}
              tabIndex={tab === t ? 0 : -1}
              className={`-mb-px rounded-t border border-b-0 px-3 py-1.5 text-sm font-semibold capitalize focus:outline-none focus:ring-2 focus:ring-accent ${
                tab === t
                  ? 'border-border bg-bg text-ink'
                  : 'border-transparent text-muted hover:text-ink'
              }`}
              onClick={() => setTab(t)}
              onKeyDown={(e) => {
                const i = TABS.indexOf(t)
                if (e.key === 'ArrowRight') setTab(TABS[(i + 1) % TABS.length])
                if (e.key === 'ArrowLeft') setTab(TABS[(i - 1 + TABS.length) % TABS.length])
              }}
            >
              {t}
              {t === 'alerts' && caseAlerts.length ? (
                <span className="ml-1 rounded bg-red px-1.5 text-xs text-white">
                  {caseAlerts.length}
                </span>
              ) : null}
            </button>
          ))}
        </div>

        <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} className="pt-3">
          {tab === 'compensation' ? (
            <CompensationTab data={compQ.data} loading={compQ.isLoading} error={compQ.error} />
          ) : tab === 'alerts' ? (
            <AlertsTab alerts={caseAlerts} loading={alertsQ.isLoading} error={alertsQ.error} />
          ) : (
            <IntegrityBadge
              integrity={integrityQ.data}
              loading={integrityQ.isLoading}
              error={integrityQ.error}
              rechecking={integrityQ.isFetching}
              onRecheck={() => integrityQ.refetch()}
            />
          )}
        </div>
      </section>

      {extending ? (
        <ExtendClockModal
          caseId={id}
          clock={extending}
          onClose={() => {
            setExtending(null)
            qc.invalidateQueries({ queryKey: ['case', id] })
          }}
        />
      ) : null}
    </div>
  )
}
