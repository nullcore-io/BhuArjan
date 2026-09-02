/**
 * Shared types, clock maths and fetch helpers for the case page.
 *
 * Contract: Docs/APIs.md §3.3–3.7 (base /api/v1, prepended by `api()`).
 * Fields are typed optional where the backend contract leaves room, so a
 * partially-implemented endpoint degrades to "—" instead of a white screen.
 */
import { api, getDemoDate } from '../../lib/api'

/* ------------------------------------------------------------------ types */

export type ClockLevel = 'ok' | 'amber' | 'red' | 'breached' | 'lapsed' | 'closed' | 'suspended'

/** GET /cases/{id}/clocks */
export interface Clock {
  clock_id: string
  basis?: string | null
  consequence?: string | null
  start_date?: string | null
  due_date?: string | null
  status?: string | null
  elapsed_pct?: number | null
  extendable?: boolean | { by?: string; reasons_required?: boolean } | null
  kind?: string | null
  closed_on?: string | null
  suspended_days?: number | null
}

/** events row (Docs/Backend.md §2) */
export interface LedgerEvent {
  seq: number
  id: string
  case_id?: string
  type: string
  occurred_at: string
  recorded_at?: string | null
  actor_id?: string | null
  actor_name?: string | null
  actor?: string | null
  payload?: Record<string, unknown> | null
  document_id?: string | null
  prev_hash?: string | null
  hash?: string | null
}

export interface CaseState {
  stage?: string | null
  as_of_seq?: number | null
  area_notified_ha?: number | string | null
  area_acquired_ha?: number | string | null
  comp_assessed?: number | string | null
  comp_paid?: number | string | null
  families_affected?: number | null
  families_displaced?: number | null
  possession_pct?: number | string | null
  risk_score?: number | string | null
  updated_at?: string | null
}

/** GET /cases/{id} → case + case_state + clocks[] + last 20 events */
export interface CaseDetail {
  id: string
  case_no?: string | null
  project_id?: string | null
  project_name?: string | null
  project?: { id?: string; name?: string; sector?: string | null } | null
  district_id?: string | null
  district_name?: string | null
  statute_track?: string | null
  ruleset_version?: string | null
  stage?: string | null
  risk_score?: number | string | null
  case_state?: CaseState | null
  clocks?: Clock[] | null
  events?: LedgerEvent[] | null
}

/** GET /cases/{id}/allowed-events → [{type, section, requires[], guard_status}] */
export interface AllowedEvent {
  type: string
  section?: string | null
  requires?: Array<string | Record<string, unknown>> | null
  guard_status?: string | boolean | Record<string, unknown> | null
  label?: string | null
  to_stage?: string | null
  document_required?: boolean | null
}

/** GET /cases/{id}/integrity */
export interface Integrity {
  verified?: boolean | null
  checked_at?: string | null
  head_hash?: string | null
  detail?: string | null
}

/** GET /cases/{id}/risk */
export interface RiskInfo {
  score?: number | string | null
  drivers?: Array<string | { label?: string; detail?: string; weight?: number }> | null
}

/** GET /cases/{id}/compensation */
export interface CompensationLine {
  id?: string
  parcel_id?: string | null
  parcel_label?: string | null
  survey_no?: string | null
  ulpin?: string | null
  owner_ref?: string | null
  market_value_paise?: number | string | null
  mv_method?: string | null
  factor?: number | string | null
  assets_paise?: number | string | null
  solatium_paise?: number | string | null
  interest_paise?: number | string | null
  total_paise?: number | string | null
  paid_paise?: number | string | null
  outstanding_paise?: number | string | null
}

export interface CompensationSummary {
  lines?: CompensationLine[] | null
  assessed_total?: number | string | null
  paid_total?: number | string | null
  outstanding?: number | string | null
  interest_accrued?: number | string | null
}

/* ------------------------------------------------------------------ R&R ---- */

/**
 * One Second/Third Schedule head on one family.
 *
 * The server writes only `due` and `delivered` (api/app/domain/rr/schedules.py:
 * "an entitlement an officer decides does not apply is a determination that belongs
 * in the ledger, not a silent third state"). `overdue` is a *view* the R&R tab
 * derives from the s.38(1) R&R clocks — it is typed here because the field is read
 * tolerantly if a later build starts sending it.
 */
export interface EntitlementCell {
  status?: string | null
  delivered_on?: string | null
  evidence_document_id?: string | null
}

/** One row of `GET /cases/{id}/families`. Names appear only under `head`, and only
 *  when the caller had both a permitted role and a stated purpose (Docs/rules.md C5). */
export interface Family {
  id: string
  case_id?: string | null
  /** Masked reference — initials, safe to print. Always present. */
  ref?: string | null
  category?: string | null
  displaced?: boolean | null
  sc_st?: boolean | null
  enumerated_on?: string | null
  synthetic?: boolean | null
  /** "masked" | "unlocked" — the server's own word for what it sent. */
  pii?: string | null
  /** Decrypted head-of-family fields; present only on an unlocked (audited) read. */
  head?: Record<string, unknown> | null
  /** `{head_id: cell}`. `rr_entitlements` is accepted as an alias. */
  entitlements?: Record<string, EntitlementCell> | EntitlementCell[] | null
  rr_entitlements?: Record<string, EntitlementCell> | EntitlementCell[] | null
  heads_total?: number | null
  heads_delivered?: number | null
  heads_due?: number | null
  delivered_pct?: number | null
}

/** GET /cases/{id}/families → masked register (+ `masked_reason` when it is masked). */
export interface FamilyPage {
  items?: Family[] | null
  families?: Family[] | null
  total?: number | null
  next_cursor?: string | null
  pii?: string | null
  purpose?: string | null
  masked_reason?: string | null
  case_id?: string | null
  case_no?: string | null
}

/** One head in `GET /cases/{id}/rr/summary`. Counts arrive nested under `counts`;
 *  flat `due`/`delivered`/`overdue` are read too, so either shape renders. */
export interface RRHead {
  head: string
  label?: string | null
  kind?: string | null
  basis?: string | null
  amount?: string | null
  applies_to?: string | null
  counts?: { due?: number | null; delivered?: number | null; overdue?: number | null } | null
  due?: number | null
  delivered?: number | null
  overdue?: number | null
  families?: number | null
  delivered_pct?: number | null
}

/** GET /cases/{id}/rr/summary */
export interface RRSummary {
  case_id?: string | null
  case_no?: string | null
  families?: { total?: number | null; displaced?: number | null; sc_st?: number | null } | null
  heads?: RRHead[] | null
  status_counts?: { due?: number | null; delivered?: number | null } | null
  rr_progress_pct?: number | null
  /** The s.38(1) R&R clocks — same shape as every other clock on the case. */
  clocks?: Clock[] | null
  as_of_seq?: number | null
  as_of_date?: string | null
  schedule_note?: string | null
}

/** POST /families/{id}/entitlements/{head}/deliver → 200 */
export interface DeliveryResult {
  family?: Family | null
  head?: (RRHead & EntitlementCell) | null
  seq?: number | null
  stage?: string | null
}

/** GET /alerts */
export interface CaseAlert {
  id: string
  case_id?: string | null
  case_no?: string | null
  clock_id?: string | null
  level?: string | null
  raised_at?: string | null
  escalated_to_role?: string | null
  acknowledged_by?: string | null
  acknowledged_at?: string | null
  due_date?: string | null
}

/** GET /documents/{id} */
export interface DocumentMeta {
  id: string
  case_id?: string | null
  kind?: string | null
  storage_key?: string | null
  sha256?: string | null
  mime?: string | null
  pages?: number | null
  uploaded_by?: string | null
  uploaded_at?: string | null
  supersedes_id?: string | null
  version?: number | null
  extraction_status?: string | null
  duplicate_of?: string | null
  filename?: string | null
}

/** GET /documents/{id}/extraction */
export interface Extraction {
  status?: string | null
  fields?: Record<string, unknown> | null
  confidence?: Record<string, number> | null
  source_spans?: Record<string, unknown> | null
  proposed_event?: { type?: string; occurred_at?: string; payload?: Record<string, unknown> } | null
  error?: string | null
  ocr?: boolean | null
  engine?: string | null
  pages?: number | null
  /** Extractor notes, e.g. "publication_date read from masthead, not the dateline". */
  warnings?: unknown[] | null
  document_id?: string | null
}

/** GET /cases/{id}/parcels → GeoJSON FeatureCollection */
export interface ParcelProps {
  survey_no?: string | null
  ulpin?: string | null
  area_ha?: number | string | null
  status?: string | null
  village_lgd?: string | null
  land_type?: string | null
  [k: string]: unknown
}

/** POST /cases/{id}/events → 201 */
export interface EventAppended {
  seq: number
  id: string
  hash?: string | null
  prev_hash?: string | null
  stage?: string | null
  clocks_changed?: Array<
    Clock & { status?: string | null; closed_on?: string | null }
  > | null
}

/* ------------------------------------------------------------ date helpers */

/** "Today" honours the demo date so the UI agrees with the server's clocks. */
export function today(): string {
  return getDemoDate() || new Date().toISOString().slice(0, 10)
}

export function formatTs(ts?: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return String(ts)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** Whole days from `a` to `b` (negative when b precedes a). */
export function daysBetween(a?: string | null, b?: string | null): number | null {
  if (!a || !b) return null
  const ta = Date.parse(a)
  const tb = Date.parse(b)
  if (!Number.isFinite(ta) || !Number.isFinite(tb)) return null
  return Math.round((tb - ta) / 86_400_000)
}

export function titleize(s?: string | null): string {
  if (!s) return '—'
  return s.replace(/_/g, ' ')
}

export function hashPrefix(h?: string | null, n = 12): string {
  if (!h) return '—'
  const clean = h.replace(/^\\?x/, '')
  return clean.length > n ? `${clean.slice(0, n)}…` : clean
}

function clamp(n: number, lo: number, hi: number): number {
  return n < lo ? lo : n > hi ? hi : n
}

/* ----------------------------------------------------------- clock helpers */

/** Fraction 0..1. The server's `elapsed_pct` is always 0–100 (see /cases/{id}/clocks). */
export function clockElapsed(c: Clock): number {
  const raw = c.elapsed_pct
  if (raw != null && Number.isFinite(Number(raw))) {
    return clamp(Number(raw) / 100, 0, 1)
  }
  const s = Date.parse(c.start_date ?? '')
  const d = Date.parse(c.due_date ?? '')
  const t = Date.parse(today())
  if (!Number.isFinite(s) || !Number.isFinite(d) || d <= s || !Number.isFinite(t)) return 0
  return clamp((t - s) / (d - s), 0, 1)
}

/**
 * Thresholds per Docs/rules.md C2: amber 75%, red 90%, black on breach.
 * Terminal statuses from the server always win over the computed fraction.
 */
export function clockLevel(c: Clock): ClockLevel {
  const st = (c.status ?? 'running').toLowerCase()
  if (st === 'closed') return 'closed'
  if (st === 'lapsed') return 'lapsed'
  if (st === 'breached') return 'breached'
  if (st === 'suspended') return 'suspended'
  const e = clockElapsed(c)
  if (e >= 1) return 'breached'
  if (e >= 0.9) return 'red'
  if (e >= 0.75) return 'amber'
  return 'ok'
}

/** Colour is never the only signal — every level carries `label` too (GIGW/WCAG). */
export const CLOCK_LEVEL: Record<ClockLevel, { label: string; bar: string; chip: string }> = {
  ok: { label: 'On time', bar: 'bg-ok', chip: 'bg-ok/10 text-[#1B5E20] border border-ok' },
  amber: {
    label: 'Due soon — 75% elapsed',
    bar: 'bg-amber',
    chip: 'bg-amber/10 text-[#8A5300] border border-amber',
  },
  red: {
    label: 'Critical — 90% elapsed',
    bar: 'bg-red',
    chip: 'bg-red/10 text-[#8C1D18] border border-red',
  },
  breached: {
    label: 'Breached',
    bar: 'bg-breached',
    chip: 'bg-breached text-white border border-breached',
  },
  lapsed: {
    label: 'Lapsed',
    bar: 'bg-breached',
    chip: 'bg-breached text-white border border-breached',
  },
  closed: { label: 'Closed', bar: 'bg-muted', chip: 'bg-surface text-muted border border-border' },
  suspended: {
    label: 'Suspended (stay)',
    bar: 'bg-accent2',
    chip: 'bg-accent2/10 text-[#7A4E09] border border-accent2',
  },
}

export function isExtendable(c: Clock): boolean {
  const e = c.extendable
  if (e == null) return false
  if (typeof e === 'boolean') return e
  return true
}

export function extendAuthority(c: Clock): string {
  const e = c.extendable
  if (e && typeof e === 'object' && typeof e.by === 'string') return titleize(e.by)
  return 'Appropriate Government'
}

/* ----------------------------------------------------------- page fetching */

export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

/** Accepts `{items|events|alerts|results, next_cursor}` or a bare array. */
export function normalizePage<T>(raw: unknown, ...keys: string[]): Page<T> {
  if (Array.isArray(raw)) return { items: raw as T[], next_cursor: null }
  const o = (raw ?? {}) as Record<string, unknown>
  for (const k of ['items', ...keys, 'results', 'data']) {
    const v = o[k]
    if (Array.isArray(v)) return { items: v as T[], next_cursor: (o.next_cursor as string) ?? null }
  }
  return { items: [], next_cursor: (o.next_cursor as string) ?? null }
}

export async function fetchEvents(
  caseId: string,
  opts: { cursor?: string | null; limit?: number; type?: string } = {},
): Promise<Page<LedgerEvent>> {
  const qs = new URLSearchParams()
  if (opts.limit) qs.set('limit', String(opts.limit))
  if (opts.cursor) qs.set('cursor', opts.cursor)
  if (opts.type) qs.set('type', opts.type)
  const suffix = qs.toString() ? `?${qs}` : ''
  const raw = await api<unknown>(`/cases/${caseId}/events${suffix}`)
  const page = normalizePage<LedgerEvent>(raw, 'events')
  page.items.sort((a, b) => Number(b.seq ?? 0) - Number(a.seq ?? 0))
  return page
}

export async function fetchAlerts(): Promise<Page<CaseAlert>> {
  const raw = await api<unknown>('/alerts?limit=200')
  return normalizePage<CaseAlert>(raw, 'alerts')
}

/** GET /documents/{id}/file → short-lived signed URL. */
export async function fetchSignedFileUrl(documentId: string): Promise<string> {
  const res = await api<unknown>(`/documents/${documentId}/file`)
  if (typeof res === 'string') return res
  const o = (res ?? {}) as Record<string, unknown>
  const url = o.url ?? o.signed_url ?? o.href ?? o.location
  return typeof url === 'string' ? url : ''
}

/**
 * Open a document in a new tab. The blank tab is opened synchronously (inside
 * the click) so pop-up blockers do not eat it while the signed URL is fetched.
 */
export async function openDocumentInTab(documentId: string): Promise<void> {
  const tab = window.open('', '_blank')
  try {
    const url = await fetchSignedFileUrl(documentId)
    if (!url) throw new Error('No signed URL returned for this document')
    if (tab) tab.location.href = url
    else window.open(url, '_blank', 'noopener,noreferrer')
  } catch (err) {
    tab?.close()
    throw err
  }
}

/* ----------------------------------------------- allowed-event preconditions */

export interface RequirementView {
  key: string
  section?: string
  satisfied: boolean
}

function requirementKey(r: Record<string, unknown>): string {
  const k = r.type ?? r.missing ?? r.event_type ?? r.key ?? r.name ?? r.id
  return typeof k === 'string' ? k : JSON.stringify(r)
}

/**
 * `requires[]` items arrive either as plain event-type strings or as objects
 * carrying their own satisfaction flag. Plain strings are checked against the
 * event types already in the ledger.
 */
export function requirementsOf(ae: AllowedEvent, satisfiedTypes: Set<string>): RequirementView[] {
  const list = Array.isArray(ae.requires) ? ae.requires : []
  return list.map((r) => {
    if (typeof r === 'string') return { key: r, satisfied: satisfiedTypes.has(r) }
    const key = requirementKey(r)
    const flag = r.satisfied ?? r.met ?? r.ok ?? r.present
    const satisfied =
      typeof flag === 'boolean' ? flag : 'missing' in r ? false : satisfiedTypes.has(key)
    const section = typeof r.section === 'string' ? r.section : undefined
    return { key, section, satisfied }
  })
}

const GUARD_OK = new Set(['ok', 'pass', 'passed', 'satisfied', 'allowed', 'true', 'green'])

export function guardOk(ae: AllowedEvent): boolean {
  const g = ae.guard_status
  if (g == null) return true
  if (typeof g === 'boolean') return g
  if (typeof g === 'string') return GUARD_OK.has(g.toLowerCase())
  const o = g as Record<string, unknown>
  const flag = o.ok ?? o.passed ?? o.satisfied
  if (typeof flag === 'boolean') return flag
  if (typeof o.status === 'string') return GUARD_OK.has(o.status.toLowerCase())
  return true
}

export function guardReason(ae: AllowedEvent): string | null {
  const g = ae.guard_status
  if (g == null || typeof g === 'boolean') return null
  if (typeof g === 'string') return GUARD_OK.has(g.toLowerCase()) ? null : titleize(g)
  const o = g as Record<string, unknown>
  const r = o.reason ?? o.detail ?? o.message
  return typeof r === 'string' ? r : null
}

export function eventIsAllowed(ae: AllowedEvent, satisfiedTypes: Set<string>): boolean {
  return guardOk(ae) && requirementsOf(ae, satisfiedTypes).every((r) => r.satisfied)
}

/* --------------------------------------------------------- problem+json ---- */

export interface ProblemLine {
  label: string
  detail?: string
}

/** Flattens RFC 7807 `errors[]` (Docs/APIs.md §1) into printable lines. */
export function problemErrors(problem: unknown): ProblemLine[] {
  const p = (problem ?? {}) as Record<string, unknown>
  const errs = p.errors
  if (!Array.isArray(errs)) return []
  return errs.map((e): ProblemLine => {
    if (typeof e === 'string') return { label: e }
    const o = e as Record<string, unknown>
    const label = o.missing ?? o.field ?? o.loc ?? o.name ?? o.type ?? 'error'
    const detail = o.section ?? o.message ?? o.detail ?? o.msg
    return {
      label: typeof label === 'string' ? label : JSON.stringify(label),
      detail: typeof detail === 'string' ? detail : undefined,
    }
  })
}

/** Pulls the RFC 7807 body off an ApiError without importing its class. */
export function asProblem(err: unknown): Record<string, unknown> | null {
  const p = (err as { problem?: unknown } | null)?.problem
  return p && typeof p === 'object' ? (p as Record<string, unknown>) : null
}

export function errorText(err: unknown): string {
  const p = asProblem(err)
  const detail = p?.detail ?? p?.title
  if (typeof detail === 'string') return detail
  return err instanceof Error ? err.message : 'Request failed'
}

/* ------------------------------------------------------------ form styling */

/**
 * Shared input skin. Kept as a constant rather than a CSS class so the case
 * screens do not depend on a utility landing in the shared stylesheet.
 * Focus ring is always visible — GIGW/WCAG keyboard requirement.
 */
export const INP =
  'w-full rounded border border-border bg-bg px-2 py-1 text-sm text-ink ' +
  'focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent ' +
  'disabled:bg-surface disabled:text-muted'

/* -------------------------------------------------------- statutory stages */

export interface StageStep {
  stage: string
  label: string
  /** Section shown under the stage name; statutory references stay visible. */
  section?: string
  /** Event types whose occurrence puts the case into this stage. */
  entry: string[]
  /** Clock whose due date is this stage's statutory deadline. */
  clockId?: string
}

const RFCTLARR_STAGES: StageStep[] = [
  {
    stage: 'PROPOSED',
    label: 'Proposal',
    entry: ['PROJECT_CREATED', 'PROPOSAL_SUBMITTED', 'PROPOSAL_APPROVED'],
  },
  { stage: 'SIA', label: 'Social Impact Assessment', section: 's.4(1)', entry: ['SIA_NOTIFIED'] },
  {
    stage: 'APPRAISED',
    label: 'Expert Group appraisal',
    section: 's.7',
    entry: ['EXPERT_GROUP_APPRAISAL', 'GOVT_DECISION_S8', 'SIA_EXEMPTED_S40'],
  },
  {
    stage: 'NOTIFIED',
    label: 'Preliminary notification',
    section: 's.11',
    entry: ['PRELIM_NOTIFICATION_S11'],
    clockId: 'S11_AFTER_APPRAISAL',
  },
  {
    stage: 'DECLARED',
    label: 'Declaration',
    section: 's.19',
    entry: ['DECLARATION_S19'],
    clockId: 'DECLARATION_S19',
  },
  { stage: 'AWARDED', label: 'Award', section: 's.23', entry: ['AWARD_S23'], clockId: 'AWARD_S23' },
  {
    stage: 'POSSESSED',
    label: 'Possession',
    section: 's.38',
    entry: ['POSSESSION_TAKEN_S38'],
    clockId: 'COMPENSATION_3M',
  },
  {
    stage: 'CLOSED',
    label: 'Utilised / closed',
    section: 's.101',
    entry: ['LAND_UTILISED', 'CASE_CLOSED'],
    clockId: 'UTILISATION_5Y',
  },
]

const NH_STAGES: StageStep[] = [
  { stage: 'PROPOSED', label: 'Proposal', entry: ['PROJECT_CREATED', 'PROPOSAL_APPROVED'] },
  {
    stage: 'NOTIFIED',
    label: 'Notification of intention',
    section: '3A',
    entry: ['NOTIFICATION_3A'],
  },
  {
    stage: 'DECLARED',
    label: 'Declaration',
    section: '3D',
    entry: ['DECLARATION_3D'],
    clockId: 'DECLARATION_3D',
  },
  {
    stage: 'AWARDED',
    label: 'Determination of amount',
    section: '3G',
    entry: ['AWARD_3G'],
    clockId: 'AWARD_3G',
  },
  { stage: 'POSSESSED', label: 'Possession', section: '3E', entry: ['POSSESSION_3E'] },
  { stage: 'CLOSED', label: 'Closed', entry: ['CASE_CLOSED', 'LAND_UTILISED'] },
]

/** Terminal stages are appended only when the case has actually reached them. */
export const TERMINAL_STAGES: Record<string, StageStep> = {
  LAPSED: {
    stage: 'LAPSED',
    label: 'Lapsed',
    section: 's.25 / s.19(7)',
    entry: ['CASE_LAPSED', 'NOTIFICATION_RESCINDED'],
  },
}

export function stagesForTrack(track?: string | null): StageStep[] {
  const t = (track ?? '').toUpperCase()
  if (t.startsWith('NH')) return NH_STAGES
  return RFCTLARR_STAGES
}

/* ---------------------------------------------------------- document kinds */

const DOC_KIND: Record<string, string> = {
  EXTENSION_GRANTED: 'extension_order',
  COURT_STAY: 'court_order',
  STAY_VACATED: 'court_order',
  PAYMENT_MADE: 'payment',
  AWARD_S23: 'award',
  AWARD_3G: 'award',
}

/** `kind` for POST /documents; the event type is the sensible default. */
export function docKindFor(eventType?: string | null): string {
  if (!eventType) return 'other'
  return DOC_KIND[eventType] ?? eventType.toLowerCase()
}

/* ------------------------------------------------------ extraction helpers */

export type ConfLevel = 'high' | 'medium' | 'low' | 'none'

/** Bands per Docs/Frontend.md 3: green >= 0.9, amber 0.7-0.9, red < 0.7. */
export function confLevel(v: unknown): ConfLevel {
  const n = Number(v)
  if (v == null || !Number.isFinite(n)) return 'none'
  if (n >= 0.9) return 'high'
  if (n >= 0.7) return 'medium'
  return 'low'
}

export const CONF_CHIP: Record<ConfLevel, { label: string; cls: string }> = {
  high: { label: 'High', cls: 'bg-ok/10 text-[#1B5E20] border border-ok' },
  medium: { label: 'Check', cls: 'bg-amber/10 text-[#8A5300] border border-amber' },
  low: { label: 'Verify', cls: 'bg-red/10 text-[#8C1D18] border border-red' },
  none: { label: 'Not read', cls: 'bg-surface text-muted border border-border' },
}

export function extractionSettled(e?: Extraction | null): boolean {
  const s = (e?.status ?? 'pending').toLowerCase()
  return s !== 'pending' && s !== 'running' && s !== 'queued' && s !== 'processing'
}

/** True when the extractor produced nothing usable and the officer must type. */
export function extractionEmpty(e?: Extraction | null): boolean {
  return !e?.fields || Object.keys(e.fields).length === 0
}

/* ---------------------------------------------------------- typed fetchers */

export const fetchCase = (id: string) => api<CaseDetail>(`/cases/${id}`)
export const fetchClocks = (id: string) =>
  api<unknown>(`/cases/${id}/clocks`).then((r) => normalizePage<Clock>(r, 'clocks').items)
export const fetchIntegrity = (id: string) => api<Integrity>(`/cases/${id}/integrity`)
export const fetchRisk = (id: string) => api<RiskInfo>(`/cases/${id}/risk`)
export const fetchCompensation = (id: string) =>
  api<CompensationSummary>(`/cases/${id}/compensation`)
export const fetchAllowedEvents = (id: string) =>
  api<unknown>(`/cases/${id}/allowed-events`).then(
    (r) => normalizePage<AllowedEvent>(r, 'allowed_events', 'events').items,
  )

export interface ParcelFeature {
  type: 'Feature'
  id?: string | number
  geometry: unknown
  properties: ParcelProps
}

export interface ParcelCollection {
  type: 'FeatureCollection'
  features: ParcelFeature[]
  area_total_ha?: number | null
}

export const fetchParcels = (id: string) => api<ParcelCollection>(`/cases/${id}/parcels`)

/**
 * Documents on a case. Prefers `GET /cases/{id}/documents`; if that is not
 * served, falls back to the `document_id`s carried on ledger events, which
 * Docs/APIs.md 3.5 always exposes.
 */
export async function fetchCaseDocuments(
  caseId: string,
  events: LedgerEvent[],
): Promise<DocumentMeta[]> {
  try {
    const raw = await api<unknown>(`/cases/${caseId}/documents`)
    const page = normalizePage<DocumentMeta>(raw, 'documents')
    if (page.items.length) return page.items
  } catch {
    /* endpoint absent — fall through to the ledger */
  }
  const ids = Array.from(
    new Set(events.map((e) => e.document_id).filter((d): d is string => typeof d === 'string')),
  )
  const docs = await Promise.all(
    ids.map((d) => api<DocumentMeta>(`/documents/${d}`).catch(() => null)),
  )
  return docs.filter((d): d is DocumentMeta => d !== null)
}

/** Event types already in the ledger — used to resolve string `requires[]`. */
export function satisfiedTypes(events: LedgerEvent[]): Set<string> {
  return new Set(events.map((e) => e.type))
}

export function num(v: unknown): number {
  const n = Number(v ?? 0)
  return Number.isFinite(n) ? n : 0
}
