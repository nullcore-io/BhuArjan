/**
 * Project page — Docs/APIs.md §3.2 (`GET /projects/{id}` → project + KPIs +
 * cases[]), Docs/Frontend.md §1.
 *
 * The KPI block reuses the dashboard tiles so the same nine PS figures mean the
 * same thing at every level of the hierarchy. Project-level figures are not
 * event-explainable (the explain endpoint is defined for national/state/district
 * scopes only), so the tiles show their provenance sequence without an Explain
 * link rather than offering one that would 404.
 */
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Empty, ErrorNote, Loading, Panel } from '../../components/ui/Feedback'
import KpiTile from '../../components/ui/KpiTile'
import { DaysLeft, RiskScore, StageBadge, StatuteBadge } from '../../components/ui/StatBadge'
import {
  formatCount,
  formatDay,
  formatHa,
  formatPct,
  listOf,
  num,
  present,
  textOf,
  titleize,
} from '../../components/ui/format'
import { api, formatINR } from '../../lib/api'
import { caseCountOf, requiringBodyOf } from './ProjectList'
import type { ProjectRow } from './ProjectList'

interface ProjectKpis {
  area_notified_ha?: number | null
  area_acquired_ha?: number | null
  comp_assessed_paise?: number | null
  comp_paid_paise?: number | null
  families_affected?: number | null
  families_displaced?: number | null
  rr_progress_pct?: number | null
  possession_pct?: number | null
  timeline_adherence_pct?: number | null
  case_count?: number | null
  sources?: Record<string, string> | null
}

interface CaseRow {
  id: string
  case_no?: string | null
  district?: string | { name?: string } | null
  district_name?: string | null
  district_id?: string | null
  stage?: string | null
  case_state?: { stage?: string | null; as_of_seq?: number | null } | null
  risk_score?: number | string | null
  risk?: number | string | { score?: number | string } | null
  statute_track?: string | null
  next_clock_id?: string | null
  next_due_clock?: string | { clock_id?: string; due_date?: string; days_left?: number } | null
  next_due_date?: string | null
  days_left?: number | null
}

interface ProjectDetail extends ProjectRow {
  kpis?: ProjectKpis | null
  as_of_seq?: number | null
  as_of_date?: string | null
  cases?: CaseRow[] | null
}

/* --- per-row field tolerance ------------------------------------------- */

function stageOf(c: CaseRow): string | null {
  return c.stage ?? c.case_state?.stage ?? null
}

function riskOf(c: CaseRow): number | string | null {
  if (present(c.risk_score)) return c.risk_score as number | string
  const r = c.risk
  if (r && typeof r === 'object') return (r as { score?: number | string }).score ?? null
  if (present(r)) return r as number | string
  return null
}

interface NextClock {
  id: string | null
  due: string | null
  days: number | null
}

function nextClockOf(c: CaseRow): NextClock {
  const nd = c.next_due_clock
  if (nd && typeof nd === 'object') {
    return {
      id: nd.clock_id ?? null,
      due: nd.due_date ?? c.next_due_date ?? null,
      days: nd.days_left ?? c.days_left ?? null,
    }
  }
  return {
    id: (typeof nd === 'string' ? nd : null) ?? c.next_clock_id ?? null,
    due: c.next_due_date ?? null,
    days: c.days_left ?? null,
  }
}

function districtOf(c: CaseRow): string {
  const name = textOf(c as unknown as Record<string, unknown>, 'district_name', 'district')
  if (name) return name
  return c.district_id ? `${c.district_id.slice(0, 8)}…` : '—'
}

/* ----------------------------------------------------------------- screen */

interface TileDef {
  key: keyof ProjectKpis
  label: string
  labelHi: string
  format: (v: unknown) => string
}

const TILES: TileDef[] = [
  { key: 'area_notified_ha', label: 'Area notified', labelHi: 'अधिसूचित क्षेत्र', format: formatHa },
  { key: 'area_acquired_ha', label: 'Area acquired', labelHi: 'अर्जित क्षेत्र', format: formatHa },
  {
    key: 'comp_assessed_paise',
    label: 'Compensation assessed',
    labelHi: 'निर्धारित मुआवजा',
    format: (v) => (present(v) ? formatINR(num(v)) : '—'),
  },
  {
    key: 'comp_paid_paise',
    label: 'Compensation paid',
    labelHi: 'भुगतान किया गया मुआवजा',
    format: (v) => (present(v) ? formatINR(num(v)) : '—'),
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
  { key: 'rr_progress_pct', label: 'R&R status', labelHi: 'पुनर्वास स्थिति', format: formatPct },
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

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>()

  const project = useQuery({
    queryKey: ['project', id],
    queryFn: () => api<ProjectDetail>(`/projects/${id}`),
    enabled: Boolean(id),
  })

  const p = project.data
  const kpis = p?.kpis ?? null
  const cases = listOf<CaseRow>(p?.cases, 'cases')
  const asOfSeq = p?.as_of_seq ?? null

  return (
    <div className="flex flex-col gap-4">
      <nav className="text-xs text-muted">
        <Link to="/projects" className="text-accent underline decoration-dotted underline-offset-2">
          Projects
        </Link>
        <span className="mx-1">/</span>
        <span>{p?.name || id}</span>
      </nav>

      {project.isLoading ? <Loading label="Loading project…" /> : null}
      {project.isError ? <ErrorNote error={project.error} what="Project" /> : null}

      {project.isSuccess && p ? (
        <>
          {/* --- header --- */}
          <header className="card flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h1 className="text-lg font-bold text-ink">{p.name || 'Untitled project'}</h1>
              <StatuteBadge track={p.statute_track} />
              {p.ruleset_version ? (
                <span className="badge border border-border bg-surface text-muted">
                  rule-set {p.ruleset_version}
                </span>
              ) : null}
            </div>
            <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-4">
              <div className="flex gap-2">
                <dt className="text-muted">Sector</dt>
                <dd className="font-medium">{p.sector || '—'}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="text-muted">State</dt>
                <dd className="font-medium">{p.state_code || p.state || '—'}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="text-muted">Requiring body</dt>
                <dd className="font-medium">{requiringBodyOf(p)}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="text-muted">Cases</dt>
                <dd className="font-medium tabular-nums">
                  {formatCount(cases.length || caseCountOf(p) || 0)}
                </dd>
              </div>
            </dl>
          </header>

          {/* --- KPIs --- */}
          {kpis ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
              {TILES.map((t) => (
                <KpiTile
                  key={String(t.key)}
                  label={t.label}
                  labelHi={t.labelHi}
                  value={t.format(kpis[t.key])}
                  asOfSeq={asOfSeq}
                  source={kpis.sources?.[String(t.key)] ?? null}
                />
              ))}
            </div>
          ) : (
            <Empty>
              This project record carries no KPI block yet — figures are shown per case below.
            </Empty>
          )}

          {/* --- cases --- */}
          <Panel
            title="Cases"
            right={
              asOfSeq === null ? 'one case = one s.11 / 3A proceeding' : `as of seq ${asOfSeq}`
            }
          >
            {cases.length === 0 ? (
              <Empty>No acquisition cases have been opened under this project.</Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="gov">
                  <thead>
                    <tr>
                      <th>Case no.</th>
                      <th>District</th>
                      <th>Stage</th>
                      <th>Risk</th>
                      <th>Next statutory due</th>
                      <th>Days</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cases.map((c) => {
                      const next = nextClockOf(c)
                      return (
                        <tr key={c.id} className="hover:bg-surface">
                          <td className="whitespace-nowrap">
                            <Link
                              to={`/cases/${c.id}`}
                              className="font-medium text-accent underline decoration-dotted underline-offset-2"
                            >
                              {c.case_no || 'Open case'}
                            </Link>
                          </td>
                          <td>{districtOf(c)}</td>
                          <td>
                            <StageBadge stage={stageOf(c)} />
                          </td>
                          <td>
                            <RiskScore score={riskOf(c)} />
                          </td>
                          <td>
                            {next.id ? (
                              <>
                                <span>{titleize(next.id)}</span>
                                {next.due ? (
                                  <span className="ml-1 text-xs text-muted">
                                    due {formatDay(next.due)}
                                  </span>
                                ) : null}
                              </>
                            ) : (
                              <span className="text-muted">—</span>
                            )}
                          </td>
                          <td className="whitespace-nowrap">
                            <DaysLeft days={next.days} />
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      ) : null}
    </div>
  )
}
