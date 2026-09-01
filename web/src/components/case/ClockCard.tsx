/**
 * ClockCard — one statutory clock. Docs/Frontend.md §2, Docs/rules.md C2.
 * Shows `basis` (section) and `consequence` verbatim; the elapsed bar always
 * carries a text label so colour is never the only signal.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, formatDate, uploadForm } from '../../lib/api'
import {
  CLOCK_LEVEL,
  Clock,
  INP,
  clockElapsed,
  clockLevel,
  daysBetween,
  extendAuthority,
  isExtendable,
  problemErrors,
  titleize,
  today,
} from './caseApi'

export default function ClockCard({
  clock,
  onExtend,
}: {
  clock: Clock
  onExtend?: (clock: Clock) => void
}) {
  const level = clockLevel(clock)
  const meta = CLOCK_LEVEL[level]
  const pct = Math.round(clockElapsed(clock) * 100)
  const left = daysBetween(today(), clock.due_date)
  const status = titleize(clock.status ?? 'running')

  return (
    <li className="card p-3">
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold leading-tight text-ink">{titleize(clock.clock_id)}</h3>
        <span className="badge shrink-0 bg-surface text-muted border border-border">{status}</span>
      </div>

      <dl className="mt-1.5 space-y-1 text-xs">
        <div className="flex gap-1">
          <dt className="text-muted">Basis</dt>
          <dd className="font-semibold text-ink">{clock.basis || '—'}</dd>
        </div>
        {clock.consequence ? (
          <div>
            <dt className="text-muted">Consequence of breach</dt>
            <dd className="text-ink">{clock.consequence}</dd>
          </div>
        ) : null}
        <div className="flex gap-1">
          <dt className="text-muted">Period</dt>
          <dd className="text-ink">
            {formatDate(clock.start_date)} <span aria-hidden="true">→</span>{' '}
            <span className="sr-only">to</span>
            <span className="font-semibold">{formatDate(clock.due_date)}</span>
          </dd>
        </div>
      </dl>

      <div className="mt-2">
        <div
          className="h-2 w-full overflow-hidden rounded border border-border bg-surface"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${titleize(clock.clock_id)} elapsed`}
        >
          <div className={`h-full ${meta.bar}`} style={{ width: `${pct}%` }} />
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
          <span className={`badge ${meta.chip}`}>{meta.label}</span>
          <span className="text-muted">{pct}% elapsed</span>
          {left != null && level !== 'closed' ? (
            <span className="text-muted">
              {left >= 0 ? `${left} day${left === 1 ? '' : 's'} left` : `${-left} days overdue`}
            </span>
          ) : null}
        </div>
      </div>

      {isExtendable(clock) && level !== 'closed' && onExtend ? (
        <button type="button" className="btn mt-2 text-xs" onClick={() => onExtend(clock)}>
          Extend…
        </button>
      ) : null}
    </li>
  )
}

/* -------------------------------------------------------------- extend modal */

interface ExtendForm {
  order_date: string
  authority: string
  order_ref: string
  reasons: string
  new_due_date: string
  no_document_reason: string
}

/**
 * Posts EXTENSION_GRANTED per Docs/APIs.md §3.4 "Special payloads":
 * payload {clock_id, authority, order_ref, reasons, new_due_date}, document required.
 */
export function ExtendClockModal({
  caseId,
  clock,
  onClose,
}: {
  caseId: string
  clock: Clock
  onClose: () => void
}) {
  const qc = useQueryClient()
  const dialogRef = useRef<HTMLDivElement>(null)
  const firstRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [form, setForm] = useState<ExtendForm>({
    order_date: today(),
    authority: extendAuthority(clock),
    order_ref: '',
    reasons: '',
    new_due_date: clock.due_date ?? '',
    no_document_reason: '',
  })

  useEffect(() => {
    firstRef.current?.focus()
  }, [])

  const set = <K extends keyof ExtendForm>(k: K, v: ExtendForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  const mutation = useMutation({
    mutationFn: async () => {
      let documentId: string | null = null
      if (file) {
        const fd = new FormData()
        fd.append('file', file)
        fd.append('case_id', caseId)
        fd.append('kind', 'extension_order')
        const doc = await uploadForm<{ id: string }>('/documents', fd)
        documentId = doc.id
      }
      const body: Record<string, unknown> = {
        type: 'EXTENSION_GRANTED',
        occurred_at: form.order_date,
        payload: {
          clock_id: clock.clock_id,
          authority: form.authority,
          order_ref: form.order_ref,
          reasons: form.reasons,
          new_due_date: form.new_due_date,
        },
      }
      if (documentId) body.document_id = documentId
      else body.no_document_reason = form.no_document_reason
      return api('/cases/' + caseId + '/events', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        json: body,
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['case', caseId] })
      onClose()
    },
  })

  const problem = (mutation.error as { problem?: Record<string, unknown> } | null)?.problem
  const lines = problemErrors(problem)
  const valid =
    form.order_date && form.authority && form.reasons.trim() && form.new_due_date &&
    (file != null || form.no_document_reason.trim().length > 0)

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/50 p-4"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="extend-title"
        className="card mt-12 w-full max-w-lg shadow-none"
      >
        <h2 id="extend-title" className="text-base font-bold">
          Extend {titleize(clock.clock_id)}
        </h2>
        <p className="mt-1 text-xs text-muted">
          {clock.basis ? `${clock.basis} — ` : ''}
          {clock.consequence || 'Extension of a statutory period.'} Current due date{' '}
          <span className="font-semibold text-ink">{formatDate(clock.due_date)}</span>. Reasons in
          writing are required by the proviso.
        </p>

        <form
          className="mt-3 grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (valid) mutation.mutate()
          }}
        >
          <Field label="Order date (legal date)">
            <input
              ref={firstRef}
              type="date"
              required
              className={INP}
              value={form.order_date}
              onChange={(e) => set('order_date', e.target.value)}
            />
          </Field>
          <Field label="New due date">
            <input
              type="date"
              required
              className={INP}
              value={form.new_due_date}
              onChange={(e) => set('new_due_date', e.target.value)}
            />
          </Field>
          <Field label="Extending authority">
            <input
              type="text"
              required
              className={INP}
              value={form.authority}
              onChange={(e) => set('authority', e.target.value)}
            />
          </Field>
          <Field label="Order reference">
            <input
              type="text"
              className={INP}
              placeholder="e.g. No. LA/2026/1187"
              value={form.order_ref}
              onChange={(e) => set('order_ref', e.target.value)}
            />
          </Field>
          <Field label="Reasons in writing" full>
            <textarea
              required
              rows={3}
              className={INP}
              value={form.reasons}
              onChange={(e) => set('reasons', e.target.value)}
            />
          </Field>
          <Field label="Extension order (PDF)" full>
            <input
              type="file"
              accept="application/pdf,image/*"
              className={INP}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Field>
          {!file ? (
            <Field label="Reason no document is attached" full>
              <input
                type="text"
                className={INP}
                required
                placeholder="Required when no order copy is uploaded (rules.md C1)"
                value={form.no_document_reason}
                onChange={(e) => set('no_document_reason', e.target.value)}
              />
            </Field>
          ) : null}

          {mutation.isError ? (
            <div className="sm:col-span-2 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
              <p className="font-semibold">
                {(problem?.title as string) || 'Could not record the extension'}
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

          <div className="sm:col-span-2 flex justify-end gap-2 border-t border-border pt-3">
            <button type="button" className="btn" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={!valid || mutation.isPending}>
              {mutation.isPending ? 'Recording…' : 'Record EXTENSION_GRANTED'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function Field({
  label,
  children,
  full,
}: {
  label: string
  children: React.ReactNode
  full?: boolean
}) {
  return (
    <label className={`block text-xs ${full ? 'sm:col-span-2' : ''}`}>
      <span className="mb-0.5 block font-semibold text-muted">{label}</span>
      {children}
    </label>
  )
}
