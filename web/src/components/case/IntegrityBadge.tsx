/**
 * IntegrityBadge — hash-chain verification for a case (Docs/APIs.md §3.3,
 * Docs/rules.md C1). Verified / mismatch, head hash, last check time.
 * The badge carries a word as well as a colour (Docs/Frontend.md §9).
 */
import { Integrity, formatTs, hashPrefix } from './caseApi'

export function IntegrityChip({
  integrity,
  loading,
  error,
}: {
  integrity?: Integrity | null
  loading?: boolean
  error?: unknown
}) {
  if (loading) return <span className="badge border border-border bg-surface text-muted">Chain: checking…</span>
  if (error)
    return (
      <span className="badge border border-border bg-surface text-muted">Chain: unavailable</span>
    )
  const verified = integrity?.verified === true
  return (
    <span
      className={`badge ${
        verified
          ? 'border border-ok bg-ok/10 text-[#1B5E20]'
          : 'border border-red bg-red/10 text-[#8C1D18]'
      }`}
    >
      {verified ? 'Chain verified' : 'Chain mismatch'}
    </span>
  )
}

export default function IntegrityBadge({
  integrity,
  loading,
  error,
  onRecheck,
  rechecking,
}: {
  integrity?: Integrity | null
  loading?: boolean
  error?: unknown
  onRecheck?: () => void
  rechecking?: boolean
}) {
  const verified = integrity?.verified === true

  return (
    <div className="max-w-2xl">
      <p className="text-xs text-muted">
        Every event stores <span className="font-mono">prev_hash</span> and{' '}
        <span className="font-mono">hash</span> (SHA-256 over the canonical event JSON), so the
        ledger is tamper-evident. This check recomputes the whole chain for the case.
      </p>

      {loading ? (
        <p className="mt-3 text-xs text-muted">Verifying the chain…</p>
      ) : error ? (
        <p role="alert" className="mt-3 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
          Could not verify: {error instanceof Error ? error.message : 'request failed'}
        </p>
      ) : (
        <div
          className={`mt-3 rounded border p-3 ${
            verified ? 'border-ok bg-ok/5' : 'border-red bg-red/5'
          }`}
        >
          <p className={`text-base font-semibold ${verified ? 'text-[#1B5E20]' : 'text-[#8C1D18]'}`}>
            {verified ? 'Verified — no tampering detected' : 'Mismatch — chain does not verify'}
          </p>
          <dl className="mt-2 grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
            <div>
              <dt className="text-muted">Head hash</dt>
              <dd className="break-all font-mono text-ink">{hashPrefix(integrity?.head_hash, 32)}</dd>
            </div>
            <div>
              <dt className="text-muted">Checked at</dt>
              <dd className="text-ink">{formatTs(integrity?.checked_at)}</dd>
            </div>
          </dl>
          {integrity?.detail ? <p className="mt-2 text-xs text-ink">{integrity.detail}</p> : null}
        </div>
      )}

      {onRecheck ? (
        <button type="button" className="btn mt-3 text-xs" onClick={onRecheck} disabled={rechecking}>
          {rechecking ? 'Re-checking…' : 'Re-check now'}
        </button>
      ) : null}
    </div>
  )
}
