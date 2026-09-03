/**
 * Loading / error / empty states.
 *
 * Errors quote the RFC 7807 `detail` the API sent (Docs/APIs.md §1) rather
 * than a generic "something went wrong" — an officer needs to know whether the
 * case is out of jurisdiction, the rule-set rejected the transition, or the
 * router simply is not deployed yet.
 */
import type { ReactNode } from 'react'
import { errorText, httpStatus } from './format'

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-2 py-6 text-sm text-muted" role="status">
      <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
      {label}
    </div>
  )
}

export function ErrorNote({ error, what }: { error: unknown; what?: string }) {
  const status = httpStatus(error)
  const problem = (error as { problem?: Record<string, unknown> } | null)?.problem
  const rulesetRef = typeof problem?.ruleset_ref === 'string' ? problem.ruleset_ref : null
  return (
    <div
      className="rounded border border-red bg-red/5 px-3 py-2 text-sm text-[#8C1D18]"
      role="alert"
    >
      <div className="font-semibold">
        {what ? `${what} unavailable` : 'Request failed'}
        {status ? ` (HTTP ${status})` : ''}
      </div>
      <div>{errorText(error)}</div>
      {rulesetRef ? <div className="mt-1 text-xs opacity-80">Rule-set: {rulesetRef}</div> : null}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-2 py-6 text-sm text-muted">{children}</div>
}

/** Section wrapper with a title bar — the dashboards' repeated frame. */
export function Panel({
  title,
  right,
  children,
  className = '',
}: {
  title: ReactNode
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`card p-0 ${className}`}>
      <div className="card-head">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        {right ? <div className="text-xs text-muted">{right}</div> : null}
      </div>
      <div className="card-body">{children}</div>
    </section>
  )
}
