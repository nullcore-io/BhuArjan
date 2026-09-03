/**
 * CompensationTab — award lines per parcel/owner and the possession gate.
 * Docs/Frontend.md §6, Docs/APIs.md §3.7, First Schedule maths in Docs/rules.md B4:
 *   T = MV x F + A · S = 100% of T (s.30(1)) · I = 12% p.a. (s.30(3)) · Total = T + S + I
 * Owners are shown as masked references — this screen never asks for PII.
 */
import { formatINR } from '../../lib/api'
import { CompensationLine, CompensationSummary, num } from './caseApi'

function parcelLabel(l: CompensationLine): string {
  return l.parcel_label || l.survey_no || l.ulpin || (l.parcel_id ? l.parcel_id.slice(0, 8) : '—')
}

/** Falls back to the line total when the server does not send `outstanding`. */
function outstandingOf(l: CompensationLine): number {
  if (l.outstanding_paise != null) return num(l.outstanding_paise)
  return Math.max(0, num(l.total_paise) - num(l.paid_paise))
}

export default function CompensationTab({
  data,
  loading,
  error,
}: {
  data?: CompensationSummary | null
  loading?: boolean
  error?: unknown
}) {
  if (loading) return <p className="text-xs text-muted">Loading compensation…</p>
  if (error)
    return (
      <p role="alert" className="rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
        Could not load compensation: {error instanceof Error ? error.message : 'request failed'}
      </p>
    )

  const lines = data?.lines ?? []
  const assessed =
    data?.assessed_total != null
      ? num(data.assessed_total)
      : lines.reduce((a, l) => a + num(l.total_paise), 0)
  const paid =
    data?.paid_total != null ? num(data.paid_total) : lines.reduce((a, l) => a + num(l.paid_paise), 0)
  const outstanding =
    data?.outstanding != null ? num(data.outstanding) : Math.max(0, assessed - paid)
  const gateOpen = assessed > 0 && paid >= assessed

  return (
    <div>
      <div className="flex flex-wrap items-stretch gap-3">
        <Tile label="Assessed" value={formatINR(assessed)} />
        <Tile label="Paid" value={formatINR(paid)} />
        <Tile label="Outstanding" value={formatINR(outstanding)} tone={outstanding > 0 ? 'amber' : 'ok'} />
        {data?.interest_accrued != null ? (
          <Tile label="Interest accrued (s.30(3))" value={formatINR(data.interest_accrued)} />
        ) : null}

        <div
          className={`min-w-[15rem] flex-1 rounded border p-2 ${
            gateOpen ? 'border-ok bg-ok/5' : 'border-red bg-red/5'
          }`}
        >
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">
            Possession gate · s.38
          </p>
          <p className={`mt-0.5 text-sm font-semibold ${gateOpen ? 'text-[#1B5E20]' : 'text-[#8C1D18]'}`}>
            {gateOpen ? 'Open — compensation paid in full' : 'Blocked — compensation not paid in full'}
          </p>
          <p className="mt-0.5 text-xs text-muted">
            Possession may be taken only after compensation is paid or tendered (s.38(1)); under
            urgency (s.40) at least 80% must be paid.
          </p>
        </div>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="gov">
          <caption className="sr-only">Compensation award lines per parcel and owner</caption>
          <thead>
            <tr>
              <th scope="col">Parcel</th>
              <th scope="col">Owner (ref)</th>
              <th scope="col" className="text-right">Market value</th>
              <th scope="col" className="text-right">Factor</th>
              <th scope="col" className="text-right">Assets</th>
              <th scope="col" className="text-right">Solatium</th>
              <th scope="col" className="text-right">Interest</th>
              <th scope="col" className="text-right">Total</th>
              <th scope="col" className="text-right">Paid</th>
              <th scope="col" className="text-right">Outstanding</th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 ? (
              <tr>
                <td colSpan={10} className="text-muted">
                  No award lines assessed yet for this case.
                </td>
              </tr>
            ) : (
              lines.map((l, i) => {
                const out = outstandingOf(l)
                return (
                  <tr key={l.id ?? `${l.parcel_id}-${i}`}>
                    <td>{parcelLabel(l)}</td>
                    <td className="font-mono text-xs">{l.owner_ref ?? '—'}</td>
                    <td className="text-right tabular-nums">{formatINR(l.market_value_paise)}</td>
                    <td className="text-right tabular-nums">
                      {l.factor != null ? num(l.factor).toFixed(2) : '—'}
                    </td>
                    <td className="text-right tabular-nums">{formatINR(l.assets_paise)}</td>
                    <td className="text-right tabular-nums">{formatINR(l.solatium_paise)}</td>
                    <td className="text-right tabular-nums">{formatINR(l.interest_paise)}</td>
                    <td className="text-right font-semibold tabular-nums">
                      {formatINR(l.total_paise)}
                    </td>
                    <td className="text-right tabular-nums">{formatINR(l.paid_paise)}</td>
                    <td
                      className={`text-right tabular-nums ${out > 0 ? 'font-semibold text-[#8C1D18]' : 'text-muted'}`}
                    >
                      {formatINR(out)}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
          {lines.length ? (
            <tfoot>
              <tr className="bg-surface font-semibold">
                <td colSpan={7}>Total</td>
                <td className="text-right tabular-nums">{formatINR(assessed)}</td>
                <td className="text-right tabular-nums">{formatINR(paid)}</td>
                <td className="text-right tabular-nums">{formatINR(outstanding)}</td>
              </tr>
            </tfoot>
          ) : null}
        </table>
      </div>

      <p className="mt-2 text-xs text-muted">
        Market value per s.26(1); First Schedule factor applied to rural land; solatium 100% of
        (MV x factor + assets) per s.30(1); interest 12% p.a. per s.30(3). Owner identities are
        shown as masked references.
      </p>
    </div>
  )
}

function Tile({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: 'ok' | 'amber'
}) {
  return (
    <div className="min-w-[9rem] flex-1 rounded border border-border bg-surface p-2">
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p
        className={`mt-0.5 text-base font-semibold tabular-nums ${
          tone === 'amber' ? 'text-[#8A5300]' : tone === 'ok' ? 'text-[#1B5E20]' : 'text-ink'
        }`}
      >
        {value}
      </p>
    </div>
  )
}
