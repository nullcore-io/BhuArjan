/**
 * AdminIntegrations (/admin/integrations) — Docs/Frontend.md §8, Docs/APIs.md §3.12/§4.
 *
 *   GET  /admin/integrations            → adapter status, read off the live registry
 *   POST /admin/integrations/{name}/test → run that adapter's self-check
 *
 * The honesty screen. Docs/APIs.md §4 is explicit: `GET /admin/integrations` shows
 * `mock` vs `live` truthfully — *"say so on stage"*. So the badge on every card is
 * whatever the adapter object reports, never a hard-coded label, and a `mock` badge
 * is drawn in amber and spelled out in words rather than buried in small print.
 *
 * A failing self-check is a result, not an error: the server answers `200` with
 * `ok: false`, and this screen prints the detail. Showing that state is the point of
 * the screen — a red card that says why is worth more than a green one that lies.
 */
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../lib/api'
import { errorText, listOf, titleize } from '../../components/ui/format'
import { formatTs } from '../../components/case/caseApi'

/** Roles the server lets fire a self-check — api/app/api/v1/admin.py. */
const TEST_ROLES = ['MINISTRY', 'STATE_REVENUE', 'ADMIN', 'COLLECTOR']

interface LastTest {
  at?: string | null
  ok?: boolean | null
  detail?: string | null
}

interface Adapter {
  name?: string | null
  title?: string | null
  mode?: string | null
  interface?: string | null
  real_target?: string | null
  mock_behaviour?: string | null
  deferred?: unknown
  last_test?: LastTest | null
}

/** `{ok, detail, name, mode, at, ...adapter-specific fields}`. */
interface TestResult extends LastTest {
  name?: string | null
  mode?: string | null
  [k: string]: unknown
}

const RESULT_META = new Set(['ok', 'detail', 'name', 'mode', 'at'])

export default function AdminIntegrations() {
  const listQ = useQuery({
    queryKey: ['admin', 'integrations'],
    queryFn: () => api<unknown>('/admin/integrations'),
  })
  const meQ = useQuery<{ roles?: string[] }>({ queryKey: ['me'], queryFn: () => api('/auth/me') })
  const roles = meQ.data?.roles ?? []
  const mayTest = TEST_ROLES.some((r) => roles.includes(r))

  const items = listOf<Adapter>(listQ.data, 'integrations', 'adapters')
  const envelope = (listQ.data ?? {}) as Record<string, unknown>
  const note = typeof envelope.note === 'string' ? envelope.note : null
  const liveCount = Number.isFinite(Number(envelope.live_count)) ? Number(envelope.live_count) : null

  return (
    <div className="space-y-3">
      <header className="card">
        <h1 className="text-lg font-bold text-ink">Integrations</h1>
        <p className="mt-1 text-sm text-muted">
          Six adapters sit behind real interfaces (Docs/APIs.md §4). In this build every one of
          them is a mock, and this screen says so — the badge is read from the adapter itself, so
          it cannot drift into claiming a connection the process does not have.
        </p>
        <p className="mt-1 text-xs text-muted">
          {items.length} adapter{items.length === 1 ? '' : 's'} registered
          {liveCount != null ? ` · ${liveCount} live` : ''}
          {note ? ` · ${note}` : ''}
        </p>
      </header>

      {listQ.isLoading ? (
        <p className="card text-sm text-muted">Loading adapters…</p>
      ) : listQ.isError ? (
        <p role="alert" className="card border-red text-sm text-[#8C1D18]">
          Could not load the adapter registry: {errorText(listQ.error)}
        </p>
      ) : items.length === 0 ? (
        <p className="card text-sm text-muted">
          No adapters are registered in this build. The interfaces are documented in
          Docs/APIs.md §4.
        </p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {items.map((a) => (
            <AdapterCard key={String(a.name)} adapter={a} mayTest={mayTest} />
          ))}
        </div>
      )}

      {!mayTest && !meQ.isLoading ? (
        <p className="text-[11px] text-muted">
          Your role may read this list but not fire a self-check; a test call is an outbound
          request, so it is not a read.
        </p>
      ) : null}

      <p className="text-[11px] text-muted">
        Mock connectors behind real interfaces (Docs/APIs.md §4) — said honestly on stage. Each
        mock answers from something real in this system (the parcels table, the event ledger, the
        seeded gazette PDFs, object storage), so the shape of every reply is the shape the live
        adapter would have to produce. “Last test” is in-process and resets on restart: it records
        the last time somebody pressed the button, not a background sync we do not run.
      </p>
    </div>
  )
}

/* ------------------------------------------------------------------- card */

function AdapterCard({ adapter, mayTest }: { adapter: Adapter; mayTest: boolean }) {
  const name = String(adapter.name ?? '')
  const [result, setResult] = useState<TestResult | null>(null)

  const test = useMutation({
    mutationFn: () => api<TestResult>(`/admin/integrations/${name}/test`, { method: 'POST' }),
    onSuccess: (r) => setResult(r),
  })

  const live = String(adapter.mode ?? '').toLowerCase() === 'live'
  const last: LastTest | null = result ?? adapter.last_test ?? null
  const deferred = listOf<string>(adapter.deferred).filter((d) => typeof d === 'string')
  const extras = result
    ? Object.entries(result).filter(([k]) => !RESULT_META.has(k))
    : []

  return (
    <section className="card flex flex-col">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="font-bold text-ink">{adapter.title || titleize(name)}</h2>
          <p className="font-mono text-[11px] text-muted">{name}</p>
        </div>
        {live ? (
          <span className="badge shrink-0 border border-accent bg-accent/10 text-accent">Live</span>
        ) : (
          <span
            className="badge shrink-0 border border-amber bg-amber/10 text-[#8A5300]"
            title="Mock implementation behind a real interface (Docs/APIs.md §4)"
          >
            Mock
          </span>
        )}
      </div>

      <dl className="mt-2 space-y-1 text-xs">
        {adapter.interface ? (
          <div>
            <dt className="text-muted">Interface</dt>
            <dd className="break-words font-mono text-[11px] text-ink">{adapter.interface}</dd>
          </div>
        ) : null}
        {adapter.real_target ? (
          <div>
            <dt className="text-muted">Real target</dt>
            <dd className="text-ink">{adapter.real_target}</dd>
          </div>
        ) : null}
        {adapter.mock_behaviour ? (
          <div>
            <dt className="text-muted">Mock behaviour</dt>
            <dd className="text-ink">{adapter.mock_behaviour}</dd>
          </div>
        ) : null}
        {deferred.length ? (
          <div>
            <dt className="text-muted">Not implemented in this build</dt>
            <dd className="font-mono text-[11px] text-[#8A5300]">{deferred.join(', ')}</dd>
          </div>
        ) : null}
      </dl>

      <div className="mt-2 border-t border-border pt-2 text-xs">
        <p className="text-muted">Last test</p>
        {last?.at ? (
          <p className="mt-0.5">
            <span
              className={`badge ${
                last.ok
                  ? 'border border-ok bg-ok/10 text-[#1B5E20]'
                  : 'border border-red bg-red/10 text-[#8C1D18]'
              }`}
            >
              {last.ok ? 'Passed' : 'Failed'}
            </span>{' '}
            <span className="text-muted">{formatTs(last.at)}</span>
          </p>
        ) : (
          <p className="mt-0.5 text-muted">Not tested in this process yet.</p>
        )}
        {last?.detail ? <p className="mt-1 text-ink">{last.detail}</p> : null}

        {extras.length ? (
          <ul className="mt-1 space-y-0.5 border-t border-border pt-1">
            {extras.map(([k, v]) => (
              <li key={k} className="break-words">
                <span className="text-muted">{titleize(k)}: </span>
                <span className="font-mono text-[11px] text-ink">
                  {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                </span>
              </li>
            ))}
          </ul>
        ) : null}

        {test.isError ? (
          <p role="alert" className="mt-1 rounded border border-red bg-red/10 p-1.5 text-[#8C1D18]">
            {errorText(test.error)}
          </p>
        ) : null}
      </div>

      <div className="mt-auto pt-2">
        <button
          type="button"
          className="btn text-xs"
          disabled={!mayTest || !name || test.isPending}
          title={mayTest ? undefined : 'Your role may read this list but not fire a test call'}
          onClick={() => test.mutate()}
        >
          {test.isPending ? 'Calling…' : 'Test call'}
        </button>
      </div>
    </section>
  )
}
