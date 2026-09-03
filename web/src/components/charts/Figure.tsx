/**
 * A chart and its text equivalent, as one unit — Docs/design.md §4
 * ("every chart needs a table alternative … charts alone are not screen-reader
 * friendly").
 *
 * Follows the precedent already set by ParcelMap, which pairs the map with a
 * <details> parcel table. Making that the shared shape means a chart cannot be
 * added without its table: the data that feeds the marks feeds the rows.
 *
 * The <details> is collapsed by default so sighted users keep a clean dashboard,
 * but it is real DOM — screen readers and Ctrl+F reach it either way.
 */
import { useId, type ReactNode } from 'react'
import { Panel } from '../ui/Feedback'

export interface FigureColumn<Row> {
  key: string
  label: string
  /** Right-align and use tabular figures — money, areas, counts. */
  numeric?: boolean
  render?: (row: Row) => ReactNode
}

export interface FigureProps<Row> {
  title: ReactNode
  right?: ReactNode
  /** Statutory note under the chart; also the figure's caption. */
  caption?: ReactNode
  columns: FigureColumn<Row>[]
  rows: Row[]
  /** Shown instead of chart+table when there is nothing in scope. */
  empty?: ReactNode
  /** Label for the disclosure, e.g. "Clock counts". */
  tableLabel?: string
  children: ReactNode
}

export default function Figure<Row extends Record<string, any>>({
  title,
  right,
  caption,
  columns,
  rows,
  empty,
  tableLabel = 'Data table',
  children,
}: FigureProps<Row>) {
  const tableId = useId()
  const capId = useId()

  if (rows.length === 0 && empty) return <Panel title={title} right={right}>{empty}</Panel>

  return (
    <Panel title={title} right={right}>
      <figure className="m-0" aria-describedby={caption ? capId : tableId}>
        {/* Recharts' accessibilityLayer makes the plot itself arrow-key
            navigable; the table below is the non-visual equivalent. */}
        <div className="h-64">{children}</div>
        {caption ? (
          <figcaption id={capId} className="mt-1 text-xs text-muted">
            {caption}
          </figcaption>
        ) : null}
      </figure>

      <details id={tableId} className="mt-2">
        <summary className="cursor-pointer text-xs text-accent">
          {tableLabel} (text equivalent of the chart)
        </summary>
        <div className="mt-2 overflow-x-auto">
          <table className="gov">
            <caption className="sr-only">
              {typeof title === 'string' ? title : tableLabel} — text equivalent
            </caption>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.key} scope="col" className={c.numeric ? 'num' : undefined}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.key ?? row.id ?? i}>
                  {columns.map((c) => (
                    <td key={c.key} className={c.numeric ? 'num' : undefined}>
                      {c.render ? c.render(row) : (row[c.key] ?? '—')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </Panel>
  )
}
