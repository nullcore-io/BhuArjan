/**
 * 3D globe of every parcel in the signed-in officer's jurisdiction.
 *
 * MapLibre GL with `projection: globe` — the map is a sphere you orbit rather
 * than a flat sheet you pan, which is the Google-Earth reading the brief asked
 * for. Parcels are extruded so a plot reads as a block of land with height,
 * not a flat outline.
 *
 * A WebGL canvas is opaque to assistive technology, so this component is never
 * the only way to read the data — MapPage renders the same features as a table
 * beside it (Docs/design.md §4, and the precedent set by ParcelMap).
 */
import {
  LngLatBounds,
  Map as MlMap,
  NavigationControl,
  ScaleControl,
  type GeoJSONSource,
} from 'maplibre-gl'
import { useEffect, useRef } from 'react'
import {
  PARCEL_STATUS,
  PARCEL_UNKNOWN,
  TERRAIN_SOURCE,
  styleFor,
  type BasemapId,
} from '../../lib/mapStyles'

const SRC = 'parcels'
const PT_SRC = 'parcel-centres'
const FIT_MS = 2600 // initial flight from orbit down to the parcels
const FLY_MS = 2200 // table row -> that plot
const INDIA: [number, number] = [78.6569, 22.9734]

/** MapLibre `match` expression: status property -> fill colour. */
function statusColourExpression(): any {
  const stops: any[] = ['match', ['downcase', ['coalesce', ['get', 'status'], '']]]
  for (const [key, v] of Object.entries(PARCEL_STATUS)) stops.push(key, v.colour)
  stops.push(PARCEL_UNKNOWN.colour)
  return stops
}

const FILL_PAINT = {
  'fill-extrusion-color': statusColourExpression(),
  // Height is presentational — it makes a plot read as a block of land. It is
  // NOT a data encoding; area in hectares lives in the table.
  'fill-extrusion-height': 120,
  'fill-extrusion-base': 0,
  'fill-extrusion-opacity': 0.78,
} as any

const OUTLINE_PAINT = {
  'line-color': '#FFFFFF',
  'line-width': 1.2,
  'line-opacity': 0.9,
} as any

/**
 * A 3 ha plot is sub-pixel when the view spans two districts, so the parcels
 * were invisible from altitude. These locator dots carry the same status colour
 * and fade out exactly as the extruded footprints become legible.
 *
 * They ride their OWN point source, not the parcel polygons: a circle layer
 * draws one circle per vertex, so a rectangular plot came out as four dots at
 * its corners and a click landed on a corner rather than the parcel.
 */
const POINT_PAINT = {
  'circle-color': statusColourExpression(),
  'circle-stroke-color': '#FFFFFF',
  'circle-stroke-width': 1.5,
  'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 4, 10, 7, 13, 10],
  'circle-opacity': ['interpolate', ['linear'], ['zoom'], 12.5, 0.95, 14, 0],
  'circle-stroke-opacity': ['interpolate', ['linear'], ['zoom'], 12.5, 1, 14, 0],
} as any

export interface GlobeMapProps {
  data: GeoJSON.FeatureCollection | null
  basemap: BasemapId
  /** Slow orbit — the "spinning globe" idle state. */
  spinning: boolean
  terrain3d: boolean
  onSelect: (props: Record<string, any> | null) => void
  /**
   * Fired on the first real interaction. The orbit has to stop the moment the
   * user reaches for the map: a parcel that is sliding under the cursor cannot
   * be clicked, because the feature has moved on by the time the click resolves.
   */
  onUserInteract?: () => void
  /** Bumped by the parent to fly to a feature chosen in the table. */
  flyTo?: { lng: number; lat: number; key: number } | null
}

export default function GlobeMap({
  data,
  basemap,
  spinning,
  terrain3d,
  onSelect,
  onUserInteract,
  flyTo,
}: GlobeMapProps) {
  const holder = useRef<HTMLDivElement>(null)
  const map = useRef<MlMap | null>(null)
  const spinRef = useRef(spinning)
  spinRef.current = spinning
  // A programmatic camera move (fitBounds / flyTo) is an animation, and a single
  // setBearing mid-flight cancels it — which is why the globe never reached the
  // parcels. Waiting on `moveend` raced with the style's own initial move, so
  // the orbit is held off by a deadline instead: deterministic, no listener.
  const spinHeldUntil = useRef(0)
  // Which basemap the live map is actually showing. A plain "have I mounted"
  // boolean survives StrictMode's remount and fires setStyle() on the freshly
  // built map, rebuilding the style and dropping the parcel layers.
  const appliedBasemap = useRef<BasemapId | null>(null)
  const interactRef = useRef(onUserInteract)
  interactRef.current = onUserInteract
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  /* -------------------------------------------------------------- create */
  useEffect(() => {
    if (!holder.current || map.current) return
    const m = new MlMap({
      container: holder.current,
      style: styleFor(basemap),
      center: INDIA,
      zoom: 3.2,
      pitch: 45,
      bearing: 0,
      attributionControl: { compact: true },
    })
    map.current = m
    appliedBasemap.current = basemap
    // Dev-only handle so e2e can assert what the GPU actually drew (one dot per
    // parcel, a click selecting the right one). Stripped from production builds.
    if (import.meta.env.DEV) (window as any).__bhuarjanMap = m
    m.addControl(new NavigationControl({ visualizePitch: true }), 'top-right')
    m.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')

    // Keyboard users must be able to reach and drive the canvas.
    const canvas = m.getCanvas()
    canvas.setAttribute('tabindex', '0')
    canvas.setAttribute('role', 'application')
    canvas.setAttribute(
      'aria-label',
      'Interactive 3D globe of acquisition parcels. Arrow keys pan, plus and minus zoom. The parcel table beside the map carries the same information.',
    )

    const selectRef = onSelectRef
    for (const layer of ['parcel-fill', 'parcel-point']) {
      m.on('click', layer, (e) => {
        const f = e.features?.[0]
        selectRef.current(f ? { ...f.properties } : null)
      })
      m.on('mouseenter', layer, () => {
        m.getCanvas().style.cursor = 'pointer'
      })
      m.on('mouseleave', layer, () => {
        m.getCanvas().style.cursor = ''
      })
    }

    // Any deliberate input stands the orbit down for good.
    const stand_down = () => interactRef.current?.()
    m.on('mousedown', stand_down)
    m.on('touchstart', stand_down)
    m.on('wheel', stand_down)

    return () => {
      m.remove()
      map.current = null
    }
    // basemap deliberately omitted — style swaps are handled in their own effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /* ---------------------------------------- add/refresh parcels + terrain */
  useEffect(() => {
    const m = map.current
    if (!m) return

    const paint = () => {
      if (!m.getSource(SRC)) {
        m.addSource(SRC, { type: 'geojson', data: data ?? emptyFC() })
      } else {
        ;(m.getSource(SRC) as GeoJSONSource).setData(data ?? emptyFC())
      }
      if (!m.getSource(PT_SRC)) {
        m.addSource(PT_SRC, { type: 'geojson', data: centresOf(data) })
      } else {
        ;(m.getSource(PT_SRC) as GeoJSONSource).setData(centresOf(data))
      }

      if (!m.getLayer('parcel-fill')) addParcelLayers(m)

      applyTerrain(m, terrain3d)
      if (fitToData(m, data)) spinHeldUntil.current = performance.now() + FIT_MS + 400
    }

    if (m.isStyleLoaded()) paint()
    else m.once('load', paint)
  }, [data, terrain3d])

  /* --------------------------------------------------------- basemap swap */
  useEffect(() => {
    const m = map.current
    if (!m) return
    if (appliedBasemap.current === basemap) return
    appliedBasemap.current = basemap
    m.setStyle(styleFor(basemap), { diff: false })
    // A style swap drops every source and layer, so ours are re-added once the
    // new style settles.
    m.once('styledata', () => {
      if (!m.getSource(SRC)) {
        m.addSource(SRC, { type: 'geojson', data: data ?? emptyFC() })
        m.addSource(PT_SRC, { type: 'geojson', data: centresOf(data) })
        addParcelLayers(m)
      }
      applyTerrain(m, terrain3d)
      if (fitToData(m, data)) spinHeldUntil.current = performance.now() + FIT_MS + 400
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [basemap])

  /* ----------------------------------------------------------------- spin */
  useEffect(() => {
    const m = map.current
    if (!m) return
    let raf = 0
    let last = performance.now()
    const tick = (now: number) => {
      const dt = now - last
      last = now
      // Never fight the user: an in-progress drag or zoom pauses the orbit.
      if (spinRef.current && now >= spinHeldUntil.current && !m.isMoving()) {
        m.setBearing(m.getBearing() + (dt / 1000) * 6) // ~6°/s
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  /* ---------------------------------------------------------------- flyTo */
  useEffect(() => {
    const m = map.current
    if (!m || !flyTo) return
    spinHeldUntil.current = performance.now() + FLY_MS + 400
    m.flyTo({
      center: [flyTo.lng, flyTo.lat],
      zoom: 15,
      pitch: 60,
      duration: FLY_MS,
      essential: true,
    })
  }, [flyTo])

  return <div ref={holder} className="h-full w-full" />
}

/* -------------------------------------------------------------- helpers */

function emptyFC(): GeoJSON.FeatureCollection {
  return { type: 'FeatureCollection', features: [] }
}

function addParcelLayers(m: MlMap) {
  m.addLayer({ id: 'parcel-fill', type: 'fill-extrusion', source: SRC, paint: FILL_PAINT })
  m.addLayer({ id: 'parcel-outline', type: 'line', source: SRC, paint: OUTLINE_PAINT })
  m.addLayer({ id: 'parcel-point', type: 'circle', source: PT_SRC, paint: POINT_PAINT })
}

/** One Point per parcel, at its centroid, carrying the parcel's properties. */
function centresOf(data: GeoJSON.FeatureCollection | null): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = []
  for (const f of data?.features ?? []) {
    const c = featureCentre(f)
    if (!c) continue
    features.push({
      type: 'Feature',
      properties: { ...(f.properties ?? {}) },
      geometry: { type: 'Point', coordinates: [c.lng, c.lat] },
    })
  }
  return { type: 'FeatureCollection', features }
}

function applyTerrain(m: MlMap, on: boolean) {
  if (on) {
    if (!m.getSource('terrain')) m.addSource('terrain', TERRAIN_SOURCE as any)
    m.setTerrain({ source: 'terrain', exaggeration: 1.3 })
  } else {
    m.setTerrain(null)
  }
}

/** Frame the parcels without zooming past useful detail. */
function fitToData(m: MlMap, data: GeoJSON.FeatureCollection | null): boolean {
  if (!data?.features?.length) return false
  const b = new LngLatBounds()
  let any = false
  for (const f of data.features) {
    eachCoord(f.geometry as any, ([lng, lat]) => {
      if (Number.isFinite(lng) && Number.isFinite(lat)) {
        b.extend([lng, lat])
        any = true
      }
    })
  }
  if (any) m.fitBounds(b, { padding: 80, maxZoom: 14, pitch: 50, duration: FIT_MS })
  return any
}

function eachCoord(geom: any, fn: (c: [number, number]) => void) {
  if (!geom) return
  if (geom.type === 'GeometryCollection') {
    geom.geometries?.forEach((g: any) => eachCoord(g, fn))
    return
  }
  const walk = (c: any) => {
    if (typeof c?.[0] === 'number') fn(c as [number, number])
    else if (Array.isArray(c)) c.forEach(walk)
  }
  walk(geom.coordinates)
}

/** Centroid of a feature, for the table's "fly here" action. */
export function featureCentre(f: GeoJSON.Feature): { lng: number; lat: number } | null {
  let sx = 0
  let sy = 0
  let n = 0
  eachCoord(f.geometry as any, ([lng, lat]) => {
    sx += lng
    sy += lat
    n++
  })
  return n ? { lng: sx / n, lat: sy / n } : null
}
