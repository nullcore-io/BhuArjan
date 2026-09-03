/**
 * Clock health — statutory clocks by state.
 *
 * The status hues are fixed by design.md §1 and by meaning (red = breached),
 * and measured they collide under colour-vision deficiency: lapsed↔running is
 * ΔE 2.8 under deuteranopia — precisely the red/green case §4 forbids relying
 * on. They are therefore never the only signal here: every bar carries a
 * texture, an axis label, and a legend entry naming the state in words.
 */
import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS, statusFill, statusStyle } from '../../theme/charts'
import ChartLegend, { type LegendItem } from './ChartLegend'
import ChartPatterns from './ChartPatterns'
import Figure from './Figure'

export interface ClockRow {
  key: string
  status: string
  count: number
}

export default function ClockHealthChart({
  data,
  right,
  caption,
}: {
  data: ClockRow[]
  right?: React.ReactNode
  caption?: React.ReactNode
}) {
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const toggle = (k: string) =>
    setHidden((prev) => {
      const next = new Set(prev)
      next.has(k) ? next.delete(k) : next.add(k)
      return next
    })

  const items: LegendItem[] = data.map((r) => ({
    key: r.key,
    label: statusStyle(r.key).label,
    colour: statusStyle(r.key).colour,
    statusKey: r.key,
  }))
  const shown = data.filter((r) => !hidden.has(r.key))

  return (
    <Figure
      title="Clock health"
      right={right}
      caption={caption}
      tableLabel="Clock counts"
      rows={data}
      columns={[
        { key: 'status', label: 'Status', render: (r) => statusStyle(r.key).label },
        { key: 'count', label: 'Clocks', numeric: true },
      ]}
    >
      <>
        <ChartLegend items={items} hidden={hidden} onToggle={toggle} label="Clock states" />
        {/* Sibling <svg>, not a child of the chart — Recharts drops children it
            does not recognise, which silently voided every url(#…) fill. */}
        <ChartPatterns />
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={shown} margin={{ top: 8, right: 12, left: 4, bottom: 4 }} accessibilityLayer>
            <CartesianGrid stroke={AXIS.grid} strokeDasharray="2 2" vertical={false} />
            <XAxis dataKey="status" tick={AXIS.tick} />
            <YAxis allowDecimals={false} tick={AXIS.tick} width={36} />
            <Tooltip contentStyle={AXIS.tooltip} cursor={{ fill: 'rgba(15,31,61,0.05)' }} />
            <Bar dataKey="count" name="Clocks" radius={[4, 4, 0, 0]} isAnimationActive={false}>
              {shown.map((row) => (
                <Cell
                  key={row.key}
                  fill={statusFill(row.key)}
                  stroke={statusStyle(row.key).colour}
                  strokeWidth={1}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </>
    </Figure>
  )
}
