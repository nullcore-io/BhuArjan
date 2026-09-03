/**
 * MIS report builder — Docs/Frontend.md §4, Docs/APIs.md §3.10, Docs/rules.md C7.
 *
 * The contract is asynchronous (`POST /reports` → `202 {job_id}`, then
 * `GET /reports/{job_id}`), and this screen honours that shape even though this
 * build generates synchronously: the POST hands back a job id, the GET is a real
 * query that can be re-run, and the download link is re-fetched rather than
 * remembered — the URL is presigned and short-lived, so a link kept from twenty
 * minutes ago would 403 in front of an audience.
 *
 * What the result card exists to show is not the file. It is the two integrity
 * properties every export carries: the ledger sequence the figures were computed
 * at, and the SHA-256 of the exact bytes served. A spreadsheet mailed onwards can
 * be checked back against both.
 *
 * The template and format lists are read from `GET /reports/templates` rather than
 * hard-coded, so a template this build cannot produce is never offered; the
 * constants below are only the fallback for an older API.
 */
import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import CopyButton from '../../components/ui/CopyButton'
import { Empty, ErrorNote, Loading, Panel } from '../../components/ui/Feedback'
import { formatCount, listOf, num } from '../../components/ui/format'
import { api } from '../../lib/api'

/* ------------------------------------------------------------- API shapes */

interface TemplatesResponse {
  templates?: string[] | null
  formats?: string[] | null
  geojson_templates?: string[] | null
  filters?: string[] | null
  note?: string | null
}

interface ReportJob {
  job_id: string
  status?: string | null
  template?: string | null
  format?: string | null
  filters?: Record<string, unknown> | null
  url?: string | null
  url_expires_in?: number | null
  report_hash?: string | null
  as_of_seq?: number | null
  row_count?: number | null
  case_count?: number | null
  size_bytes?: number | null
  mime?: string | null
  filename?: string | null
  generated_at?: string | null
  detail?: string | null
}

/** A history row is the job plus the wall-clock time this session first saw it. */
type HistoryItem = ReportJob & { seenAt: number }

/* ------------------------------------------------------------- vocabulary */

const FALLBACK_TEMPLATES = ['national_kpis', 'cases_register', 'compensation_register']
const FALLBACK_FORMATS = ['csv', 'geojson']
const FALLBACK_GEOJSON = ['cases_register']

interface TemplateView {
  label: string
  labelHi: string
  note: string
}

const TEMPLATE_VIEW: Record<string, TemplateView> = {
  national_kpis: {
    label: 'National KPIs',
    labelHi: 'राष्ट्रीय संकेतक',
    note: 'One row per KPI with the projection or event set it was read from — the dashboard tiles, exported.',
  },
  cases_register: {
    label: 'Cases register',
    labelHi: 'प्रकरण पंजी',
    note: 'One row per case: stage, district, area notified and acquired, compensation assessed and paid, risk.',
  },
  compensation_register: {
    label: 'Compensation register',
    labelHi: 'मुआवजा पंजी',
    note: 'One row per award line — market value, factor, assets, solatium, interest, paid and outstanding (First Schedule).',
  },
}

function templateView(key: string): TemplateView {
  return (
    TEMPLATE_VIEW[key] ?? {
      label: key.replace(/_/g, ' '),
      labelHi: '',
      note: 'Template served by this API build.',
    }
  )
}

const FORMAT_LABEL: Record<string, string> = {
  csv: 'CSV',
  geojson: 'GeoJSON',
  pdf: 'PDF',
}

const STATUTE_OPTIONS = [
  { value: '', label: 'All statute tracks' },
  { value: 'RFCTLARR_2013', label: 'RFCTLARR 2013' },
  { value: 'NH_ACT_1956', label: 'NH Act 1956' },
]

/* ---------------------------------------------------------------- helpers */

function formatBytes(v: unknown): string {
  const n = num(v)
  if (!n) return '—'
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} kB`
  return `${n} B`
}

/** `2026-09-02T04:11:07+00:00` → `02-09-2026 09:41` in the reader's own zone. */
function formatStamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)}-${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const inputCls =
  'w-full rounded border border-border bg-bg px-2 py-1 text-sm text-ink ' +
  'focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent'

/* ----------------------------------------------------------------- screen */

export default function ReportsPage() {
  const [params] = useSearchParams()

  // A district (or state) dashboard links here with its own scope prefilled, so
  // the export the officer is looking at is the one the button offered.
  const [template, setTemplate] = useState(
    () => params.get('template') || FALLBACK_TEMPLATES[0],
  )
  const [stateCode, setStateCode] = useState(() => params.get('state') ?? '')
  const [district, setDistrict] = useState(() => params.get('district') ?? '')
  const [statute, setStatute] = useState(() => params.get('statute') ?? '')
  const [format, setFormat] = useState('csv')

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [history, setHistory] = useState<HistoryItem[]>([])

  /* --- what this build can produce ------------------------------------- */

  const templates = useQuery({
    queryKey: ['reportTemplates'],
    queryFn: () => api<TemplatesResponse>('/reports/templates'),
    staleTime: 10 * 60_000,
    retry: false,
  })

  const templateKeys = listOf<string>(templates.data?.templates, 'templates')
  const availableTemplates = templateKeys.length ? templateKeys : FALLBACK_TEMPLATES
  const formatKeys = listOf<string>(templates.data?.formats, 'formats')
  const availableFormats = formatKeys.length ? formatKeys : FALLBACK_FORMATS
  const geojsonKeys = listOf<string>(templates.data?.geojson_templates, 'geojson_templates')
  const geojsonTemplates = templates.data ? geojsonKeys : FALLBACK_GEOJSON

  // GeoJSON is a map of parcels, so it only means anything for the register that
  // has parcels. Switching template away from one that supports it drops back to
  // CSV rather than sending a request the API is right to reject.
  const geojsonAllowed = geojsonTemplates.includes(template)
  useEffect(() => {
    if (!geojsonAllowed && format === 'geojson') setFormat('csv')
  }, [geojsonAllowed, format])

  // A `?template=` in the URL is caller-supplied. Once the API has said what it
  // serves, an unknown one falls back rather than sitting in a select with no
  // visible option selected and failing on submit.
  const templateList = availableTemplates.join(',')
  useEffect(() => {
    const known = templateList.split(',')
    if (templates.data && !known.includes(template)) setTemplate(known[0])
  }, [templates.data, templateList, template])

  /* --- generate: POST, then poll the job ------------------------------- */

  const generate = useMutation({
    mutationFn: async () => {
      const filters: Record<string, string> = {}
      if (stateCode.trim()) filters.state = stateCode.trim()
      if (district.trim()) filters.district = district.trim()
      if (statute) filters.statute = statute
      const created = await api<{ job_id?: string }>('/reports', {
        method: 'POST',
        json: { template, filters, format },
      })
      if (!created?.job_id) throw new Error('the API accepted the report but returned no job id')
      return created.job_id
    },
    onSuccess: (jobId) => setSelectedId(jobId),
  })

  const job = useQuery({
    queryKey: ['report', selectedId],
    queryFn: () => api<ReportJob>(`/reports/${selectedId}`),
    enabled: Boolean(selectedId),
    // The presigned URL inside expires; never serve a stale one from cache.
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })

  // Session-local history. Deliberately component state: a list of presigned URLs
  // is not something to leave in localStorage after the officer walks away.
  const jobData = job.data
  useEffect(() => {
    if (!jobData?.job_id) return
    setHistory((h) => {
      const prior = h.find((j) => j.job_id === jobData.job_id)
      const rest = h.filter((j) => j.job_id !== jobData.job_id)
      return [{ ...jobData, seenAt: prior?.seenAt ?? Date.now() }, ...rest].slice(0, 20)
    })
  }, [jobData])

  const view = templateView(template)

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-lg font-semibold text-ink">
          Reports <span className="font-normal text-muted">/ रिपोर्ट</span>
        </h1>
        <p className="text-xs text-muted">
          MIS extracts over the cases you can already open — a report can never contain a
          case your jurisdiction does not cover (Docs/rules.md C6).
        </p>
      </header>

      {templates.isError ? (
        <div className="rounded border border-amber bg-amber/5 px-3 py-1.5 text-xs text-[#8A5300]">
          <code>GET /reports/templates</code> is not served by this API build; the three
          templates below are the documented set (Docs/APIs.md §3.10) and a request for
          one this build cannot produce will come back as a 422 naming what it can.
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-3">
        {/* --- builder ---------------------------------------------------- */}
        <Panel
          title="Report builder"
          right={templates.isLoading ? 'reading templates…' : `${availableTemplates.length} templates`}
        >
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              generate.mutate()
            }}
          >
            <label className="flex flex-col gap-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted">
                Template
              </span>
              <select
                className={inputCls}
                value={template}
                onChange={(e) => setTemplate(e.target.value)}
              >
                {availableTemplates.map((t) => (
                  <option key={t} value={t}>
                    {templateView(t).label}
                  </option>
                ))}
              </select>
              <span className="text-xs text-muted">{view.note}</span>
            </label>

            <fieldset className="flex flex-col gap-2 rounded border border-border p-2">
              <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted">
                Filters
              </legend>
              <label className="flex flex-col gap-0.5">
                <span className="text-xs text-muted">State code</span>
                <input
                  className={inputCls}
                  value={stateCode}
                  placeholder="e.g. MP"
                  onChange={(e) => setStateCode(e.target.value)}
                />
              </label>
              <label className="flex flex-col gap-0.5">
                <span className="text-xs text-muted">District</span>
                <input
                  className={inputCls}
                  value={district}
                  placeholder="name, LGD code or id"
                  onChange={(e) => setDistrict(e.target.value)}
                />
              </label>
              <label className="flex flex-col gap-0.5">
                <span className="text-xs text-muted">Statute track</span>
                <select
                  className={inputCls}
                  value={statute}
                  onChange={(e) => setStatute(e.target.value)}
                >
                  {STATUTE_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
              <p className="text-xs text-muted">
                Leave a filter blank for everything in your jurisdiction. An unmatched
                district produces an empty extract, not an error.
              </p>
            </fieldset>

            <fieldset className="flex flex-col gap-1">
              <legend className="text-xs font-semibold uppercase tracking-wide text-muted">
                Format
              </legend>
              <div className="flex flex-wrap gap-3">
                {availableFormats.map((f) => {
                  const disabled = f === 'geojson' && !geojsonAllowed
                  return (
                    <label
                      key={f}
                      className={`flex items-center gap-1 text-sm ${disabled ? 'text-muted opacity-60' : ''}`}
                      title={
                        disabled
                          ? `GeoJSON draws parcels; only ${geojsonTemplates
                              .map((t) => templateView(t).label)
                              .join(', ')} has them`
                          : undefined
                      }
                    >
                      <input
                        type="radio"
                        name="format"
                        value={f}
                        checked={format === f}
                        disabled={disabled}
                        onChange={() => setFormat(f)}
                      />
                      {FORMAT_LABEL[f] ?? f.toUpperCase()}
                    </label>
                  )
                })}
              </div>
              {!geojsonAllowed ? (
                <span className="text-xs text-muted">
                  GeoJSON is enabled for the cases register only — it is a parcel map, and
                  the other templates have no geometry to draw.
                </span>
              ) : null}
            </fieldset>

            <div className="flex items-center gap-2">
              <button className="btn-primary" type="submit" disabled={generate.isPending}>
                {generate.isPending ? 'Generating…' : 'Generate'}
              </button>
              {generate.isPending ? (
                <span className="text-xs text-muted">posting to /reports…</span>
              ) : null}
            </div>

            {generate.isError ? <ErrorNote error={generate.error} what="Report request" /> : null}
          </form>
        </Panel>

        {/* --- result ----------------------------------------------------- */}
        <div className="flex flex-col gap-4 xl:col-span-2">
          <Panel
            title="Result"
            right={
              selectedId ? (
                <button
                  type="button"
                  className="rounded text-accent underline decoration-dotted underline-offset-2 hover:text-ink focus:outline-none focus:ring-2 focus:ring-accent"
                  onClick={() => job.refetch()}
                  disabled={job.isFetching}
                >
                  {job.isFetching ? 'refreshing…' : 'Refresh link'}
                </button>
              ) : (
                'nothing generated yet'
              )
            }
          >
            {!selectedId ? (
              <Empty>
                Choose a template and press Generate. The job id comes back immediately;
                this panel then reads <code>GET /reports/&#123;job_id&#125;</code> for the
                finished file.
              </Empty>
            ) : null}
            {selectedId && job.isLoading ? <Loading label="Reading the report job…" /> : null}
            {job.isError ? <ErrorNote error={job.error} what="Report job" /> : null}
            {jobData ? <ResultCard job={jobData} /> : null}
          </Panel>

          {/* --- history --------------------------------------------------- */}
          <Panel
            title="This session's reports"
            right={history.length ? `${formatCount(history.length)} generated` : 'not stored'}
          >
            {history.length === 0 ? (
              <Empty>
                Reports generated in this browser session are listed here. The list is not
                persisted — a presigned download URL is not something to leave behind on a
                shared machine.
              </Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="gov">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Template</th>
                      <th>Format</th>
                      <th className="text-right">Rows</th>
                      <th className="text-right">As of seq</th>
                      <th>Hash</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => (
                      <tr
                        key={h.job_id}
                        className={h.job_id === selectedId ? 'bg-surface' : 'hover:bg-surface'}
                      >
                        <td className="whitespace-nowrap">{formatStamp(h.generated_at)}</td>
                        <td>{templateView(String(h.template ?? '')).label}</td>
                        <td>{FORMAT_LABEL[String(h.format)] ?? h.format ?? '—'}</td>
                        <td className="text-right tabular-nums">{formatCount(h.row_count)}</td>
                        <td className="text-right tabular-nums">{formatCount(h.as_of_seq)}</td>
                        <td
                          className="font-mono text-xs"
                          title={h.report_hash ?? undefined}
                        >
                          {h.report_hash ? `${h.report_hash.slice(0, 12)}…` : '—'}
                        </td>
                        <td className="whitespace-nowrap text-right">
                          <button
                            type="button"
                            className="rounded text-accent underline decoration-dotted underline-offset-2 hover:text-ink focus:outline-none focus:ring-2 focus:ring-accent"
                            onClick={() => setSelectedId(h.job_id)}
                          >
                            {h.job_id === selectedId ? 'Shown' : 'Open'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>
      </div>

      <p className="text-xs text-muted">
        Exports embed the ledger sequence and a content hash so any figure can be
        re-verified (Docs/rules.md C7).
      </p>
    </div>
  )
}

/* ------------------------------------------------------------ result card */

function ResultCard({ job }: { job: ReportJob }) {
  const done = String(job.status ?? '').toLowerCase() === 'done'
  const filters = job.filters ?? {}
  const filterPairs = Object.entries(filters).filter(([, v]) => v !== null && v !== '')

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`badge border ${
            done
              ? 'border-ok bg-ok/10 text-[#1B5E20]'
              : 'border-amber bg-amber/10 text-[#8A5300]'
          }`}
        >
          {done ? 'Ready' : (job.status ?? 'pending')}
        </span>
        <span className="text-sm font-semibold text-ink">
          {templateView(String(job.template ?? '')).label}
        </span>
        <span className="badge border border-border bg-surface text-muted">
          {FORMAT_LABEL[String(job.format)] ?? String(job.format ?? '').toUpperCase()}
        </span>
        {filterPairs.map(([k, v]) => (
          <span key={k} className="badge border border-accent bg-accent/10 text-accent">
            {k}: {String(v)}
          </span>
        ))}
      </div>

      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div className="flex gap-2">
          <dt className="text-muted">As of seq</dt>
          <dd
            className="font-semibold tabular-nums"
            title="Event sequence number the figures were computed at (Docs/rules.md C7)"
          >
            {formatCount(job.as_of_seq)}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted">Generated</dt>
          <dd className="font-medium">{formatStamp(job.generated_at)}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted">Rows</dt>
          <dd className="font-medium tabular-nums">{formatCount(job.row_count)}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted">Cases in scope</dt>
          <dd className="font-medium tabular-nums">{formatCount(job.case_count)}</dd>
        </div>
      </dl>

      <div className="rounded border border-border bg-surface p-2">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted">
          Report hash (SHA-256 of the bytes served)
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <code className="break-all font-mono text-xs text-ink">{job.report_hash ?? '—'}</code>
          <CopyButton value={job.report_hash} label="Copy hash" />
        </div>
        <p className="mt-1 text-xs text-muted">
          Re-hash the downloaded file and you get this string back. A CSV also carries{' '}
          <code>#&nbsp;as_of_seq={job.as_of_seq ?? '—'}</code> on its first line; a GeoJSON
          carries it as a top-level member.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {job.url ? (
          <a className="btn-primary" href={job.url} target="_blank" rel="noreferrer">
            Download {FORMAT_LABEL[String(job.format)] ?? 'file'}
          </a>
        ) : (
          <span className="text-sm text-muted">
            No download URL yet{job.status ? ` — job is ${job.status}` : ''}.
          </span>
        )}
        {job.filename ? (
          <span className="font-mono text-xs text-muted">{job.filename}</span>
        ) : null}
        <span className="text-xs text-muted">{formatBytes(job.size_bytes)}</span>
        {job.url && job.url_expires_in ? (
          <span className="text-xs text-muted">
            link valid ~{Math.round(num(job.url_expires_in) / 60)} min — use Refresh link if
            it has lapsed
          </span>
        ) : null}
      </div>

      <div className="text-xs text-muted">
        Job <span className="font-mono">{job.job_id}</span>
        {job.detail ? ` · ${job.detail}` : ''}
      </div>
    </div>
  )
}
