/**
 * Districts card — the national dashboard's drill-down into `/districts/:district`
 * (Docs/Frontend.md §4, Docs/APIs.md §3.10).
 *
 * The API has no "list the districts in scope" endpoint, so this component
 * assembles one from whatever the caller can already see, cheapest source first:
 *
 *   1. the dashboard's own `top_risk_cases` rows, if the server sends a district
 *      on them (it does not today — see the note at the bottom of this file);
 *   2. the project list, if a project row carries a district;
 *   3. a bounded fan-out over the first few projects, whose detail body does
 *      carry `district_id` + `district_name` per case (APIs.md §3.2).
 *
 * Each step runs only when the one before it found nothing, and the fan-out is
 * capped, so the common path is zero extra requests and the demo path is two.
 * Every read is tolerant: a shape the API has not got yet renders as an empty
 * card with an explanation, never as a broken screen.
 */
import { useQueries, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import { Empty, Loading, Panel } from './Feedback'
import { formatCount, listOf, textOf } from './format'

/** How many project detail bodies the last-resort source will fetch. */
const MAX_PROJECT_FANOUT = 6

export interface DistrictRef {
  /** Dedupe key — the lower-cased name, or the id when the name is unknown. */
  key: string
  name: string | null
  id: string | null
  /** Distinct cases seen for this district, or the row count when ids are absent. */
  cases: number
}

interface Acc {
  key: string
  name: string | null
  id: string | null
  caseIds: Set<string>
  rows: number
}

type Row = Record<string, unknown>

function addRow(acc: Map<string, Acc>, row: unknown): void {
  if (!row || typeof row !== 'object') return
  const r = row as Row
  const name = textOf(r, 'district_name', 'district')
  const id = textOf(r, 'district_id')
  if (!name && !id) return
  const key = (name ?? id ?? '').trim().toLowerCase()
  if (!key) return
  let entry = acc.get(key)
  if (!entry) {
    entry = { key, name: name ?? null, id: id ?? null, caseIds: new Set(), rows: 0 }
    acc.set(key, entry)
  }
  if (!entry.name && name) entry.name = name
  if (!entry.id && id) entry.id = id
  entry.rows += 1
  const caseId = textOf(r, 'case_id', 'id')
  if (caseId) entry.caseIds.add(caseId)
}

function harvest(rows: unknown[]): DistrictRef[] {
  const acc = new Map<string, Acc>()
  for (const row of rows) addRow(acc, row)
  return [...acc.values()]
    .map((e) => ({
      key: e.key,
      name: e.name,
      id: e.id,
      // A top-risk row is one clock, not one case, so distinct case ids win
      // wherever the source carries them.
      cases: e.caseIds.size || e.rows,
    }))
    .sort((a, b) => (a.name ?? a.key).localeCompare(b.name ?? b.key))
}

export default function DistrictsCard({ rows = [] }: { rows?: unknown[] }) {
  /* 1 — free: whatever the dashboard already returned. */
  const fromRows = harvest(rows)

  /* 2 — one request: the project list. */
  const projects = useQuery({
    queryKey: ['projects', 'districtsCard'],
    queryFn: () => api<unknown>('/projects?limit=50'),
    enabled: fromRows.length === 0,
    staleTime: 5 * 60_000,
    retry: false,
  })
  const projectRows = listOf<Row>(projects.data, 'projects')
  const fromProjects = fromRows.length ? fromRows : harvest(projectRows)

  /* 3 — bounded fan-out: project detail bodies carry a district per case. */
  const needFanout = fromProjects.length === 0 && projects.isSuccess
  const projectIds = projectRows
    .map((p) => textOf(p, 'id'))
    .filter((id): id is string => Boolean(id))
    .slice(0, MAX_PROJECT_FANOUT)

  const details = useQueries({
    queries: projectIds.map((pid) => ({
      // Same key ProjectPage uses, so opening a project afterwards is a cache hit.
      queryKey: ['project', pid],
      queryFn: () => api<Row>(`/projects/${pid}`),
      enabled: needFanout,
      staleTime: 5 * 60_000,
      retry: false,
    })),
  })

  const fanoutRows: Row[] = needFanout
    ? details.flatMap((q) => listOf<Row>((q.data as Row | undefined)?.cases, 'cases'))
    : []
  const districts = fromProjects.length ? fromProjects : harvest(fanoutRows)

  const busy =
    districts.length === 0 &&
    (projects.isLoading || (needFanout && details.some((q) => q.isLoading)))

  const totalCases = districts.reduce((s, d) => s + d.cases, 0)

  return (
    <Panel
      title="Districts"
      right={
        districts.length
          ? `${formatCount(districts.length)} in scope · ${formatCount(totalCases)} cases`
          : 'drill down'
      }
    >
      {busy ? <Loading label="Resolving districts in scope…" /> : null}

      {!busy && districts.length === 0 ? (
        <Empty>
          No district could be resolved from the figures on this page. A district
          dashboard is still reachable directly at <code>/districts/&lt;name&gt;</code>.
        </Empty>
      ) : null}

      {districts.length ? (
        <>
          <ul className="flex flex-wrap gap-2">
            {districts.map((d) => {
              const label = d.name ?? `${(d.id ?? '').slice(0, 8)}…`
              const target = d.name ?? d.id ?? ''
              return (
                <li key={d.key}>
                  <Link
                    to={`/districts/${encodeURIComponent(target)}`}
                    className="flex items-baseline gap-2 rounded border border-border bg-surface px-3 py-1.5 hover:border-accent hover:bg-bg focus:outline-none focus:ring-2 focus:ring-accent"
                    title={
                      d.id ? `District ${label} (${d.id})` : `District dashboard for ${label}`
                    }
                  >
                    <span className="font-medium text-accent underline decoration-dotted underline-offset-2">
                      {label}
                    </span>
                    <span className="text-xs tabular-nums text-muted">
                      {formatCount(d.cases)} {d.cases === 1 ? 'case' : 'cases'}
                    </span>
                  </Link>
                </li>
              )
            })}
          </ul>
          <p className="mt-2 text-xs text-muted">
            A district dashboard resolves its scope by name, LGD code or id
            (Docs/APIs.md §3.10) and re-computes every figure over that district's
            cases — it is not a client-side filter of this page.
          </p>
        </>
      ) : null}
    </Panel>
  )
}

/*
 * Note for the dashboards lane: source (1) is the one that should win. Adding
 * `district` / `district_id` to the rows returned by
 * `app.domain.dashboards.service.top_risk_cases` (the join already has `Case`,
 * so it is an outer join to `OrgUnit` and two more dict keys) would make sources
 * (2) and (3) — and the fan-out with them — deletable.
 */
