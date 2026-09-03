/**
 * StatutoryTimeline — the statutory stages of a track, in order.
 * Docs/Frontend.md §2: "horizontal stages with dates; current stage highlighted;
 * future stages show due dates from clocks".
 *
 * Stages come from the track's rule-set order (Docs/Backend.md §5); *dates* come
 * from the ledger (actual) or from the clock that governs the stage (due).
 */
import { formatDate } from '../../lib/api'
import {
  Clock,
  LedgerEvent,
  StageStep,
  TERMINAL_STAGES,
  clockLevel,
  daysBetween,
  stagesForTrack,
  titleize,
  today,
} from './caseApi'

type Position = 'done' | 'current' | 'future'

interface Row {
  step: StageStep
  position: Position
  /** Legal date the stage was entered (from the ledger). */
  actual: string | null
  /** Statutory due date for the stage, from its governing clock. */
  due: string | null
  clock: Clock | null
}

function buildRows(
  track: string | null | undefined,
  stage: string | null | undefined,
  events: LedgerEvent[],
  clocks: Clock[],
): Row[] {
  const steps = [...stagesForTrack(track)]
  const current = (stage ?? '').toUpperCase()
  const terminal = TERMINAL_STAGES[current]
  if (terminal && !steps.some((s) => s.stage === current)) steps.push(terminal)

  const clockById = new Map(clocks.map((c) => [c.clock_id, c]))
  const firstOccurrence = new Map<string, string>()
  // Ledger arrives newest-first; walking it in reverse leaves the earliest date.
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (e?.type && e.occurred_at && !firstOccurrence.has(e.type)) {
      firstOccurrence.set(e.type, e.occurred_at)
    }
  }

  let currentIndex = steps.findIndex((s) => s.stage === current)
  if (currentIndex < 0) {
    // Unknown stage label: fall back to the last stage that actually happened.
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i].entry.some((t) => firstOccurrence.has(t))) {
        currentIndex = i
        break
      }
    }
  }

  return steps.map((step, i): Row => {
    const actual =
      step.entry.map((t) => firstOccurrence.get(t)).find((d): d is string => Boolean(d)) ?? null
    const clock = step.clockId ? (clockById.get(step.clockId) ?? null) : null
    const position: Position =
      currentIndex >= 0 && i === currentIndex ? 'current' : i < currentIndex ? 'done' : 'future'
    return { step, position, actual, due: clock?.due_date ?? null, clock }
  })
}

export default function StatutoryTimeline({
  track,
  stage,
  events,
  clocks,
}: {
  track?: string | null
  stage?: string | null
  events: LedgerEvent[]
  clocks: Clock[]
}) {
  const rows = buildRows(track, stage, events, clocks)

  return (
    <section className="card" aria-labelledby="timeline-h">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="timeline-h" className="text-sm font-semibold uppercase tracking-wide text-muted">
          Statutory timeline
        </h2>
        <span className="text-xs text-muted">{titleize(track) || 'Track'}</span>
      </div>

      <ol className="mt-3 flex gap-0 overflow-x-auto pb-1" role="list">
        {rows.map((r, i) => (
          <li
            key={r.step.stage}
            className="min-w-[9.5rem] flex-1 shrink-0"
            aria-current={r.position === 'current' ? 'step' : undefined}
          >
            <div className="flex items-center">
              <span
                className={[
                  'grid h-6 w-6 shrink-0 place-items-center rounded-full border text-xs font-semibold',
                  r.position === 'done'
                    ? 'border-ok bg-ok text-white'
                    : r.position === 'current'
                      ? 'border-accent bg-accent text-white'
                      : 'border-dashed border-border bg-bg text-muted',
                ].join(' ')}
              >
                {r.position === 'done' ? '✓' : i + 1}
              </span>
              {i < rows.length - 1 ? (
                <span
                  aria-hidden="true"
                  className={`ml-1 h-px flex-1 ${
                    r.position === 'future'
                      ? 'border-t border-dashed border-border'
                      : 'bg-accent'
                  }`}
                />
              ) : null}
            </div>

            <div
              className={[
                'mt-2 mr-2 rounded border p-2',
                r.position === 'current'
                  ? 'border-accent bg-accent/5'
                  : r.position === 'done'
                    ? 'border-border bg-bg'
                    : 'border-dashed border-border bg-bg',
              ].join(' ')}
            >
              <p
                className={`text-xs font-semibold leading-tight ${
                  r.position === 'future' ? 'text-muted' : 'text-ink'
                }`}
              >
                {r.step.label}
              </p>
              {r.step.section ? (
                <p className="mt-0.5 font-mono text-xs text-muted">{r.step.section}</p>
              ) : null}
              <StageDate row={r} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

function StageDate({ row }: { row: Row }) {
  if (row.actual) {
    return (
      <p className="mt-1 text-xs text-ink">
        <span className="text-muted">on </span>
        <span className="font-semibold">{formatDate(row.actual)}</span>
      </p>
    )
  }
  if (row.due) {
    const level = row.clock ? clockLevel(row.clock) : 'ok'
    const left = daysBetween(today(), row.due)
    const overdue = left != null && left < 0
    return (
      <p className="mt-1 text-xs">
        <span className="text-muted">due </span>
        <span
          className={`font-semibold ${
            overdue || level === 'breached' || level === 'lapsed'
              ? 'text-red'
              : level === 'red' || level === 'amber'
                ? 'text-amber'
                : 'text-ink'
          }`}
        >
          {formatDate(row.due)}
        </span>
        {left != null ? (
          <span className="block text-muted">
            {left >= 0 ? `${left} days left` : `${-left} days overdue`}
          </span>
        ) : null}
      </p>
    )
  }
  return <p className="mt-1 text-xs text-muted">not reached</p>
}
