/**
 * Keyboard-operable chart legend — Docs/design.md §4 ("legends stay visible …
 * legend items are clickable to toggle series visibility").
 *
 * Recharts' built-in <Legend> renders <li> elements: clickable with a mouse,
 * unreachable by keyboard. Since §4 also requires keyboard operability, the
 * toggle has to be a real <button> with aria-pressed, which is what this is.
 *
 * Rendered outside the <svg>, immediately above the plot, so it is never below
 * a scroll fold.
 */
import { StatusSwatch } from './ChartPatterns'

export interface LegendItem {
  key: string
  label: string
  colour: string
  /** When set, the swatch shows that status's texture instead of a flat chip. */
  statusKey?: string
}

export default function ChartLegend({
  items,
  hidden,
  onToggle,
  label = 'Chart series',
}: {
  items: LegendItem[]
  hidden: Set<string>
  onToggle: (key: string) => void
  label?: string
}) {
  return (
    <ul
      className="mb-1 flex flex-wrap items-center gap-x-3 gap-y-1 pl-0"
      aria-label={label}
      role="group"
    >
      {items.map((it) => {
        const off = hidden.has(it.key)
        return (
          <li key={it.key} className="list-none">
            <button
              type="button"
              onClick={() => onToggle(it.key)}
              aria-pressed={!off}
              title={off ? `Show ${it.label}` : `Hide ${it.label}`}
              className={`flex items-center gap-1.5 rounded px-1 py-0.5 text-xs transition-opacity hover:bg-surface2 ${
                off ? 'opacity-45' : ''
              }`}
            >
              {it.statusKey ? (
                <StatusSwatch statusKey={it.statusKey} />
              ) : (
                <span
                  aria-hidden="true"
                  className="inline-block h-3 w-3 shrink-0 rounded-sm"
                  style={{ background: it.colour }}
                />
              )}
              <span className={off ? 'line-through' : ''}>{it.label}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
