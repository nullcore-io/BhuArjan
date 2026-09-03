/**
 * Basemaps for the globe view.
 *
 * All three are key-less on purpose. Google Earth's own imagery is only
 * available through the paid Google Maps Platform and its terms forbid the
 * kind of redistribution a government system of record would need, so this uses
 * open sources that carry no key, no quota and no per-seat licence.
 *
 * `plain` exists for the demo floor: it draws no external tile at all, so the
 * parcels still render as a 3D globe when the venue network is down — which has
 * already happened once on this machine.
 */
import type { StyleSpecification } from 'maplibre-gl'
import { palette } from '../theme/palette.mjs'

export type BasemapId = 'satellite' | 'terrain' | 'plain'

/** Free elevation tiles (Terrarium encoding) — drives the 3D relief. */
export const TERRAIN_SOURCE = {
  type: 'raster-dem' as const,
  tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
  encoding: 'terrarium' as const,
  tileSize: 256,
  maxzoom: 13,
  attribution: 'Elevation: Mapzen / AWS Open Data',
}

const SKY = {
  'sky-color': '#7AB7E8',
  'sky-horizon-blend': 0.6,
  'horizon-color': '#D6E8F5',
  'horizon-fog-blend': 0.6,
  'fog-color': '#CFE0EC',
  'fog-ground-blend': 0.1,
}

function base(layers: StyleSpecification['layers'], sources: StyleSpecification['sources']) {
  return {
    version: 8 as const,
    // The globe projection is what gives the Google-Earth feel: the map is a
    // sphere you orbit, not a flat sheet you pan.
    projection: { type: 'globe' as const },
    sky: SKY,
    light: { anchor: 'map' as const, position: [1.5, 90, 80] as [number, number, number] },
    sources,
    layers,
  } as StyleSpecification
}

export function styleFor(id: BasemapId): StyleSpecification {
  if (id === 'satellite') {
    return base(
      [
        { id: 'bg', type: 'background', paint: { 'background-color': '#0B1A2B' } },
        { id: 'imagery', type: 'raster', source: 'imagery' },
      ],
      {
        imagery: {
          type: 'raster',
          tiles: [
            'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          ],
          tileSize: 256,
          maxzoom: 19,
          attribution:
            'Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community',
        },
        terrain: TERRAIN_SOURCE,
      },
    )
  }

  if (id === 'terrain') {
    return base(
      [
        { id: 'bg', type: 'background', paint: { 'background-color': '#EAE6DC' } },
        { id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-saturation': -0.35 } },
      ],
      {
        osm: {
          type: 'raster',
          tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
          tileSize: 256,
          maxzoom: 19,
          attribution: '© OpenStreetMap contributors',
        },
        terrain: TERRAIN_SOURCE,
      },
    )
  }

  // No network at all — a plain sphere the parcels can still sit on.
  return base(
    [{ id: 'bg', type: 'background', paint: { 'background-color': palette.surface2 } }],
    {},
  )
}

export const BASEMAPS: { id: BasemapId; label: string; note: string }[] = [
  { id: 'satellite', label: 'Satellite', note: 'Esri World Imagery' },
  { id: 'terrain', label: 'Street', note: 'OpenStreetMap' },
  { id: 'plain', label: 'Offline', note: 'no external tiles' },
]

/** Possession status → colour. Mirrors the case-page parcel legend. */
export const PARCEL_STATUS: Record<string, { label: string; colour: string }> = {
  notified: { label: 'Notified', colour: palette.accent },
  awarded: { label: 'Awarded', colour: palette.accent2 },
  paid: { label: 'Paid', colour: palette.ok },
  possessed: { label: 'Possessed', colour: palette.ink },
  disputed: { label: 'Disputed', colour: palette.red },
}
export const PARCEL_UNKNOWN = { label: 'Unknown', colour: palette.muted }
