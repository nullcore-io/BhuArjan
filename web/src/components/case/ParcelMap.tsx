/**
 * ParcelMap — Leaflet map of the case's parcels.
 * Docs/Frontend.md §2: polygons coloured by possession status, legend, click
 * shows survey no / ULPIN / area. GeoJSON from `GET /cases/{id}/parcels`
 * (Docs/APIs.md §3.6). Leaflet's stylesheet is loaded in index.html.
 *
 * The parcel table below the map is the non-visual equivalent required by
 * Docs/Frontend.md §9 ("parcel table always available") — it is not decoration.
 */
import type { FeatureCollection, GeoJsonProperties, Geometry } from 'geojson'
import L from 'leaflet'
import { useEffect, useMemo, useState } from 'react'
import { GeoJSON, MapContainer, TileLayer, useMap } from 'react-leaflet'
import { ParcelCollection, ParcelProps, num } from './caseApi'

/** Legend order matches Docs/Frontend.md §2. */
const STATUS_STYLE: Record<string, { label: string; color: string }> = {
  notified: { label: 'Notified', color: '#1F4E9C' },
  awarded: { label: 'Awarded', color: '#B9770E' },
  paid: { label: 'Paid', color: '#2E7D32' },
  possessed: { label: 'Possessed', color: '#14213D' },
  disputed: { label: 'Disputed', color: '#B3261E' },
}
const UNKNOWN = { label: 'Unknown', color: '#5B6675' }

function styleFor(status?: string | null) {
  const key = String(status ?? '').toLowerCase()
  return STATUS_STYLE[key] ?? UNKNOWN
}

const CENTRE_OF_INDIA: [number, number] = [22.9734, 78.6569]

/** The API's FeatureCollection retyped for Leaflet, which wants real GeoJSON. */
type ParcelGeoJson = FeatureCollection<Geometry, GeoJsonProperties>

function FitToParcels({ data }: { data: ParcelGeoJson | null }) {
  const map = useMap()
  useEffect(() => {
    if (!data || data.features.length === 0) return
    try {
      const bounds = L.geoJSON(data).getBounds()
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [16, 16], maxZoom: 15 })
    } catch {
      /* a malformed geometry must not blank the page */
    }
  }, [data, map])
  return null
}

export default function ParcelMap({
  data,
  loading,
  error,
}: {
  data: ParcelCollection | null | undefined
  loading?: boolean
  error?: unknown
}) {
  const [selected, setSelected] = useState<ParcelProps | null>(null)

  const features = useMemo(
    () => (data?.features ?? []).filter((f) => f && f.geometry),
    [data],
  )
  /** One object identity per data change so <GeoJSON> and fitBounds agree. */
  const geo = useMemo<ParcelGeoJson | null>(
    () =>
      features.length
        ? ({ type: 'FeatureCollection', features } as unknown as ParcelGeoJson)
        : null,
    [features],
  )
  const legend = useMemo(() => {
    const seen = new Map<string, number>()
    for (const f of data?.features ?? []) {
      const k = String(f.properties?.status ?? '').toLowerCase() || 'unknown'
      seen.set(k, (seen.get(k) ?? 0) + 1)
    }
    return Array.from(seen.entries())
  }, [data])

  const totalHa = (data?.features ?? []).reduce((a, f) => a + num(f.properties?.area_ha), 0)

  return (
    <section className="card" aria-labelledby="map-h">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="map-h" className="text-sm font-semibold uppercase tracking-wide text-muted">
          Parcels
        </h2>
        <span className="text-xs text-muted">
          {features.length} parcel{features.length === 1 ? '' : 's'} · {totalHa.toFixed(4)} ha
        </span>
      </div>

      {loading ? (
        <p className="mt-3 text-xs text-muted">Loading parcels…</p>
      ) : error ? (
        <p role="alert" className="mt-3 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
          Could not load parcels: {error instanceof Error ? error.message : 'request failed'}
        </p>
      ) : (
        <>
          <div className="mt-2 h-64 overflow-hidden rounded border border-border">
            <MapContainer
              center={CENTRE_OF_INDIA}
              zoom={5}
              scrollWheelZoom={false}
              style={{ height: '100%', width: '100%' }}
              attributionControl
            >
              <TileLayer
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              />
              {geo ? (
                <GeoJSON
                  key={`${features.length}-${String(features[0]?.id ?? '')}`}
                  data={geo}
                  style={(feature) => {
                    const props = (feature?.properties ?? {}) as ParcelProps
                    const s = styleFor(props.status)
                    return {
                      color: s.color,
                      weight: 1.5,
                      opacity: 1,
                      fillColor: s.color,
                      fillOpacity: 0.35,
                    }
                  }}
                  onEachFeature={(feature, layer) => {
                    const props = (feature?.properties ?? {}) as ParcelProps
                    const s = styleFor(props.status)
                    layer.bindTooltip(
                      `${props.survey_no ?? 'Survey no —'} · ${s.label}`,
                      { sticky: true },
                    )
                    layer.on('click', () => setSelected(props))
                  }}
                />
              ) : null}
              <FitToParcels data={geo} />
            </MapContainer>
          </div>

          <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
            {legend.map(([key, count]) => {
              const s = STATUS_STYLE[key] ?? UNKNOWN
              return (
                <li key={key} className="flex items-center gap-1">
                  <span
                    aria-hidden="true"
                    className="inline-block h-3 w-3 rounded-[2px] border border-border"
                    style={{ backgroundColor: s.color }}
                  />
                  <span className="text-muted">
                    {s.label} ({count})
                  </span>
                </li>
              )
            })}
            {legend.length === 0 ? (
              <li className="text-muted">No parcels imported for this case.</li>
            ) : null}
          </ul>

          {selected ? (
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 rounded border border-accent bg-accent/5 p-2 text-xs">
              <Pair label="Survey no" value={selected.survey_no ?? '—'} />
              <Pair label="ULPIN" value={selected.ulpin ?? '—'} mono />
              <Pair label="Area (ha)" value={selected.area_ha != null ? String(selected.area_ha) : '—'} />
              <Pair label="Status" value={styleFor(selected.status).label} />
            </dl>
          ) : null}

          {features.length ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-accent focus:outline-none focus:ring-2 focus:ring-accent">
                Parcel table (text equivalent of the map)
              </summary>
              <div className="mt-1 max-h-56 overflow-y-auto">
                <table className="gov">
                  <thead>
                    <tr>
                      <th scope="col">Survey no</th>
                      <th scope="col">ULPIN</th>
                      <th scope="col">Village</th>
                      <th scope="col">Area (ha)</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {features.map((f, i) => {
                      const p = f.properties ?? {}
                      return (
                        <tr key={String(f.id ?? i)}>
                          <td>{p.survey_no ?? '—'}</td>
                          <td className="font-mono text-xs">{p.ulpin ?? '—'}</td>
                          <td>{(p.village as string) ?? '—'}</td>
                          <td className="text-right tabular-nums">
                            {p.area_ha != null ? num(p.area_ha).toFixed(4) : '—'}
                          </td>
                          <td>{styleFor(p.status).label}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </details>
          ) : null}
        </>
      )}
    </section>
  )
}

function Pair({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className={`text-ink ${mono ? 'font-mono' : ''}`}>{value}</dd>
    </div>
  )
}
