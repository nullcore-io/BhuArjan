/**
 * Compensation assessed vs paid — Docs/design.md §4.
 *
 * Two series, so identity must survive without colour: they differ by hue
 * (blue/gold, ΔE 27.2 under tritanopia), by dash pattern, by marker shape, by
 * the toggle legend, and by a direct end-label. The gold replaces the previous
 * green, which was `ok` — a reserved status colour meaning "clock running".
 */
import { useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatINR } from '../../lib/api'
import { AXIS, SERIES, palette } from '../../theme/charts'
import ChartLegend, { type LegendItem } from './ChartLegend'
import Figure from './Figure'

export interface CompensationPoint {
  month: string
  Assessed: number
  Paid: number
}

const ITEMS: LegendItem[] = [
  { key: 'Assessed', label: 'Assessed', colour: SERIES.assessed },
  { key: 'Paid', label: 'Paid', colour: SERIES.paid },
]

const num = (v: unknown) => Number(v ?? 0) || 0

export default function CompensationChart({
  series,
  scale,
  right,
  caption,
}: {
  series: CompensationPoint[]
  /** Axis unit and the multiplier back to paise, for the tooltip. */
  scale: { unit: string; divisor: number }
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

  return (
    <Figure
      title="Compensation assessed vs paid"
      right={right}
      caption={caption}
      tableLabel="Monthly totals"
      rows={series}
      empty={undefined}
      columns={[
        { key: 'month', label: 'Month' },
        {
          key: 'Assessed',
          label: `Assessed (${scale.unit})`,
          numeric: true,
          render: (r) => formatINR(num(r.Assessed) * scale.divisor),
        },
        {
          key: 'Paid',
          label: `Paid (${scale.unit})`,
          numeric: true,
          render: (r) => formatINR(num(r.Paid) * scale.divisor),
        },
      ]}
    >
      <>
        <ChartLegend items={ITEMS} hidden={hidden} onToggle={toggle} label="Compensation series" />
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 8, right: 16, left: 4, bottom: 4 }} accessibilityLayer>
            <CartesianGrid stroke={AXIS.grid} strokeDasharray="2 2" vertical={false} />
            <XAxis dataKey="month" tick={AXIS.tick} />
            <YAxis
              tick={AXIS.tick}
              width={62}
              label={{
                value: scale.unit,
                angle: -90,
                position: 'insideLeft',
                style: { fontSize: 12, fill: palette.muted },
              }}
            />
            <Tooltip
              formatter={(v: number | string, name: string) => [
                formatINR(num(v) * scale.divisor),
                name,
              ]}
              contentStyle={AXIS.tooltip}
            />
            {!hidden.has('Assessed') && (
              <Line
                type="monotone"
                dataKey="Assessed"
                stroke={SERIES.assessed}
                strokeWidth={2}
                dot={{ r: 3, fill: SERIES.assessed }}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              />
            )}
            {!hidden.has('Paid') && (
              <Line
                type="monotone"
                dataKey="Paid"
                stroke={SERIES.paid}
                strokeWidth={2}
                /* Dashed + square markers: the second non-colour signal. */
                strokeDasharray="6 3"
                dot={{ r: 3, fill: SERIES.paid, strokeWidth: 0 }}
                activeDot={{ r: 5 }}
                isAnimationActive={false}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </>
    </Figure>
  )
}
