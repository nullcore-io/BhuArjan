/**
 * RRTab — affected families and their Second/Third Schedule entitlements.
 *
 * Docs/Frontend.md §6: "family table with entitlement heads as columns
 * (Second/Third Schedule), status per cell (due/delivered/overdue) with s.38
 * timelines; evidence document per delivery. PII revealed only after a purpose
 * dialog; the read is audited and the UI says so."
 *
 * Contract: Docs/APIs.md §3.8
 *   GET  /cases/{id}/families?purpose=            masked by default
 *   GET  /cases/{id}/rr/summary                   heads × status counts + s.38 clocks
 *   POST /families/{id}/entitlements/{head}/deliver
 *
 * Three rules run through this file:
 *
 *  - **Masked is the default.** The register renders from `ref` (initials the server
 *    computes once, at enumeration) and never asks for a name. Revealing identities
 *    is a deliberate act behind a purpose dialog, and the banner stays on screen for
 *    as long as the names are — Docs/rules.md C5 (DPDP Act 2023).
 *  - **Colour is never the only signal.** Every status cell carries the word
 *    "Delivered", "Due" or "Overdue" (Docs/Frontend.md §9).
 *  - **Read tolerantly.** Counts arrive nested or flat, the register arrives as
 *    `items` or `families`, and a head map may be an object or a list. A partial
 *    response degrades to a visible note, never to a blank tab.
 *
 * On "overdue": the server stores only `due` and `delivered`, deliberately
 * (api/app/domain/rr/schedules.py). "Overdue" is a *view* computed here from the
 * s.38(1) R&R clocks the summary returns — monetary R&R within 6 months
 * (`RR_MONETARY_6M`), infrastructural R&R within 18 months (`RR_INFRA_18M`). A head
 * still `due` after its own clock has breached is shown as overdue, and the footnote
 * says exactly that so nobody reads it as a stored status.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, formatDate } from '../../lib/api'
import {
  CLOCK_LEVEL,
  Clock,
  DeliveryResult,
  DocumentMeta,
  EntitlementCell,
  Family,
  FamilyPage,
  INP,
  RRHead,
  RRSummary,
  clockLevel,
  errorText,
  normalizePage,
  problemErrors,
  titleize,
  today,
} from './caseApi'

/* ------------------------------------------------------------------- roles */

/** Roles the server will unlock names for — api/app/api/v1/rr.py `PII_ROLES`. */
const PII_ROLES = ['COLLECTOR', 'ADMIN_RR']
/** Roles that may record a delivery — api/app/api/v1/rr.py `DELIVER_ROLES`. */
const DELIVER_ROLES = ['LAO', 'CALA', 'COLLECTOR', 'ADMIN_RR', 'ADMIN']

const AUDIT_NOTICE =
  'This read is audited — every identity access is recorded with your name and purpose'

/* ---------------------------------------------------------------- fetching */

function fetchFamilies(caseId: string, purpose: string | null): Promise<FamilyPage> {
  const qs = new URLSearchParams({ limit: '200' })
  if (purpose) qs.set('purpose', purpose)
  return api<FamilyPage>(`/cases/${caseId}/families?${qs}`)
}

const fetchRRSummary = (caseId: string) => api<RRSummary>(`/cases/${caseId}/rr/summary`)

/** Register rows, whichever envelope key the router used. */
function familyRows(page?: FamilyPage | Family[] | null): Family[] {
  if (Array.isArray(page)) return page
  return page?.items ?? page?.families ?? []
}

/** `{head_id: cell}` from either the object map the server sends or a list. */
function cellsOf(f: Family): Record<string, EntitlementCell> {
  const raw = f.entitlements ?? f.rr_entitlements
  if (!raw) return {}
  if (Array.isArray(raw)) {
    const out: Record<string, EntitlementCell> = {}
    for (const c of raw) {
      const key = (c as { head?: unknown }).head
      if (typeof key === 'string') out[key] = c
    }
    return out
  }
  return raw
}

/* ------------------------------------------------------------------- heads */

/** Column headings short enough for a dense table; the full label is the tooltip. */
const HEAD_SHORT: Record<string, string> = {
  house: 'House',
  land_for_land: 'Land for land',
  employment: 'Employment',
  subsistence_allowance: 'Subsistence',
  transportation_allowance: 'Transport',
  cattle_shed_grant: 'Cattle shed',
  artisan_grant: 'Artisan grant',
  resettlement_allowance: 'Resettlement',
  stamp_duty_exemption: 'Stamp duty',
  resettlement_infrastructure: 'Site infrastructure',
}

function headShort(h: RRHead): string {
  return HEAD_SHORT[h.head] ?? titleize(h.head)
}

function headTitle(h: RRHead): string {
  const parts = [h.label || titleize(h.head)]
  if (h.basis) parts.push(h.basis)
  if (h.applies_to && h.applies_to !== 'all') parts.push(`applies to: ${h.applies_to}`)
  return parts.join(' — ')
}

/** Columns come from the summary; if it is unavailable, from the register itself. */
function headColumns(summary: RRSummary | undefined, rows: Family[]): RRHead[] {
  const fromSummary = (summary?.heads ?? []).filter(
    (h): h is RRHead => !!h && typeof h.head === 'string',
  )
  if (fromSummary.length) return fromSummary
  const seen: string[] = []
  for (const f of rows) {
    for (const k of Object.keys(cellsOf(f))) if (!seen.includes(k)) seen.push(k)
  }
  return seen.map((head) => ({ head }))
}

function headCount(h: RRHead, key: 'due' | 'delivered' | 'overdue'): number | null {
  const nested = h.counts?.[key]
  const flat = h[key]
  const v = nested ?? flat
  return v == null || !Number.isFinite(Number(v)) ? null : Number(v)
}

/* ---------------------------------------------------------- s.38 R&R clocks */

/** s.38(1) proviso: monetary R&R within 6 months, infrastructural within 18. */
function rrClockIdFor(h: RRHead): string {
  return h.kind === 'infra' ? 'RR_INFRA_18M' : 'RR_MONETARY_6M'
}

/**
 * Heads whose own statutory window has already run out. Only a breached or lapsed
 * clock counts: a clock that is merely amber has not passed its due date, and a
 * suspended one is under a court stay — nobody is in default while a court has
 * stopped the proceeding (Docs/rules.md C2).
 */
function overdueHeads(summary: RRSummary | undefined, heads: RRHead[]): Set<string> {
  const clocks = new Map<string, Clock>()
  for (const c of summary?.clocks ?? []) if (c?.clock_id) clocks.set(c.clock_id, c)
  const out = new Set<string>()
  for (const h of heads) {
    const c = clocks.get(rrClockIdFor(h))
    if (!c) continue
    const level = clockLevel(c)
    if (level === 'breached' || level === 'lapsed') out.add(h.head)
  }
  return out
}

/* ------------------------------------------------------------------- cells */

type CellState = 'delivered' | 'due' | 'overdue'

const CELL_VIEW: Record<CellState, { label: string; cls: string }> = {
  delivered: { label: 'Delivered', cls: 'bg-ok/10 text-[#1B5E20] border border-ok' },
  due: { label: 'Due', cls: 'bg-surface text-muted border border-border' },
  overdue: { label: 'Overdue', cls: 'bg-red/10 text-[#8C1D18] border border-red' },
}

function cellState(cell: EntitlementCell | undefined, headIsOverdue: boolean): CellState {
  const s = String(cell?.status ?? 'due').toLowerCase()
  if (s === 'delivered') return 'delivered'
  if (s === 'overdue') return 'overdue'
  return headIsOverdue ? 'overdue' : 'due'
}

function nameOf(f: Family): string | null {
  const n = f.head?.name
  return typeof n === 'string' && n.trim() ? n : null
}

function textField(head: Record<string, unknown> | null | undefined, key: string): string | null {
  const v = head?.[key]
  return typeof v === 'string' && v.trim() ? v : null
}

/* =========================================================================== */

/** Stages from which both shipped rule-sets accept RR_ENTITLEMENT_DELIVERED (s.38(1): R&R runs from the award). */
const DELIVERY_STAGES = ['AWARDED', 'POSSESSED']

export default function RRTab({ caseId, stage }: { caseId: string; stage?: string | null }) {
  const qc = useQueryClient()
  /** Non-null exactly while identities are being requested with a stated purpose. */
  const [purpose, setPurpose] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)
  const [delivering, setDelivering] = useState<{ family: Family; head: RRHead } | null>(null)

  // Shared with the case header's query — no extra request.
  const meQ = useQuery<{ roles?: string[] }>({ queryKey: ['me'], queryFn: () => api('/auth/me') })
  const roles = meQ.data?.roles ?? []
  const mayReveal = PII_ROLES.some((r) => roles.includes(r))
  const stageAllowsDelivery = !stage || DELIVERY_STAGES.includes(String(stage).toUpperCase())
  const mayDeliver = stageAllowsDelivery && DELIVER_ROLES.some((r) => roles.includes(r))

  const familiesQ = useQuery({
    queryKey: ['case', caseId, 'families', purpose ?? ''],
    queryFn: () => fetchFamilies(caseId, purpose),
    enabled: !!caseId,
    // An audited PII read happens because an officer asked for it, not because the
    // window regained focus. Docs/rules.md C5 counts every decrypt.
    refetchOnWindowFocus: false,
  })
  const summaryQ = useQuery({
    queryKey: ['case', caseId, 'rr', 'summary'],
    queryFn: () => fetchRRSummary(caseId),
    enabled: !!caseId,
    retry: false,
  })

  const page = familiesQ.data
  const rows = useMemo(() => familyRows(page), [page])
  const summary = summaryQ.data
  const heads = useMemo(() => headColumns(summary, rows), [summary, rows])
  const overdue = useMemo(() => overdueHeads(summary, heads), [summary, heads])

  /** The server's own word wins; a row carrying a name is the fallback proof. */
  const unlocked =
    page?.pii === 'unlocked' || (purpose != null && rows.some((r) => nameOf(r) != null))
  const revealing = purpose != null && !unlocked && familiesQ.isFetching
  /** Asked for names and did not get them — say why rather than fail silently. */
  const refusedReason =
    purpose != null && !unlocked && !familiesQ.isFetching && !familiesQ.isError
      ? (page?.masked_reason ??
        'no reason was given; the register came back masked (Docs/rules.md C5).')
      : null

  /** Locking again drops the decrypted page from the client cache, not just from view. */
  function hideIdentities() {
    const key = ['case', caseId, 'families', purpose ?? '']
    setPurpose(null)
    qc.removeQueries({ queryKey: key, exact: true })
  }

  const totals = summary?.families
  const cellCounts = summary?.status_counts
  const progress = summary?.rr_progress_pct
  const cellsDue = Number(cellCounts?.due ?? 0)
  const cellsDelivered = Number(cellCounts?.delivered ?? 0)
  // No families enumerated is not a shortfall — it renders plain, never amber.
  const headsTone =
    cellsDue + cellsDelivered === 0 ? undefined : cellsDue === 0 ? 'ok' : 'amber'

  return (
    <div>
      {/* ───────────────────────────────────────────────────────── summary tiles */}
      <div className="flex flex-wrap items-stretch gap-3">
        <Tile label="Affected families" value={countText(totals?.total ?? page?.total ?? rows.length)} />
        <Tile label="Displaced" value={countText(totals?.displaced ?? countBy(rows, 'displaced'))} />
        <Tile label="SC / ST" value={countText(totals?.sc_st ?? countBy(rows, 'sc_st'))} />
        <Tile
          label="Entitlement heads delivered"
          value={
            cellCounts
              ? `${countText(cellsDelivered)} of ${countText(cellsDelivered + cellsDue)}`
              : '—'
          }
          tone={headsTone}
        />
        <div className="min-w-[15rem] flex-1 rounded border border-border bg-surface p-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">
            R&amp;R progress · Second/Third Schedule
          </p>
          <p className="mt-0.5 text-base font-bold tabular-nums text-ink">
            {progress == null ? '—' : `${Number(progress).toFixed(1)}%`}
          </p>
          <p className="mt-0.5 text-[11px] text-muted">
            {summary?.as_of_seq != null ? `As of seq ${summary.as_of_seq}` : 'As of seq —'}
            {summary?.as_of_date ? ` · ${formatDate(summary.as_of_date)}` : ''}
          </p>
        </div>
      </div>

      {summaryQ.isError ? (
        <p role="alert" className="mt-3 rounded border border-amber bg-amber/10 p-2 text-xs text-[#8A5300]">
          Head totals and the s.38 clocks are unavailable ({errorText(summaryQ.error)}). The
          register below still renders; columns are read from the families themselves.
        </p>
      ) : null}

      {/* ─────────────────────────────────────────────────────── s.38 R&R clocks */}
      <RRClocks clocks={summary?.clocks ?? []} />

      {/* ───────────────────────────────────────────────────── identity controls */}
      <div className="mt-3">
        {unlocked ? (
          <div
            className="rounded border border-amber bg-amber/10 p-2 text-xs text-[#8A5300]"
            role="status"
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-bold">Audited read — identities revealed</p>
                <p className="mt-0.5">{AUDIT_NOTICE}.</p>
                {page?.purpose || purpose ? (
                  <p className="mt-0.5">
                    Purpose recorded: <span className="italic">“{page?.purpose ?? purpose}”</span>
                  </p>
                ) : null}
              </div>
              <button type="button" className="btn shrink-0 text-xs" onClick={hideIdentities}>
                Hide identities
              </button>
            </div>
          </div>
        ) : revealing ? (
          <p className="text-xs text-muted" role="status">
            Requesting identities — recording the read against your name and purpose…
          </p>
        ) : mayReveal ? (
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className="btn text-xs" onClick={() => setAsking(true)}>
              Reveal identities…
            </button>
            <span className="text-[11px] text-muted">
              Names are decrypted only for a role with jurisdiction and a stated purpose
              (Docs/rules.md C5). {AUDIT_NOTICE}.
            </span>
          </div>
        ) : (
          <p className="text-[11px] text-muted">
            Masked register. {page?.masked_reason ??
              'Names are released to Collector, Administrator R&R and State Revenue only, and only against a stated purpose (Docs/rules.md C5).'}
          </p>
        )}
        {refusedReason ? (
          <p role="alert" className="mt-2 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
            The server kept this register masked: {refusedReason}
          </p>
        ) : null}
      </div>

      {/* ──────────────────────────────────────────────────────────── the table */}
      <div className="mt-3 overflow-x-auto">
        <table className="gov">
          <caption className="sr-only">
            Affected families and Second/Third Schedule entitlement heads, one column per head
          </caption>
          <thead>
            <tr>
              <th scope="col">{unlocked ? 'Head of family' : 'Family (masked ref)'}</th>
              <th scope="col">Category</th>
              <th scope="col">Displaced</th>
              <th scope="col">SC / ST</th>
              {heads.map((h) => (
                <th key={h.head} scope="col" title={headTitle(h)} className="whitespace-nowrap">
                  {headShort(h)}
                  {h.basis ? (
                    <span className="block font-normal normal-case text-[10px] text-muted">
                      {shortBasis(h.basis)}
                    </span>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {familiesQ.isLoading ? (
              <tr>
                <td colSpan={4 + heads.length} className="text-muted">
                  Loading the affected-family register…
                </td>
              </tr>
            ) : familiesQ.isError ? (
              <tr>
                <td colSpan={4 + heads.length}>
                  <span role="alert" className="text-[#8C1D18]">
                    Could not load families: {errorText(familiesQ.error)}
                  </span>
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={4 + heads.length} className="text-muted">
                  No affected families have been enumerated on this case yet — the
                  families KPI reads 0 because there is nothing to count, not because the
                  count failed.
                </td>
              </tr>
            ) : (
              rows.map((f) => {
                const cells = cellsOf(f)
                const name = nameOf(f)
                return (
                  <tr key={f.id}>
                    <td className="align-top">
                      {name ? (
                        <>
                          <span className="font-semibold text-ink">{name}</span>
                          <span className="block text-[11px] text-muted">
                            {[
                              textField(f.head, 'guardian'),
                              textField(f.head, 'village'),
                              textField(f.head, 'id_ref_last4')
                                ? `ID ••••${textField(f.head, 'id_ref_last4')}`
                                : null,
                            ]
                              .filter(Boolean)
                              .join(' · ') || f.ref}
                          </span>
                        </>
                      ) : (
                        <span className="font-mono text-[12px]">{f.ref || '—'}</span>
                      )}
                      {f.synthetic ? (
                        <span
                          className="ml-1 badge border border-border bg-surface text-muted"
                          title="Synthetic demo record — no real PII (Docs/rules.md A5)"
                        >
                          Synthetic
                        </span>
                      ) : null}
                    </td>
                    <td className="whitespace-nowrap">{f.category ? titleize(f.category) : '—'}</td>
                    <td>
                      {f.displaced ? (
                        <span className="badge border border-accent2 bg-accent2/10 text-[#7A4E09]">
                          Displaced
                        </span>
                      ) : (
                        <span className="text-muted">Not displaced</span>
                      )}
                    </td>
                    <td>
                      {f.sc_st ? (
                        <span className="badge border border-accent bg-accent/10 text-accent">
                          SC / ST
                        </span>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    {heads.map((h) => {
                      const cell = cells[h.head]
                      const state = cellState(cell, overdue.has(h.head))
                      const view = CELL_VIEW[state]
                      return (
                        <td key={h.head} className="whitespace-nowrap align-top">
                          <span className={`badge ${view.cls}`}>{view.label}</span>
                          {cell?.delivered_on ? (
                            <span className="block text-[11px] text-muted">
                              {formatDate(cell.delivered_on)}
                            </span>
                          ) : null}
                          {state !== 'delivered' && mayDeliver ? (
                            <button
                              type="button"
                              className="btn mt-1 px-2 py-0.5 text-[11px]"
                              onClick={() => setDelivering({ family: f, head: h })}
                            >
                              Deliver…
                            </button>
                          ) : null}
                        </td>
                      )
                    })}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {page?.next_cursor ? (
        <p className="mt-2 text-[11px] text-muted">
          Showing the first 200 families of {countText(page.total)}. The register is paged
          (Docs/APIs.md §1); narrow by village on the parcels screen for larger cases.
        </p>
      ) : null}

      {/* ──────────────────────────────────────────────────── head-level totals */}
      {heads.some((h) => headCount(h, 'delivered') != null) ? (
        <div className="mt-3 overflow-x-auto">
          <table className="gov">
            <caption className="sr-only">Delivery totals per entitlement head</caption>
            <thead>
              <tr>
                <th scope="col">Entitlement head</th>
                <th scope="col">Statutory basis</th>
                <th scope="col" className="text-right">Delivered</th>
                <th scope="col" className="text-right">Due</th>
                <th scope="col">Window</th>
              </tr>
            </thead>
            <tbody>
              {heads.map((h) => (
                <tr key={h.head}>
                  <td>{h.label || titleize(h.head)}</td>
                  <td className="text-[11px] text-muted">{h.basis || '—'}</td>
                  <td className="text-right tabular-nums">{countText(headCount(h, 'delivered'))}</td>
                  <td className="text-right tabular-nums">{countText(headCount(h, 'due'))}</td>
                  <td className="whitespace-nowrap text-[11px]">
                    {titleize(rrClockIdFor(h))}
                    {overdue.has(h.head) ? (
                      <span className="ml-1 badge border border-red bg-red/10 text-[#8C1D18]">
                        Window closed
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <p className="mt-2 text-[11px] text-muted">
        {summary?.schedule_note ??
          'Statuses only — Second Schedule amounts are as notified by the appropriate Government and revised by indexation, so no rupee figure is held here (verify current values).'}{' '}
        “Overdue” is not a stored status: a head still due after its own s.38(1) clock has
        breached — monetary R&amp;R 6 months, infrastructural R&amp;R 18 months — is shown as
        overdue on this screen.
      </p>
      <p className="mt-1 text-[11px] text-muted">
        Every identity read is written to the audit trail with the reader and the purpose
        (Docs/rules.md C5, DPDP Act 2023); the ledger itself never carries a name.
      </p>

      {asking ? (
        <PurposeDialog
          onCancel={() => setAsking(false)}
          onConfirm={(text) => {
            setPurpose(text)
            setAsking(false)
          }}
        />
      ) : null}

      {delivering ? (
        <DeliverModal
          caseId={caseId}
          family={delivering.family}
          head={delivering.head}
          onClose={() => setDelivering(null)}
        />
      ) : null}
    </div>
  )
}

/* --------------------------------------------------------------- s.38 clocks */

function RRClocks({ clocks }: { clocks: Clock[] }) {
  if (!clocks.length) return null
  return (
    <section className="mt-3 rounded border border-border bg-surface p-2" aria-labelledby="rr-clocks-h">
      <h3 id="rr-clocks-h" className="text-xs font-bold uppercase tracking-wide text-muted">
        R&amp;R timelines · s.38(1) proviso
      </h3>
      <ul className="mt-2 grid gap-2 sm:grid-cols-2">
        {clocks.map((c) => {
          const meta = CLOCK_LEVEL[clockLevel(c)]
          return (
            <li key={c.clock_id} className="rounded border border-border bg-bg p-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-semibold text-ink">{titleize(c.clock_id)}</span>
                <span className={`badge ${meta.chip}`}>{meta.label}</span>
              </div>
              <p className="mt-0.5 text-[11px] text-muted">
                {c.basis ? `${c.basis} · ` : ''}
                {formatDate(c.start_date)} <span aria-hidden="true">→</span>{' '}
                <span className="sr-only">to</span>
                <span className="font-semibold text-ink">{formatDate(c.due_date)}</span>
              </p>
              {c.consequence ? <p className="mt-0.5 text-[11px] text-ink">{c.consequence}</p> : null}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/* ------------------------------------------------------------ purpose dialog */

/**
 * The gate in front of every decrypt. The purpose is mandatory and free text: it is
 * written verbatim into the audit row, so a dropdown of pre-baked reasons would make
 * the audit trail say less than the officer meant.
 */
function PurposeDialog({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void
  onConfirm: (purpose: string) => void
}) {
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    ref.current?.focus()
  }, [])

  const valid = text.trim().length >= 8

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/50 p-4"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onCancel()
      }}
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="purpose-title"
        aria-describedby="purpose-notice"
        className="card mt-12 w-full max-w-lg shadow-none"
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) onConfirm(text.trim())
        }}
      >
        <h2 id="purpose-title" className="text-base font-bold">
          Reveal affected-family identities
        </h2>
        <p
          id="purpose-notice"
          className="mt-2 rounded border border-amber bg-amber/10 p-2 text-xs font-semibold text-[#8A5300]"
        >
          {AUDIT_NOTICE}.
        </p>
        <p className="mt-2 text-xs text-muted">
          The Digital Personal Data Protection Act 2023 permits a decrypt only for a role with
          jurisdiction and a stated purpose (Docs/rules.md C5). State the purpose in your own
          words — it is stored verbatim against your name.
        </p>

        <label className="mt-3 block text-xs">
          <span className="mb-0.5 block font-semibold text-muted">
            Purpose of this identity access (required)
          </span>
          <textarea
            ref={ref}
            required
            rows={3}
            className={INP}
            placeholder="e.g. verifying subsistence-allowance disbursement against the R&R award before possession"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        {!valid && text.length > 0 ? (
          <p className="mt-1 text-[11px] text-[#8A5300]">
            Give a purpose an auditor could read back — at least a few words.
          </p>
        ) : null}

        <div className="mt-3 flex justify-end gap-2 border-t border-border pt-3">
          <button type="button" className="btn" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={!valid}>
            Reveal — record this read
          </button>
        </div>
      </form>
    </div>
  )
}

/* ------------------------------------------------------------ deliver modal */

/**
 * POST /families/{id}/entitlements/{head}/deliver — Docs/APIs.md §3.8.
 * Appends `RR_ENTITLEMENT_DELIVERED` to the case ledger, so the delivery date is a
 * legal date (`occurred_at`), not the moment the officer typed it.
 */
function DeliverModal({
  caseId,
  family,
  head,
  onClose,
}: {
  caseId: string
  family: Family
  head: RRHead
  onClose: () => void
}) {
  const qc = useQueryClient()
  const firstRef = useRef<HTMLInputElement>(null)
  const [deliveredOn, setDeliveredOn] = useState<string>(today())
  const [evidenceId, setEvidenceId] = useState<string>('')

  useEffect(() => {
    firstRef.current?.focus()
  }, [])

  // Evidence is optional in the contract; the picker simply disappears when the
  // documents endpoint is not available.
  const docsQ = useQuery({
    queryKey: ['case', caseId, 'rr-evidence-docs'],
    queryFn: async () =>
      normalizePage<DocumentMeta>(await api<unknown>(`/cases/${caseId}/documents`), 'documents')
        .items,
    retry: false,
  })

  const mutation = useMutation({
    mutationFn: () =>
      api<DeliveryResult>(`/families/${family.id}/entitlements/${head.head}/deliver`, {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        json: {
          delivered_on: deliveredOn,
          ...(evidenceId ? { evidence_document_id: evidenceId } : {}),
        },
      }),
    onSuccess: () => {
      // Prefix-matches the register, the summary, the clocks and the ledger.
      qc.invalidateQueries({ queryKey: ['case', caseId] })
      onClose()
    },
  })

  const problem = (mutation.error as { problem?: Record<string, unknown> } | null)?.problem
  const lines = problemErrors(problem)
  const docs = docsQ.data ?? []

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/50 p-4"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="deliver-title"
        className="card mt-12 w-full max-w-lg shadow-none"
        onSubmit={(e) => {
          e.preventDefault()
          if (deliveredOn) mutation.mutate()
        }}
      >
        <h2 id="deliver-title" className="text-base font-bold">
          Record delivery — {head.label || titleize(head.head)}
        </h2>
        <p className="mt-1 text-xs text-muted">
          Family <span className="font-mono">{family.ref || family.id.slice(0, 8)}</span>
          {head.basis ? ` · ${head.basis}` : ''}. This appends
          <span className="font-mono"> RR_ENTITLEMENT_DELIVERED</span> to the case ledger; the
          date below is the legal date of delivery.
        </p>
        <p className="mt-1 text-[11px] text-muted">
          The rule-set decides from which stage a delivery may be recorded — both shipped tracks
          put it on <span className="font-mono">POSSESSED</span>, because s.38(1) measures the R&amp;R
          clocks from the award and possession follows payment. A refusal below is the rule-set
          speaking, and it names the rule it applied.
        </p>

        <label className="mt-3 block text-xs">
          <span className="mb-0.5 block font-semibold text-muted">Delivered on (legal date)</span>
          <input
            ref={firstRef}
            type="date"
            required
            className={INP}
            value={deliveredOn}
            onChange={(e) => setDeliveredOn(e.target.value)}
          />
        </label>

        {docs.length ? (
          <label className="mt-3 block text-xs">
            <span className="mb-0.5 block font-semibold text-muted">
              Evidence document (optional)
            </span>
            <select
              className={INP}
              value={evidenceId}
              onChange={(e) => setEvidenceId(e.target.value)}
            >
              <option value="">No evidence copy attached</option>
              {docs.map((d) => (
                <option key={d.id} value={d.id}>
                  {titleize(d.kind)} · {d.filename || d.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {mutation.isError ? (
          <div className="mt-3 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]" role="alert">
            <p className="font-semibold">
              {(problem?.title as string) || 'Could not record the delivery'}
            </p>
            {problem?.detail ? <p className="mt-0.5">{String(problem.detail)}</p> : null}
            {!problem ? <p className="mt-0.5">{(mutation.error as Error).message}</p> : null}
            {lines.length ? (
              <ul className="mt-1 list-disc pl-4">
                {lines.map((l, i) => (
                  <li key={i}>
                    <span className="font-mono">{l.label}</span>
                    {l.detail ? ` — ${l.detail}` : ''}
                  </li>
                ))}
              </ul>
            ) : null}
            {problem?.ruleset_ref ? (
              <p className="mt-1 font-mono text-[11px]">{String(problem.ruleset_ref)}</p>
            ) : null}
          </div>
        ) : null}

        <div className="mt-3 flex justify-end gap-2 border-t border-border pt-3">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn-primary" disabled={!deliveredOn || mutation.isPending}>
            {mutation.isPending ? 'Recording…' : 'Record delivery'}
          </button>
        </div>
      </form>
    </div>
  )
}

/* ------------------------------------------------------------------- bits */

function Tile({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'amber' }) {
  return (
    <div className="min-w-[9rem] flex-1 rounded border border-border bg-surface p-2">
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p
        className={`mt-0.5 text-base font-bold tabular-nums ${
          tone === 'amber' ? 'text-[#8A5300]' : tone === 'ok' ? 'text-[#1B5E20]' : 'text-ink'
        }`}
      >
        {value}
      </p>
    </div>
  )
}

/** A figure that is genuinely absent renders as "—", never as 0. */
function countText(v: unknown): string {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return Math.round(Number(v)).toLocaleString('en-IN')
}

function countBy(rows: Family[], key: 'displaced' | 'sc_st'): number | null {
  if (!rows.length) return null
  return rows.reduce((a, r) => a + (r[key] ? 1 : 0), 0)
}

/** "Second Schedule element 5 *(verify)*" → "Sch. II el. 5" for a column heading. */
function shortBasis(basis: string): string {
  const el = /element\s+(\d+)/i.exec(basis)
  if (/third schedule/i.test(basis)) return 'Sch. III'
  if (el) return `Sch. II el. ${el[1]}`
  const sec = /s\.\s*([0-9()A-Za-z]+)/.exec(basis)
  return sec ? `s.${sec[1]}` : ''
}
