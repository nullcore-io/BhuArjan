/**
 * Land view — every parcel in the officer's jurisdiction on a 3D globe.
 *
 * There is no "all parcels" endpoint (Docs/APIs.md §3.2 exposes parcels per
 * case and per project only), so this fans out over the scoped project list and
 * merges the FeatureCollections client-side. That keeps the page working
 * against the deployed backend with no server change; if the parcel count ever
 * outgrows a handful of projects, this is the thing to replace with one
 * server-side endpoint.
 *
 * Scope is still enforced server-side — `/projects` returns only what this
 * officer may see, and an out-of-scope project 404s (Docs/APIs.md §2).
 */
import { useQueries, useQuery } from '@tanstack/react-query'
import { Suspense, lazy, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Empty, ErrorNote, Loading, Panel } from '../../components/ui/Feedback'
import { api } from '../../lib/api'
import { BASEMAPS, PARCEL_STATUS, PARCEL_UNKNOWN, type BasemapId } from '../../lib/mapStyles'

// MapLibre is ~900 kB. Nobody pays for it until they open this page.
const GlobeMap = lazy(() => import('../../components/map/GlobeMap'))

interface ProjectRow {
  id: string
  name?: string
}

function statusOf(props: Record<string, any> | null | undefined) {
  const key = String(props?.status ?? '').toLowerCase()
  return PARCEL_STATUS[key] ?? PARCEL_UNKNOWN
}

function num(v: unknown): number | null {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export default function MapPage() {
  const [basemap, setBasemap] = useState<BasemapId>('satellite')
  const [spinning, setSpinning] = useState(true)
  const [terrain3d, setTerrain3d] = useState(true)
  const [selected, setSelected] = useState<Record<string, any> | null>(null)
  const [flyTo, setFlyTo] = useState<{ lng: number; lat: number; key: number } | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('all')

  const projectsQ = useQuery<ProjectRow[]>({
    queryKey: ['projects', 'forMap'],
    queryFn: async () => {
      const r = await api('/projects')
      return Array.isArray(r) ? r : (r?.items ?? [])
    },
  })

  const projects = projectsQ.data ?? []

  // One request per project; an empty project 404s, which is not an error here.
  const parcelQs = useQueries({
    queries: projects.map((p) => ({
      queryKey: ['parcels', 'project', p.id],
      queryFn: () => api(`/projects/${p.id}/parcels`).catch(() => null),
      enabled: !!p.id,
      staleTime: 60_000,
    })),
  })

  const loading = projectsQ.isLoading || parcelQs.some((q) => q.isLoading)

  const merged = useMemo<GeoJSON.FeatureCollection>(() => {
    const features: GeoJSON.Feature[] = []
    parcelQs.forEach((q, i) => {
      const fc = q.data as GeoJSON.FeatureCollection | null | undefined
      if (!fc?.features) return
      for (const f of fc.features) {
        features.push({
          ...f,
          properties: { ...(f.properties ?? {}), project_name: projects[i]?.name ?? '—' },
        })
      }
    })
    return { type: 'FeatureCollection', features }
  }, [parcelQs.map((q) => q.dataUpdatedAt).join(','), projects])

  const shown = useMemo<GeoJSON.FeatureCollection>(() => {
    if (statusFilter === 'all') return merged
    return {
      type: 'FeatureCollection',
      features: merged.features.filter(
        (f) => String(f.properties?.status ?? '').toLowerCase() === statusFilter,
      ),
    }
  }, [merged, statusFilter])

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const f of merged.features) {
      const k = String(f.properties?.status ?? '').toLowerCase() || 'unknown'
      c[k] = (c[k] ?? 0) + 1
    }
    return c
  }, [merged])

  const totalHa = useMemo(
    () => merged.features.reduce((a, f) => a + (num(f.properties?.area_ha) ?? 0), 0),
    [merged],
  )

  async function flyToFeature(f: GeoJSON.Feature) {
    const { featureCentre } = await import('../../components/map/GlobeMap')
    const c = featureCentre(f)
    if (c) setFlyTo({ ...c, key: Date.now() })
    setSelected({ ...(f.properties ?? {}) })
  }

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold text-ink">
          Land view <span className="font-normal text-muted">/ भूमि दृश्य</span>
        </h1>
        <p className="mt-1 text-xs text-muted">
          Every parcel in your jurisdiction, on the ground it actually occupies. Boundaries are
          the surveyed geometry held against each case — not an illustration.
        </p>
      </header>

      {projectsQ.isError ? <ErrorNote error={projectsQ.error} what="Projects" /> : null}

      {/* ------------------------------------------------------- controls */}
      <div className="card flex flex-wrap items-center gap-x-6 gap-y-3 px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase text-muted">Basemap</span>
          <div className="flex gap-1" role="group" aria-label="Basemap">
            {BASEMAPS.map((b) => (
              <button
                key={b.id}
                type="button"
                title={b.note}
                aria-pressed={basemap === b.id}
                onClick={() => setBasemap(b.id)}
                className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                  basemap === b.id
                    ? 'bg-accent text-white'
                    : 'border border-border bg-bg text-muted hover:text-ink'
                }`}
              >
                {b.label}
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={spinning}
            onChange={(e) => setSpinning(e.target.checked)}
          />
          <span className="font-medium text-ink">Rotate globe</span>
        </label>

        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={terrain3d}
            onChange={(e) => setTerrain3d(e.target.checked)}
          />
          <span className="font-medium text-ink">3D terrain</span>
        </label>

        <label className="flex items-center gap-2 text-xs">
          <span className="font-medium uppercase text-muted">Status</span>
          <select
            className="field w-auto py-1 text-xs"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">All ({merged.features.length})</option>
            {Object.entries(PARCEL_STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v.label} ({counts[k] ?? 0})
              </option>
            ))}
          </select>
        </label>

        <div className="ml-auto text-xs text-muted">
          {merged.features.length} parcels · {totalHa.toFixed(2)} ha across {projects.length}{' '}
          project{projects.length === 1 ? '' : 's'}
        </div>
      </div>

      {/* ------------------------------------------------------------ map */}
      <div className="grid gap-6 xl:grid-cols-[1fr_22rem]">
        <div className="card overflow-hidden p-0">
          <div className="h-[34rem] w-full">
            {loading ? (
              <div className="flex h-full items-center justify-center">
                <Loading label="Loading parcels…" />
              </div>
            ) : merged.features.length === 0 ? (
              <div className="flex h-full items-center justify-center">
                <Empty>No parcels with geometry in your jurisdiction yet.</Empty>
              </div>
            ) : (
              <Suspense
                fallback={
                  <div className="flex h-full items-center justify-center">
                    <Loading label="Loading globe…" />
                  </div>
                }
              >
                <GlobeMap
                  data={shown}
                  basemap={basemap}
                  spinning={spinning}
                  terrain3d={terrain3d}
                  onSelect={setSelected}
                  onUserInteract={() => setSpinning(false)}
                  flyTo={flyTo}
                />
              </Suspense>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-5 py-2 text-xs">
            {Object.entries(PARCEL_STATUS).map(([k, v]) => (
              <span key={k} className="flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="inline-block h-3 w-3 rounded-sm"
                  style={{ background: v.colour }}
                />
                <span className="text-muted">
                  {v.label} ({counts[k] ?? 0})
                </span>
              </span>
            ))}
          </div>
        </div>

        {/* ------------------------------------------------------ details */}
        <Panel title={selected ? 'Selected parcel' : 'Parcels'} right={selected ? undefined : 'click a plot'}>
          {selected ? (
            <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-2 text-sm">
              <Row label="Survey no." value={selected.survey_no} />
              <Row label="ULPIN" value={selected.ulpin} mono />
              <Row label="Village" value={selected.village} />
              <Row label="Area" value={num(selected.area_ha)?.toFixed(4) + ' ha'} />
              <Row label="Project" value={selected.project_name} />
              <dt className="text-muted">Status</dt>
              <dd>
                <span
                  className="badge"
                  style={{
                    background: statusOf(selected).colour + '1A',
                    color: statusOf(selected).colour,
                    border: `1px solid ${statusOf(selected).colour}`,
                  }}
                >
                  {statusOf(selected).label}
                </span>
              </dd>
              {selected.case_id ? (
                <>
                  <dt className="text-muted">Case</dt>
                  <dd>
                    <Link className="text-accent underline decoration-dotted" to={`/cases/${selected.case_id}`}>
                      {selected.case_no || 'Open case'}
                    </Link>
                  </dd>
                </>
              ) : null}
            </dl>
          ) : (
            <p className="text-sm text-muted">
              Click a plot on the globe, or choose one from the table below, to see its survey
              number, ULPIN, area and case.
            </p>
          )}
        </Panel>
      </div>

      {/* ------------------------------------------- text equivalent (§4) */}
      <Panel title="Parcel register" right={`${shown.features.length} shown`}>
        <p className="mb-3 text-xs text-muted">
          The text equivalent of the globe. A WebGL map cannot be read by a screen reader, so
          every parcel it draws is listed here with the same attributes.
        </p>
        {shown.features.length === 0 ? (
          <Empty>No parcels match this filter.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="gov dense">
              <caption className="sr-only">
                Parcels in your jurisdiction with survey number, village, area, status and case
              </caption>
              <thead>
                <tr>
                  <th scope="col">Survey no.</th>
                  <th scope="col">ULPIN</th>
                  <th scope="col">Village</th>
                  <th scope="col">Project</th>
                  <th scope="col" className="num">
                    Area (ha)
                  </th>
                  <th scope="col">Status</th>
                  <th scope="col">Locate</th>
                </tr>
              </thead>
              <tbody>
                {shown.features.map((f, i) => {
                  const p = f.properties ?? {}
                  const s = statusOf(p)
                  return (
                    <tr key={String(p.id ?? i)}>
                      <td className="whitespace-nowrap">
                        {p.case_id ? (
                          <Link className="text-accent underline decoration-dotted" to={`/cases/${p.case_id}`}>
                            {p.survey_no || '—'}
                          </Link>
                        ) : (
                          p.survey_no || '—'
                        )}
                      </td>
                      <td className="font-mono text-xs">{p.ulpin || '—'}</td>
                      <td>{p.village || '—'}</td>
                      <td className="max-w-[14rem] truncate" title={p.project_name}>
                        {p.project_name || '—'}
                      </td>
                      <td className="num">{num(p.area_ha)?.toFixed(4) ?? '—'}</td>
                      <td>
                        <span className="flex items-center gap-1.5">
                          <span
                            aria-hidden="true"
                            className="inline-block h-2.5 w-2.5 rounded-sm"
                            style={{ background: s.colour }}
                          />
                          {s.label}
                        </span>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn-ghost btn-sm"
                          onClick={() => void flyToFeature(f)}
                        >
                          Show on globe
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}

function Row({ label, value, mono }: { label: string; value?: unknown; mono?: boolean }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className={mono ? 'font-mono text-xs' : ''}>{(value as string) || '—'}</dd>
    </>
  )
}
