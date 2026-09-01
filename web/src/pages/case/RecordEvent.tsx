/**
 * RecordEvent (/cases/:id/record) — the five-step wizard of Docs/Frontend.md §3.
 *
 *   1 choose event   GET  /cases/{id}/allowed-events
 *   2 upload         POST /documents (multipart) → POST /documents/{id}/extract
 *                    → poll GET /documents/{id}/extraction
 *   3 review         signed file on the left, extracted fields on the right
 *   4 confirm        preconditions re-checked, then POST /cases/{id}/events
 *   5 committed      seq, hash, clocks changed
 *
 * Nothing here writes to the ledger before step 4: extraction produces a
 * *proposal* that an officer confirms (Docs/rules.md C1).
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  AllowedEvent,
  CONF_CHIP,
  DocumentMeta,
  EventAppended,
  Extraction,
  INP,
  RequirementView,
  asProblem,
  confLevel,
  docKindFor,
  errorText,
  eventIsAllowed,
  extractionSettled,
  fetchAllowedEvents,
  fetchCase,
  fetchEvents,
  fetchSignedFileUrl,
  guardOk,
  guardReason,
  hashPrefix,
  problemErrors,
  requirementsOf,
  satisfiedTypes,
  titleize,
  today,
} from '../../components/case/caseApi'
import { api, formatDate, uploadForm } from '../../lib/api'

type Step = 1 | 2 | 3 | 4 | 5

/** ~60 s of 1.5 s polls before the wizard stops waiting on the extractor. */
const MAX_EXTRACTION_POLLS = 40

const STEP_LABEL: Record<Step, string> = {
  1: 'Choose event',
  2: 'Upload document',
  3: 'Review extraction',
  4: 'Confirm',
  5: 'Committed',
}

interface UploadedDoc extends DocumentMeta {
  duplicate_of?: string | null
}

function isScalar(v: unknown): boolean {
  return v === null || typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'
}

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

export default function RecordEvent() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [step, setStep] = useState<Step>(1)
  const [type, setType] = useState<string | null>(null)
  const [doc, setDoc] = useState<UploadedDoc | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [noDocReason, setNoDocReason] = useState('')
  const meQ = useQuery<{ roles?: string[] }>({ queryKey: ['me'], queryFn: () => api('/auth/me') })
  const canNoDoc = ['COLLECTOR', 'STATE_REVENUE'].some((r) => (meQ.data?.roles ?? []).includes(r))
  const [fields, setFields] = useState<Record<string, unknown>>({})
  const [baseline, setBaseline] = useState<Record<string, unknown>>({})
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [jsonErrors, setJsonErrors] = useState<Record<string, string>>({})
  const [occurredAt, setOccurredAt] = useState<string>(today())
  const [committed, setCommitted] = useState<EventAppended | null>(null)

  /** One idempotency key per commit attempt; regenerated whenever the payload
   *  can still change (Docs/APIs.md §1 — replay must return the original 201). */
  const idemRef = useRef<string>(crypto.randomUUID())
  const seededRef = useRef<string | null>(null)
  const pollsRef = useRef(0)
  const [pollsSpent, setPollsSpent] = useState(false)

  const caseQ = useQuery({ queryKey: ['case', id], queryFn: () => fetchCase(id), enabled: !!id })
  const allowedQ = useQuery({
    queryKey: ['case', id, 'allowed-events'],
    queryFn: () => fetchAllowedEvents(id),
    enabled: !!id,
  })
  const ledgerQ = useQuery({
    queryKey: ['case', id, 'events'],
    queryFn: () => fetchEvents(id, { limit: 500 }),
    enabled: !!id,
  })

  const satisfied = useMemo(
    () => satisfiedTypes(ledgerQ.data?.items ?? []),
    [ledgerQ.data],
  )
  const allowed = allowedQ.data ?? []
  const chosen = allowed.find((a) => a.type === type) ?? null

  /* ------------------------------------------------------------ extraction */

  const extractionQ = useQuery({
    queryKey: ['extraction', doc?.id],
    queryFn: async () => {
      const res = await api<Extraction>(`/documents/${doc?.id}/extraction`)
      pollsRef.current += 1
      if (!extractionSettled(res) && pollsRef.current >= MAX_EXTRACTION_POLLS) setPollsSpent(true)
      return res
    },
    enabled: !!doc?.id,
    // Poll while the job is pending, but never forever: a stuck worker must not
    // trap the officer on step 2 — they can type the fields instead.
    refetchInterval: (query) =>
      extractionSettled(query.state.data) || pollsRef.current >= MAX_EXTRACTION_POLLS
        ? false
        : 1500,
    retry: 1,
  })
  const extraction = extractionQ.data ?? null
  /** "Done waiting" — settled, failed, or we gave up polling. */
  const settled = !doc || extractionSettled(extraction) || extractionQ.isError || pollsSpent

  const fileUrlQ = useQuery({
    queryKey: ['document-file', doc?.id],
    queryFn: () => fetchSignedFileUrl(doc?.id ?? ''),
    enabled: !!doc?.id && step === 3,
    staleTime: 120_000,
  })

  // Seed the review form once per document, from the extraction proposal.
  useEffect(() => {
    if (!doc || !extraction || !extractionSettled(extraction)) return
    if (seededRef.current === doc.id) return
    seededRef.current = doc.id
    const seed = { ...(extraction.fields ?? {}) }
    setFields(seed)
    setBaseline(seed)
    setTouched(new Set())
    const pub = seed.publication_date
    if (typeof pub === 'string' && pub) setOccurredAt(pub)
    const proposed = extraction.proposed_event?.occurred_at
    if (!pub && typeof proposed === 'string' && proposed) setOccurredAt(proposed)
  }, [doc, extraction])

  /* -------------------------------------------------------------- mutations */

  const uploadM = useMutation({
    mutationFn: async (f: File): Promise<UploadedDoc> => {
      const fd = new FormData()
      fd.append('file', f)
      fd.append('case_id', id)
      fd.append('kind', docKindFor(type))
      const uploaded = await uploadForm<UploadedDoc>('/documents', fd)
      // Extraction is best-effort: a failure here must not lose the upload.
      await api(`/documents/${uploaded.id}/extract`, { method: 'POST' }).catch(() => null)
      return uploaded
    },
    onSuccess: (d) => {
      seededRef.current = null
      pollsRef.current = 0
      setPollsSpent(false)
      setDoc(d)
    },
  })

  const commitM = useMutation({
    mutationFn: async (): Promise<EventAppended> => {
      const corrected = Object.keys(fields).filter((k) => !sameValue(fields[k], baseline[k]))
      const confirmed = Object.keys(fields).filter(
        (k) => fields[k] != null && fields[k] !== '' && !corrected.includes(k),
      )
      const payload: Record<string, unknown> = {
        ...fields,
        confirmed_fields: confirmed,
        corrected_fields: corrected,
      }
      const body: Record<string, unknown> = { type, occurred_at: occurredAt, payload }
      if (doc) body.document_id = doc.id
      else if (noDocReason.trim()) body.no_document_reason = noDocReason.trim()
      return api<EventAppended>(`/cases/${id}/events`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idemRef.current },
        json: body,
      })
    },
    onSuccess: (res) => {
      setCommitted(res)
      setStep(5)
      qc.invalidateQueries({ queryKey: ['case', id] })
      qc.invalidateQueries({ queryKey: ['alerts'] })
    },
  })

  /* --------------------------------------------------------------- helpers */

  const goStep = (n: Step) => {
    // Anything below Confirm can still change the payload, so the key is retired.
    if (n < 4) idemRef.current = crypto.randomUUID()
    commitM.reset()
    setStep(n)
  }

  const setField = (key: string, value: unknown) => {
    setFields((f) => ({ ...f, [key]: value }))
    setTouched((t) => new Set(t).add(key))
  }

  const confidence = extraction?.confidence ?? {}
  const lowConfidenceKeys = Object.keys(fields).filter(
    (k) => confLevel(confidence[k]) === 'low',
  )
  const untouchedLowConfidence = lowConfidenceKeys.filter((k) => !touched.has(k))

  const requirements: RequirementView[] = chosen ? requirementsOf(chosen, satisfied) : []
  const preconditionsPass = chosen ? eventIsAllowed(chosen, satisfied) : false

  const canLeaveStep1 = !!chosen && preconditionsPass
  const canLeaveStep2 = (!!doc && settled) || noDocReason.trim().length > 0
  const canLeaveStep3 =
    !!occurredAt && untouchedLowConfidence.length === 0 && Object.keys(jsonErrors).length === 0

  const restart = () => {
    setStep(1)
    setType(null)
    setDoc(null)
    setFile(null)
    setNoDocReason('')
    setFields({})
    setBaseline({})
    setTouched(new Set())
    setJsonErrors({})
    setOccurredAt(today())
    setCommitted(null)
    seededRef.current = null
    pollsRef.current = 0
    setPollsSpent(false)
    idemRef.current = crypto.randomUUID()
    commitM.reset()
    uploadM.reset()
    allowedQ.refetch()
    ledgerQ.refetch()
  }

  if (!id) return <p className="card">No case id in the URL.</p>

  /* ------------------------------------------------------------------ view */

  return (
    <div>
      <header className="card mb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-bold text-ink">Record event</h1>
            <p className="text-sm text-muted">
              <Link to={`/cases/${id}`} className="text-accent underline-offset-2 hover:underline">
                {caseQ.data?.case_no || 'Case'}
              </Link>
              {caseQ.data?.project_name ? ` · ${caseQ.data.project_name}` : ''} · stage{' '}
              <span className="font-semibold text-ink">
                {titleize(caseQ.data?.stage ?? caseQ.data?.case_state?.stage)}
              </span>
            </p>
          </div>
          <Link to={`/cases/${id}`} className="btn">
            Back to case
          </Link>
        </div>

        <ol className="mt-3 flex flex-wrap gap-1" aria-label="Wizard progress">
          {([1, 2, 3, 4, 5] as Step[]).map((n) => (
            <li key={n}>
              <span
                aria-current={step === n ? 'step' : undefined}
                className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs ${
                  step === n
                    ? 'border-accent bg-accent text-white'
                    : step > n
                      ? 'border-ok bg-ok/10 text-[#1B5E20]'
                      : 'border-dashed border-border text-muted'
                }`}
              >
                <span className="font-bold">{step > n ? '✓' : n}</span>
                {STEP_LABEL[n]}
              </span>
            </li>
          ))}
        </ol>
      </header>

      {step === 1 ? (
        <StepChoose
          allowed={allowed}
          loading={allowedQ.isLoading}
          error={allowedQ.error}
          satisfied={satisfied}
          value={type}
          onChange={(t) => {
            setType(t)
            seededRef.current = null
          }}
          onNext={() => goStep(2)}
          canNext={canLeaveStep1}
        />
      ) : null}

      {step === 2 ? (
        <StepUpload
          eventType={type}
          file={file}
          setFile={setFile}
          doc={doc}
          uploading={uploadM.isPending}
          uploadError={uploadM.error}
          onUpload={() => file && uploadM.mutate(file)}
          extraction={extraction}
          extractionLoading={!settled}
          extractionError={extractionQ.error}
          pollsSpent={pollsSpent}
          noDocReason={noDocReason}
          setNoDocReason={setNoDocReason}
          canNoDoc={canNoDoc}
          onBack={() => goStep(1)}
          onNext={() => goStep(3)}
          canNext={canLeaveStep2}
        />
      ) : null}

      {step === 3 ? (
        <StepReview
          fileUrl={fileUrlQ.data ?? null}
          fileUrlError={fileUrlQ.error}
          hasDoc={!!doc}
          extraction={extraction}
          fields={fields}
          baseline={baseline}
          touched={touched}
          setField={setField}
          jsonErrors={jsonErrors}
          setJsonErrors={setJsonErrors}
          occurredAt={occurredAt}
          setOccurredAt={setOccurredAt}
          untouchedLowConfidence={untouchedLowConfidence}
          onBack={() => goStep(2)}
          onNext={() => goStep(4)}
          canNext={canLeaveStep3}
        />
      ) : null}

      {step === 4 ? (
        <StepConfirm
          caseNo={caseQ.data?.case_no ?? null}
          chosen={chosen}
          requirements={requirements}
          preconditionsPass={preconditionsPass}
          refreshing={allowedQ.isFetching}
          onRefresh={() => {
            allowedQ.refetch()
            ledgerQ.refetch()
          }}
          occurredAt={occurredAt}
          doc={doc}
          noDocReason={noDocReason}
          fields={fields}
          baseline={baseline}
          committing={commitM.isPending}
          commitError={commitM.error}
          onBack={() => goStep(3)}
          onCommit={() => commitM.mutate()}
        />
      ) : null}

      {step === 5 && committed ? (
        <StepCommitted
          caseId={id}
          result={committed}
          onRecordAnother={restart}
          onOpenCase={() => navigate(`/cases/${id}`)}
        />
      ) : null}
    </div>
  )
}

/* ══════════════════════════════════════════════════ 1 — choose the event */

function StepChoose({
  allowed,
  loading,
  error,
  satisfied,
  value,
  onChange,
  onNext,
  canNext,
}: {
  allowed: AllowedEvent[]
  loading: boolean
  error: unknown
  satisfied: Set<string>
  value: string | null
  onChange: (t: string) => void
  onNext: () => void
  canNext: boolean
}) {
  return (
    <section className="card">
      <h2 className="text-sm font-bold uppercase tracking-wide text-muted">
        Step 1 · Choose the event to record
      </h2>
      <p className="mt-1 text-xs text-muted">
        Only transitions the rule-set permits from the current stage are listed
        (Docs/rules.md C3). An option whose preconditions are unmet is disabled and says why.
      </p>

      {loading ? (
        <p className="mt-3 text-xs text-muted">Loading permitted events…</p>
      ) : error ? (
        <p role="alert" className="mt-3 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
          Could not load allowed events: {errorText(error)}
        </p>
      ) : allowed.length === 0 ? (
        <p className="mt-3 text-xs text-muted">
          No events can be recorded from this stage — the case is terminal or the rule-set permits
          nothing further.
        </p>
      ) : (
        <fieldset className="mt-3">
          <legend className="sr-only">Permitted events</legend>
          <ul className="space-y-2">
            {allowed.map((ae) => {
              const reqs = requirementsOf(ae, satisfied)
              const missing = reqs.filter((r) => !r.satisfied)
              const guardBad = !guardOk(ae)
              const disabled = missing.length > 0 || guardBad
              const selected = value === ae.type
              return (
                <li key={ae.type}>
                  <label
                    className={`flex items-start gap-2 rounded border p-2 ${
                      disabled
                        ? 'cursor-not-allowed border-border bg-surface opacity-80'
                        : selected
                          ? 'cursor-pointer border-accent bg-accent/5'
                          : 'cursor-pointer border-border bg-bg hover:bg-surface'
                    }`}
                  >
                    <input
                      type="radio"
                      name="event-type"
                      className="mt-0.5 focus:outline-none focus:ring-2 focus:ring-accent"
                      value={ae.type}
                      checked={selected}
                      disabled={disabled}
                      onChange={() => onChange(ae.type)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-baseline gap-2">
                        <span className="font-semibold text-ink">{ae.label || ae.type}</span>
                        {ae.section ? (
                          <span className="badge border border-border bg-surface font-mono text-muted">
                            {ae.section}
                          </span>
                        ) : null}
                        {ae.to_stage ? (
                          <span className="text-xs text-muted">→ {titleize(ae.to_stage)}</span>
                        ) : null}
                      </span>
                      {ae.label && ae.label !== ae.type ? (
                        <span className="block font-mono text-[11px] text-muted">{ae.type}</span>
                      ) : null}

                      {reqs.length ? (
                        <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]">
                          {reqs.map((r) => (
                            <li
                              key={r.key}
                              className={r.satisfied ? 'text-[#1B5E20]' : 'text-[#8C1D18]'}
                            >
                              <span aria-hidden="true">{r.satisfied ? '✓' : '✗'}</span>{' '}
                              <span className="font-mono">{r.key}</span>
                              {r.section ? ` (${r.section})` : ''}
                              <span className="sr-only">
                                {r.satisfied ? ' satisfied' : ' missing'}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : null}

                      {guardBad ? (
                        <p className="mt-1 text-[11px] text-[#8C1D18]">
                          Guard not satisfied
                          {guardReason(ae) ? `: ${guardReason(ae)}` : ''}
                        </p>
                      ) : null}
                      {disabled ? (
                        <p className="mt-1 text-[11px] font-semibold text-[#8C1D18]">
                          Cannot be recorded yet — record the missing prior event first.
                        </p>
                      ) : null}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        </fieldset>
      )}

      <div className="mt-3 flex justify-end border-t border-border pt-3">
        <button type="button" className="btn-primary" disabled={!canNext} onClick={onNext}>
          Next: upload document
        </button>
      </div>
    </section>
  )
}

/* ═══════════════════════════════════════════════════ 2 — upload + extract */

function StepUpload({
  eventType,
  file,
  setFile,
  doc,
  uploading,
  uploadError,
  onUpload,
  extraction,
  extractionLoading,
  extractionError,
  pollsSpent,
  noDocReason,
  setNoDocReason,
  canNoDoc,
  onBack,
  onNext,
  canNext,
}: {
  eventType: string | null
  file: File | null
  setFile: (f: File | null) => void
  doc: UploadedDoc | null
  uploading: boolean
  uploadError: unknown
  onUpload: () => void
  extraction: Extraction | null
  extractionLoading: boolean
  extractionError: unknown
  pollsSpent: boolean
  noDocReason: string
  setNoDocReason: (s: string) => void
  canNoDoc: boolean
  onBack: () => void
  onNext: () => void
  canNext: boolean
}) {
  return (
    <section className="card">
      <h2 className="text-sm font-bold uppercase tracking-wide text-muted">
        Step 2 · Upload the document
      </h2>
      <p className="mt-1 text-xs text-muted">
        Every statutory event requires a document, or an explicit reason recorded by a
        Collector-level role (Docs/rules.md C1). The file is stored under its SHA-256, so an
        identical upload is recognised as a duplicate rather than stored twice.
      </p>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <label className="block text-xs">
            <span className="mb-1 block font-semibold text-muted">
              Document (PDF or image) · kind{' '}
              <span className="font-mono">{docKindFor(eventType)}</span>
            </span>
            <input
              type="file"
              accept="application/pdf,image/*"
              className={INP}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <button
            type="button"
            className="btn-primary mt-2"
            disabled={!file || uploading}
            onClick={onUpload}
          >
            {uploading ? 'Uploading…' : doc ? 'Replace upload' : 'Upload and extract'}
          </button>

          {uploadError ? (
            <p role="alert" className="mt-2 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
              Upload failed: {errorText(uploadError)}
            </p>
          ) : null}

          {doc ? (
            <dl className="mt-3 space-y-1 rounded border border-border bg-surface p-2 text-xs">
              <div>
                <dt className="text-muted">Document id</dt>
                <dd className="break-all font-mono text-ink">{doc.id}</dd>
              </div>
              <div>
                <dt className="text-muted">SHA-256</dt>
                <dd className="break-all font-mono text-ink">{doc.sha256 ?? '—'}</dd>
              </div>
              {doc.duplicate_of ? (
                <p className="mt-1 rounded border border-amber bg-amber/10 p-1.5 text-[#8A5300]">
                  These exact bytes are already on this case as document{' '}
                  <span className="font-mono">{hashPrefix(doc.duplicate_of, 8)}</span>. The existing
                  record is being reused — nothing was stored twice.
                </p>
              ) : null}
            </dl>
          ) : null}
        </div>

        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Extraction</h3>
          {!doc ? (
            <p className="mt-1 text-xs text-muted">Upload a file to run extraction.</p>
          ) : extractionLoading ? (
            <p className="mt-1 text-xs text-muted" role="status">
              Reading the document… (status {extraction?.status ?? 'pending'})
            </p>
          ) : extractionError ? (
            <p role="alert" className="mt-1 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
              Extraction unavailable: {errorText(extractionError)}. You can still type the fields in
              the next step.
            </p>
          ) : (
            <dl className="mt-1 space-y-1 text-xs">
              <div className="flex gap-1">
                <dt className="text-muted">Status</dt>
                <dd className="font-semibold text-ink">{extraction?.status ?? '—'}</dd>
              </div>
              <div className="flex gap-1">
                <dt className="text-muted">Fields read</dt>
                <dd className="text-ink">{Object.keys(extraction?.fields ?? {}).length}</dd>
              </div>
              {extraction?.proposed_event?.type ? (
                <div className="flex gap-1">
                  <dt className="text-muted">Proposed event</dt>
                  <dd className="font-mono text-ink">{extraction.proposed_event.type}</dd>
                </div>
              ) : null}
              {extraction?.ocr ? (
                <p className="text-[11px] text-accent2">Read through OCR — check every field.</p>
              ) : null}
              {pollsSpent ? (
                <p className="mt-1 rounded border border-amber bg-amber/10 p-1.5 text-[11px] text-[#8A5300]">
                  The extractor did not finish in a minute. The document is stored; continue and
                  type the fields yourself.
                </p>
              ) : null}
            </dl>
          )}

          <div className="mt-4 border-t border-border pt-3">
            <label className="block text-xs">
              <span className="mb-1 block font-semibold text-muted">
                Or record without a document — reason (audited)
              </span>
              <input
                type="text"
                className={INP}
                placeholder="e.g. gazette copy awaited; entry made on the Collector's order"
                value={noDocReason}
                onChange={(e) => setNoDocReason(e.target.value)}
                disabled={!!doc || !canNoDoc}
              />
            </label>
            <p className="mt-1 text-[11px] text-muted">
              Permitted only for Collector-level roles; the API rejects a statutory event with
              neither a document nor a reason (<span className="font-mono">document_required</span>).
            </p>
          </div>
        </div>
      </div>

      <div className="mt-3 flex justify-between border-t border-border pt-3">
        <button type="button" className="btn" onClick={onBack}>
          Back
        </button>
        <button type="button" className="btn-primary" disabled={!canNext} onClick={onNext}>
          Next: review extraction
        </button>
      </div>
    </section>
  )
}

/* ════════════════════════════════════════════════════════ 3 — review */

function StepReview({
  fileUrl,
  fileUrlError,
  hasDoc,
  extraction,
  fields,
  baseline,
  touched,
  setField,
  jsonErrors,
  setJsonErrors,
  occurredAt,
  setOccurredAt,
  untouchedLowConfidence,
  onBack,
  onNext,
  canNext,
}: {
  fileUrl: string | null
  fileUrlError: unknown
  hasDoc: boolean
  extraction: Extraction | null
  fields: Record<string, unknown>
  baseline: Record<string, unknown>
  touched: Set<string>
  setField: (k: string, v: unknown) => void
  jsonErrors: Record<string, string>
  setJsonErrors: (f: Record<string, string>) => void
  occurredAt: string
  setOccurredAt: (s: string) => void
  untouchedLowConfidence: string[]
  onBack: () => void
  onNext: () => void
  canNext: boolean
}) {
  const confidence = extraction?.confidence ?? {}
  const keys = Object.keys(fields)

  const setJsonError = (key: string, msg: string | null) => {
    const next = { ...jsonErrors }
    if (msg) next[key] = msg
    else delete next[key]
    setJsonErrors(next)
  }

  return (
    <section className="card">
      <h2 className="text-sm font-bold uppercase tracking-wide text-muted">
        Step 3 · Review what was read
      </h2>
      <p className="mt-1 text-xs text-muted">
        Confidence bands: green ≥ 0.9, amber 0.7–0.9, red &lt; 0.7. Every red field must be
        checked before you can continue. Edited values are marked <em>corrected</em> and travel
        with the event.
      </p>

      {untouchedLowConfidence.length ? (
        <p className="mt-2 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]" role="status">
          Confirm these low-confidence fields before continuing:{' '}
          <span className="font-mono">{untouchedLowConfidence.join(', ')}</span>
        </p>
      ) : null}

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        {/* left — the document itself */}
        <div className="rounded border border-border">
          <div className="flex items-center justify-between border-b border-border bg-surface px-2 py-1">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Source document</h3>
            {fileUrl ? (
              <a
                href={fileUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-accent underline-offset-2 hover:underline"
              >
                Open in a new tab
              </a>
            ) : null}
          </div>
          {!hasDoc ? (
            <p className="p-3 text-xs text-muted">
              No document was attached — the fields on the right are yours to enter.
            </p>
          ) : fileUrlError ? (
            <p role="alert" className="p-3 text-xs text-[#8C1D18]">
              Could not fetch the signed URL: {errorText(fileUrlError)}
            </p>
          ) : fileUrl ? (
            <iframe title="Uploaded document" src={fileUrl} className="h-[32rem] w-full bg-surface" />
          ) : (
            <p className="p-3 text-xs text-muted">Fetching a signed link…</p>
          )}
        </div>

        {/* right — the editable proposal */}
        <div>
          <label className="block text-xs">
            <span className="mb-1 block font-semibold text-muted">
              Occurred at (legal date — clocks run on this, not on today)
            </span>
            <input
              type="date"
              required
              className={INP}
              value={occurredAt}
              onChange={(e) => setOccurredAt(e.target.value)}
            />
          </label>
          {typeof fields.publication_date === 'string' && fields.publication_date ? (
            <p className="mt-0.5 text-[11px] text-muted">
              Defaulted to the extracted publication date {formatDate(String(fields.publication_date))}.
            </p>
          ) : null}

          {keys.length === 0 ? (
            <p className="mt-3 rounded border border-border bg-surface p-2 text-xs text-muted">
              Nothing was extracted. Add the payload fields the event needs — the API validates them
              against the rule-set on commit.
            </p>
          ) : (
            <ul className="mt-3 space-y-3">
              {keys.map((k) => {
                const value = fields[k]
                const level = confLevel(confidence[k])
                const chip = CONF_CHIP[level]
                const corrected = !sameValue(value, baseline[k])
                const scalar = isScalar(value)
                const dateish = /(^|_)date$/.test(k) && typeof value === 'string'
                const inputId = `field-${k}`
                return (
                  <li key={k}>
                    <div className="mb-0.5 flex flex-wrap items-center gap-2">
                      <label htmlFor={inputId} className="text-xs font-semibold text-ink">
                        {titleize(k)}
                      </label>
                      <span className={`badge ${chip.cls}`}>
                        {chip.label}
                        {confidence[k] != null ? ` ${Number(confidence[k]).toFixed(2)}` : ''}
                      </span>
                      {corrected ? (
                        <span className="badge border border-accent2 bg-accent2/10 text-[#7A4E09]">
                          corrected
                        </span>
                      ) : null}
                      {level === 'low' && !touched.has(k) ? (
                        <span className="text-[11px] text-[#8C1D18]">must be checked</span>
                      ) : null}
                    </div>

                    {scalar ? (
                      <input
                        id={inputId}
                        type={dateish ? 'date' : 'text'}
                        className={INP}
                        value={value == null ? '' : String(value)}
                        onChange={(e) => setField(k, e.target.value)}
                      />
                    ) : (
                      <>
                        <textarea
                          id={inputId}
                          rows={Math.min(10, JSON.stringify(value, null, 2).split('\n').length)}
                          className={`${INP} font-mono text-[11px]`}
                          defaultValue={JSON.stringify(value, null, 2)}
                          onChange={(e) => {
                            try {
                              const parsed: unknown = JSON.parse(e.target.value)
                              setJsonError(k, null)
                              setField(k, parsed)
                            } catch {
                              setJsonError(k, 'Not valid JSON')
                            }
                          }}
                        />
                        {jsonErrors[k] ? (
                          <p className="text-[11px] text-[#8C1D18]">{jsonErrors[k]}</p>
                        ) : null}
                      </>
                    )}

                    {level === 'low' && !touched.has(k) ? (
                      <button
                        type="button"
                        className="btn mt-1 px-2 py-0.5 text-[11px]"
                        onClick={() => setField(k, value)}
                      >
                        Value is correct as read
                      </button>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          )}

          {extraction?.warnings?.length ? (
            <ul className="mt-3 list-disc pl-4 text-[11px] text-[#8A5300]">
              {extraction.warnings.map((w, i) => (
                <li key={i}>{String(w)}</li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>

      <div className="mt-3 flex justify-between border-t border-border pt-3">
        <button type="button" className="btn" onClick={onBack}>
          Back
        </button>
        <button type="button" className="btn-primary" disabled={!canNext} onClick={onNext}>
          Next: confirm
        </button>
      </div>
    </section>
  )
}

/* ═══════════════════════════════════════════════════════ 4 — confirm */

function StepConfirm({
  caseNo,
  chosen,
  requirements,
  preconditionsPass,
  refreshing,
  onRefresh,
  occurredAt,
  doc,
  noDocReason,
  fields,
  baseline,
  committing,
  commitError,
  onBack,
  onCommit,
}: {
  caseNo: string | null
  chosen: AllowedEvent | null
  requirements: RequirementView[]
  preconditionsPass: boolean
  refreshing: boolean
  onRefresh: () => void
  occurredAt: string
  doc: UploadedDoc | null
  noDocReason: string
  fields: Record<string, unknown>
  baseline: Record<string, unknown>
  committing: boolean
  commitError: unknown
  onBack: () => void
  onCommit: () => void
}) {
  const corrected = Object.keys(fields).filter((k) => !sameValue(fields[k], baseline[k]))
  const problem = asProblem(commitError)
  const lines = problemErrors(problem)

  return (
    <section className="card">
      <h2 className="text-sm font-bold uppercase tracking-wide text-muted">
        Step 4 · Confirm and commit
      </h2>
      <p className="mt-1 text-xs text-muted">
        Committing appends one immutable event to the case ledger. Corrections afterwards are
        compensating events, never edits (Docs/rules.md C1).
      </p>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <dl className="space-y-1 rounded border border-border bg-surface p-3 text-xs">
          <Row label="Case" value={caseNo ?? '—'} />
          <Row label="Event" value={chosen?.type ?? '—'} mono />
          <Row label="Section" value={chosen?.section ?? '—'} />
          <Row label="Occurred at" value={formatDate(occurredAt)} />
          <Row
            label="Document"
            value={doc ? `${doc.id} (sha256 ${hashPrefix(doc.sha256, 12)})` : `none — ${noDocReason || 'no reason given'}`}
            mono={!!doc}
          />
          <Row label="Payload fields" value={String(Object.keys(fields).length)} />
          <Row label="Corrected" value={corrected.length ? corrected.join(', ') : 'none'} mono />
        </dl>

        <div className="rounded border border-border p-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
              Preconditions
            </h3>
            <button type="button" className="btn px-2 py-0.5 text-[11px]" onClick={onRefresh} disabled={refreshing}>
              {refreshing ? 'Re-checking…' : 'Re-check'}
            </button>
          </div>
          {requirements.length === 0 ? (
            <p className="mt-2 text-xs text-muted">
              This event has no prior-event requirements in the rule-set.
            </p>
          ) : (
            <ul className="mt-2 space-y-1 text-xs">
              {requirements.map((r) => (
                <li key={r.key} className={r.satisfied ? 'text-[#1B5E20]' : 'text-[#8C1D18]'}>
                  <span aria-hidden="true">{r.satisfied ? '✓' : '✗'}</span>{' '}
                  <span className="font-mono">{r.key}</span>
                  {r.section ? ` — ${r.section}` : ''}
                  <span className="sr-only">{r.satisfied ? ' satisfied' : ' missing'}</span>
                </li>
              ))}
            </ul>
          )}
          {chosen && !guardOk(chosen) ? (
            <p className="mt-2 text-xs text-[#8C1D18]">
              Guard not satisfied{guardReason(chosen) ? `: ${guardReason(chosen)}` : ''}
            </p>
          ) : null}
          {!preconditionsPass ? (
            <p className="mt-2 text-xs font-semibold text-[#8C1D18]">
              Commit is blocked until the missing items above are recorded.
            </p>
          ) : null}
        </div>
      </div>

      {commitError ? (
        <div role="alert" className="mt-3 rounded border border-red bg-red/10 p-3 text-xs text-[#8C1D18]">
          <p className="text-sm font-bold">
            {(problem?.title as string) || 'The event was not recorded'}
          </p>
          <p className="mt-0.5">{errorText(commitError)}</p>
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
            <p className="mt-1 font-mono text-[11px]">rule-set: {String(problem.ruleset_ref)}</p>
          ) : null}
          {problem?.type ? (
            <p className="mt-1 text-[11px]">
              error type <span className="font-mono">{String(problem.type)}</span>
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="mt-3 flex justify-between border-t border-border pt-3">
        <button type="button" className="btn" onClick={onBack}>
          Back
        </button>
        <button
          type="button"
          className="btn-primary"
          disabled={!preconditionsPass || committing || !chosen}
          onClick={onCommit}
        >
          {committing ? 'Committing…' : `Commit ${chosen?.type ?? 'event'}`}
        </button>
      </div>
    </section>
  )
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-2">
      <dt className="w-32 shrink-0 text-muted">{label}</dt>
      <dd className={`min-w-0 break-all text-ink ${mono ? 'font-mono' : ''}`}>{value}</dd>
    </div>
  )
}

/* ═════════════════════════════════════════════════════ 5 — committed */

function StepCommitted({
  caseId,
  result,
  onRecordAnother,
  onOpenCase,
}: {
  caseId: string
  result: EventAppended
  onRecordAnother: () => void
  onOpenCase: () => void
}) {
  const changed = result.clocks_changed ?? []
  return (
    <section className="card border-ok">
      <h2 className="text-base font-bold text-[#1B5E20]">Event committed to the ledger</h2>
      <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-4">
        <Stat label="Sequence" value={String(result.seq)} />
        <Stat label="Event id" value={result.id} mono />
        <Stat label="Hash" value={hashPrefix(result.hash, 16)} mono />
        <Stat label="Stage now" value={titleize(result.stage)} />
      </dl>

      <h3 className="mt-4 text-sm font-bold uppercase tracking-wide text-muted">Clocks changed</h3>
      {changed.length === 0 ? (
        <p className="mt-1 text-xs text-muted">No clock started, closed or moved.</p>
      ) : (
        <div className="mt-1 overflow-x-auto">
          <table className="gov">
            <thead>
              <tr>
                <th scope="col">Clock</th>
                <th scope="col">Basis</th>
                <th scope="col">Status</th>
                <th scope="col">Start</th>
                <th scope="col">Due</th>
                <th scope="col">Closed on</th>
              </tr>
            </thead>
            <tbody>
              {changed.map((c, i) => (
                <tr key={`${c.clock_id}-${i}`}>
                  <td className="font-semibold">{titleize(c.clock_id)}</td>
                  <td className="font-mono text-[11px]">{c.basis ?? '—'}</td>
                  <td>{titleize(c.status)}</td>
                  <td>{formatDate(c.start_date)}</td>
                  <td className="font-semibold">{formatDate(c.due_date)}</td>
                  <td>{formatDate(c.closed_on)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-3">
        <button type="button" className="btn-primary" onClick={onOpenCase}>
          Back to the case
        </button>
        <button type="button" className="btn" onClick={onRecordAnother}>
          Record another event
        </button>
        <Link to={`/cases/${caseId}`} className="btn">
          Open ledger
        </Link>
      </div>
    </section>
  )
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded border border-border bg-surface p-2">
      <dt className="text-[11px] uppercase tracking-wide text-muted">{label}</dt>
      <dd className={`mt-0.5 break-all font-semibold text-ink ${mono ? 'font-mono text-[11px]' : ''}`}>
        {value}
      </dd>
    </div>
  )
}
