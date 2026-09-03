/**
 * SVG <pattern> fills for statutory clock statuses — Docs/design.md §4
 * ("never red/green-only … pair each colour with a text label or pattern").
 *
 * The status hues cannot be changed (red = breached is both a design.md §1
 * token and a legal meaning), and measured they collide badly under colour-
 * vision deficiency — lapsed↔running is ΔE 2.8 under deuteranopia. Texture is
 * therefore the encoding that actually carries the difference: it survives
 * CVD, greyscale printing and forced-colours mode.
 *
 * Rendered as its own zero-size <svg> BESIDE the chart, not inside it:
 * Recharts silently drops children it does not recognise, so a <defs> passed to
 * <BarChart> never reaches the rendered SVG and every url(#…) fill resolves to
 * nothing. SVG ids are document-scoped, so defining them in a sibling <svg>
 * works and is the reliable placement.
 */
import { CLOCK_STATUS } from '../../theme/charts'

const S = 6 // pattern tile, px

export default function ChartPatterns() {
  // Light strokes over a full-strength ground: a textured bar must weigh the
  // same as a solid one, or texture reads as "less" rather than "different".
  const stroke = () => ({
    stroke: '#FFFFFF',
    strokeOpacity: 0.75,
    strokeWidth: 1.8,
    shapeRendering: 'crispEdges' as const,
  })
  return (
    <svg
      width={0}
      height={0}
      aria-hidden="true"
      focusable="false"
      style={{ position: 'absolute' }}
    >
      <defs>
        {Object.entries(CLOCK_STATUS).map(([key, s]) => {
          if (!s.pattern) return null
          const id = `pat-${s.pattern}`
          return (
            <pattern key={key} id={id} width={S} height={S} patternUnits="userSpaceOnUse">
            {/* A tint ground keeps the bar readable at a glance; the strokes
                carry the identity. */}
              <rect width={S} height={S} fill={s.colour} />
              {s.pattern === 'diag-right' && <path d={`M0,${S} l${S},-${S}`} {...stroke()} />}
              {s.pattern === 'diag-left' && <path d={`M0,0 l${S},${S}`} {...stroke()} />}
              {s.pattern === 'horizontal' && <path d={`M0,${S / 2} H${S}`} {...stroke()} />}
              {s.pattern === 'grid' && (
                <path d={`M0,${S / 2} H${S} M${S / 2},0 V${S}`} {...stroke()} />
              )}
              {s.pattern === 'dots' && (
                <circle cx={S / 2} cy={S / 2} r={1.5} fill="#FFFFFF" fillOpacity={0.8} />
              )}
            </pattern>
          )
        })}
      </defs>
    </svg>
  )
}

/** The same texture as a small inline swatch, for legends and table keys. */
export function StatusSwatch({ statusKey }: { statusKey: string }) {
  const s = CLOCK_STATUS[statusKey]
  if (!s) return null
  const id = `sw-${statusKey}`
  return (
    <svg width={12} height={12} aria-hidden="true" className="shrink-0">
      <defs>
        <pattern id={id} width={S} height={S} patternUnits="userSpaceOnUse">
          <rect width={S} height={S} fill={s.colour} />
          {s.pattern === 'diag-right' && (
            <path d={`M0,${S} l${S},-${S}`} stroke="#FFFFFF" strokeOpacity={0.75} strokeWidth={1.8} />
          )}
          {s.pattern === 'diag-left' && (
            <path d={`M0,0 l${S},${S}`} stroke="#FFFFFF" strokeOpacity={0.75} strokeWidth={1.8} />
          )}
          {s.pattern === 'horizontal' && (
            <path d={`M0,${S / 2} H${S}`} stroke="#FFFFFF" strokeOpacity={0.75} strokeWidth={1.8} />
          )}
          {s.pattern === 'grid' && (
            <path d={`M0,${S / 2} H${S} M${S / 2},0 V${S}`} stroke="#FFFFFF" strokeOpacity={0.75} strokeWidth={1.8} />
          )}
          {s.pattern === 'dots' && <circle cx={S / 2} cy={S / 2} r={1.4} fill={s.colour} />}
        </pattern>
      </defs>
      <rect
        width={12}
        height={12}
        rx={2}
        fill={s.pattern ? `url(#${id})` : s.colour}
        stroke={s.colour}
      />
    </svg>
  )
}
