/**
 * Stage funnel — cases by current statutory stage.
 *
 * One series, so no legend: the panel title names it (data-viz guidance —
 * a legend box for a single series is noise). Identity is carried by the
 * x-axis stage labels, which are statutory names, not invented categories.
 */
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { AXIS, SERIES } from '../../theme/charts'
import Figure from './Figure'

export interface FunnelRow {
  stage: string
  count: number
}

export default function StageFunnelChart({ funnel }: { funnel: FunnelRow[] }) {
  return (
    <Figure
      title="Stage funnel"
      right="cases by current stage"
      tableLabel="Cases by stage"
      rows={funnel}
      columns={[
        { key: 'stage', label: 'Stage' },
        { key: 'count', label: 'Cases', numeric: true },
      ]}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={funnel} margin={{ top: 8, right: 12, left: 4, bottom: 4 }} accessibilityLayer>
          <CartesianGrid stroke={AXIS.grid} strokeDasharray="2 2" vertical={false} />
          <XAxis
            dataKey="stage"
            tick={AXIS.tick}
            interval={0}
            angle={-20}
            textAnchor="end"
            height={54}
          />
          <YAxis allowDecimals={false} tick={AXIS.tick} width={36} />
          <Tooltip contentStyle={AXIS.tooltip} cursor={{ fill: 'rgba(31,78,156,0.06)' }} />
          <Bar dataKey="count" name="Cases" fill={SERIES.assessed} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </Figure>
  )
}
