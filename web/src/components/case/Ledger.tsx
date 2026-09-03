/**
 * Ledger — the append-only event log for a case (Docs/rules.md C1).
 * Row: seq · type · occurred_at · actor · document · hash prefix.
 * Expanding a row reveals the canonical payload JSON and the chain links.
 */
import { Fragment, useState } from 'react'
import { formatDate } from '../../lib/api'
import { LedgerEvent, formatTs, hashPrefix, openDocumentInTab } from './caseApi'

function actorOf(e: LedgerEvent): string {
  return e.actor_name || e.actor || e.actor_id || '—'
}

export default function Ledger({
  events,
  loading,
  error,
  hasMore,
  loadingMore,
  onLoadMore,
}: {
  events: LedgerEvent[]
  loading?: boolean
  error?: unknown
  hasMore?: boolean
  loadingMore?: boolean
  onLoadMore?: () => void
}) {
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [docError, setDocError] = useState<string | null>(null)

  const toggle = (key: string) =>
    setOpen((s) => {
      const next = new Set(s)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  return (
    <section className="card" aria-labelledby="ledger-h">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="ledger-h" className="text-sm font-semibold uppercase tracking-wide text-muted">
          Ledger
        </h2>
        <span className="text-xs text-muted">
          {events.length} event{events.length === 1 ? '' : 's'} · append-only
        </span>
      </div>

      {docError ? (
        <p role="alert" className="mt-2 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
          {docError}
        </p>
      ) : null}

      {loading ? (
        <p className="mt-3 text-xs text-muted">Loading the ledger…</p>
      ) : error ? (
        <p role="alert" className="mt-3 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
          Could not load events: {error instanceof Error ? error.message : 'request failed'}
        </p>
      ) : events.length === 0 ? (
        <p className="mt-3 text-xs text-muted">No events recorded on this case yet.</p>
      ) : (
        <div className="mt-2 max-h-[28rem] overflow-y-auto">
          <table className="gov dense">
            <caption className="sr-only">
              Case ledger, newest first. Each row expands to its payload.
            </caption>
            <thead className="sticky top-0 z-10">
              <tr>
                <th scope="col" className="w-14">Seq</th>
                <th scope="col">Event</th>
                <th scope="col" className="w-24">Occurred</th>
                <th scope="col" className="w-32">Actor</th>
                <th scope="col" className="w-20">Doc</th>
                <th scope="col" className="w-28">Hash</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => {
                const key = e.id ?? String(e.seq)
                const expanded = open.has(key)
                return (
                  <Fragment key={key}>
                    <tr className={expanded ? 'bg-surface' : undefined}>
                      <td className="font-mono text-xs">{e.seq}</td>
                      <td>
                        <button
                          type="button"
                          className="text-left font-semibold text-accent underline-offset-2 hover:underline focus:outline-none focus:ring-2 focus:ring-accent"
                          aria-expanded={expanded}
                          aria-controls={`payload-${key}`}
                          onClick={() => toggle(key)}
                        >
                          <span aria-hidden="true" className="mr-1 inline-block w-2 font-mono">
                            {expanded ? '−' : '+'}
                          </span>
                          {e.type}
                        </button>
                      </td>
                      <td>{formatDate(e.occurred_at)}</td>
                      <td className="truncate text-xs" title={actorOf(e)}>
                        {actorOf(e)}
                      </td>
                      <td>
                        {e.document_id ? (
                          <button
                            type="button"
                            className="text-accent underline-offset-2 hover:underline focus:outline-none focus:ring-2 focus:ring-accent"
                            onClick={() => {
                              setDocError(null)
                              openDocumentInTab(e.document_id as string).catch((err) =>
                                setDocError(
                                  err instanceof Error ? err.message : 'Could not open document',
                                ),
                              )
                            }}
                          >
                            Open
                          </button>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                      <td className="font-mono text-xs text-muted" title={e.hash ?? ''}>
                        {hashPrefix(e.hash, 10)}
                      </td>
                    </tr>
                    {expanded ? (
                      <tr>
                        <td colSpan={6} className="bg-surface align-top">
                          <div id={`payload-${key}`} className="py-2">
                            <dl className="mb-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
                              <Meta label="Recorded at" value={formatTs(e.recorded_at)} />
                              <Meta label="Event id" value={e.id ?? '—'} mono />
                              <Meta label="prev_hash" value={hashPrefix(e.prev_hash, 16)} mono />
                              <Meta label="hash" value={hashPrefix(e.hash, 16)} mono />
                            </dl>
                            <pre className="max-h-64 overflow-auto rounded border border-border bg-bg p-2 font-mono text-xs leading-snug text-ink">
                              {JSON.stringify(e.payload ?? {}, null, 2)}
                            </pre>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {hasMore && onLoadMore ? (
        <button type="button" className="btn mt-2 text-xs" onClick={onLoadMore} disabled={loadingMore}>
          {loadingMore ? 'Loading…' : 'Load older events'}
        </button>
      ) : null}
    </section>
  )
}

function Meta({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className={`truncate text-ink ${mono ? 'font-mono' : ''}`} title={value}>
        {value}
      </dd>
    </div>
  )
}
