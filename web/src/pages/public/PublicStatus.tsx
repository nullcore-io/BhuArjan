/**
 * Citizen status lookup — Docs/Frontend.md §7, Docs/APIs.md §3.11,
 * Docs/rules.md C5.
 *
 * No authentication, no Layout chrome, one column, large type, works on a
 * 360-px phone. What comes back is the statutory position of one plot: stage
 * and its date, the next milestone and the month it is due, area, compensation
 * assessed against paid, possession.
 *
 * What never comes back — by design in the API, and stated on the page so the
 * citizen can see the promise — is any name, identifier or document. DPDP Act
 * 2023 compliance is not a footnote here; it is the reason the page is safe to
 * publish at all.
 */
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { statuteLabel } from '../../components/ui/StatBadge'
import { ErrorNote, Loading } from '../../components/ui/Feedback'
import {
  formatDay,
  formatHa,
  formatMonth,
  httpStatus,
  num,
  present,
  titleize,
} from '../../components/ui/format'
import { api, formatINR } from '../../lib/api'

interface PublicStatusResponse {
  project?: string | null
  sector?: string | null
  statute?: string | null
  ruleset_version?: string | null
  stage?: string | null
  stage_date?: string | null
  next_milestone?: string | null
  next_due_month?: string | null
  next_milestone_basis?: string | null
  next_milestone_consequence?: string | null
  area_ha?: number | null
  case_area_ha?: number | null
  comp_assessed_paise?: number | null
  comp_paid_paise?: number | null
  possession?: { taken?: boolean | null; pct?: number | null; parcel_status?: string | null } | null
  village?: string | null
  survey_no?: string | null
  as_of_seq?: number | null
  as_of_date?: string | null
  disclaimer?: string | null
}

/** Citizen-facing stage names in both languages. */
const STAGE_HI: Record<string, string> = {
  PROPOSED: 'प्रस्तावित',
  SIA: 'सामाजिक प्रभाव आकलन',
  APPRAISED: 'विशेषज्ञ समूह द्वारा मूल्यांकित',
  NOTIFIED: 'अधिसूचित',
  DECLARED: 'घोषित',
  AWARDED: 'अधिनिर्णय पारित',
  POSSESSED: 'कब्जा लिया गया',
  CLOSED: 'बंद',
  LAPSED: 'व्यपगत',
}

const inputCls =
  'w-full rounded border border-border bg-bg px-3 py-2 text-base text-ink ' +
  'focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent'

type Mode = 'ulpin' | 'survey'

export default function PublicStatus() {
  const [mode, setMode] = useState<Mode>('ulpin')
  const [ulpin, setUlpin] = useState('')
  const [state, setState] = useState('')
  const [district, setDistrict] = useState('')
  const [village, setVillage] = useState('')
  const [surveyNo, setSurveyNo] = useState('')
  const [query, setQuery] = useState<string | null>(null)

  const canSubmit =
    mode === 'ulpin' ? ulpin.trim().length > 0 : village.trim().length > 0 && surveyNo.trim().length > 0

  function submit() {
    const qs = new URLSearchParams()
    if (mode === 'ulpin') {
      qs.set('ulpin', ulpin.trim())
    } else {
      if (state.trim()) qs.set('state', state.trim())
      if (district.trim()) qs.set('district', district.trim())
      qs.set('village', village.trim())
      qs.set('survey_no', surveyNo.trim())
    }
    setQuery(qs.toString())
  }

  const status = useQuery({
    queryKey: ['publicStatus', query],
    queryFn: () => api<PublicStatusResponse>(`/public/status?${query}`),
    enabled: Boolean(query),
    retry: false,
  })

  const d = status.data
  const notFound = status.isError && httpStatus(status.error) === 404

  return (
    <div className="min-h-screen bg-surface">
      <header className="border-b-4 border-accent2 bg-ink text-white">
        <div className="mx-auto flex max-w-md flex-wrap items-baseline gap-x-2 px-4 py-3">
          <span className="text-2xl font-semibold">BhuArjan</span>
          <span className="text-lg font-semibold opacity-90">भू-अर्जन</span>
        </div>
        <div className="mx-auto max-w-md px-4 pb-3 text-sm leading-snug opacity-90">
          Land acquisition status
          <span className="mx-1 opacity-50">·</span>
          भूमि अर्जन की स्थिति
        </div>
      </header>

      <main className="mx-auto flex max-w-md flex-col gap-4 px-4 py-5">
        {/* --- lookup --- */}
        <section className="card">
          <h1 className="text-lg font-semibold leading-snug text-ink">
            Check a plot
            <span className="block text-base font-normal text-muted">अपनी भूमि की स्थिति देखें</span>
          </h1>

          {/* Honest toggle buttons rather than a half-wired ARIA tabs pattern:
              both controls drive the same form below, not separate panels. */}
          <div className="mt-3 flex rounded border border-border" role="group" aria-label="Look up by">
            <button
              type="button"
              aria-pressed={mode === 'ulpin'}
              onClick={() => setMode('ulpin')}
              className={`flex-1 px-3 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-accent ${
                mode === 'ulpin' ? 'bg-accent text-white' : 'bg-bg text-ink hover:bg-surface'
              }`}
            >
              ULPIN
            </button>
            <button
              type="button"
              aria-pressed={mode === 'survey'}
              onClick={() => setMode('survey')}
              className={`flex-1 border-l border-border px-3 py-2 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-accent ${
                mode === 'survey' ? 'bg-accent text-white' : 'bg-bg text-ink hover:bg-surface'
              }`}
            >
              Survey no. / खसरा
            </button>
          </div>

          <form
            className="mt-3 flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (canSubmit) submit()
            }}
          >
            {mode === 'ulpin' ? (
              <label className="flex flex-col gap-1">
                <span className="text-sm font-semibold text-ink">
                  ULPIN <span className="font-normal text-muted">/ भू-खंड पहचान संख्या</span>
                </span>
                <input
                  className={inputCls}
                  value={ulpin}
                  inputMode="text"
                  autoComplete="off"
                  placeholder="e.g. MP23413-000123"
                  onChange={(e) => setUlpin(e.target.value)}
                />
                <span className="text-xs text-muted">
                  The 14-character plot identifier printed on your land record.
                </span>
              </label>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <label className="flex flex-col gap-1">
                    <span className="text-sm font-semibold text-ink">
                      State <span className="font-normal text-muted">/ राज्य</span>
                    </span>
                    <input
                      className={inputCls}
                      value={state}
                      placeholder="MP"
                      onChange={(e) => setState(e.target.value)}
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-sm font-semibold text-ink">
                      District <span className="font-normal text-muted">/ ज़िला</span>
                    </span>
                    <input
                      className={inputCls}
                      value={district}
                      placeholder="Seoni"
                      onChange={(e) => setDistrict(e.target.value)}
                    />
                  </label>
                </div>
                <label className="flex flex-col gap-1">
                  <span className="text-sm font-semibold text-ink">
                    Village <span className="font-normal text-muted">/ ग्राम</span>
                  </span>
                  <input
                    className={inputCls}
                    value={village}
                    onChange={(e) => setVillage(e.target.value)}
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-sm font-semibold text-ink">
                    Survey / Khasra no. <span className="font-normal text-muted">/ खसरा संख्या</span>
                  </span>
                  <input
                    className={inputCls}
                    value={surveyNo}
                    placeholder="123/1"
                    onChange={(e) => setSurveyNo(e.target.value)}
                  />
                </label>
                <span className="text-xs text-muted">
                  State and district are optional; village and survey number are required.
                </span>
              </>
            )}

            <button type="submit" className="btn-primary justify-center py-2 text-base" disabled={!canSubmit}>
              Check status / स्थिति देखें
            </button>
          </form>
        </section>

        {/* --- result --- */}
        {status.isLoading && query ? <Loading label="Looking up the plot…" /> : null}

        {notFound ? (
          <div className="card text-base">
            <p className="font-semibold text-ink">
              No acquisition proceeding found for this plot.
            </p>
            <p className="mt-1 text-muted">इस भूमि के लिए कोई अर्जन कार्यवाही दर्ज नहीं है।</p>
            <p className="mt-2 text-sm text-muted">
              Check the identifier and try again. A plot appears here only once a
              notification under s.11 or 3A has been recorded.
            </p>
          </div>
        ) : status.isError ? (
          <ErrorNote error={status.error} what="Status lookup" />
        ) : null}

        {status.isSuccess && d ? (
          <>
            <section className="card flex flex-col gap-3">
              <div>
                <div className="text-sm font-semibold uppercase tracking-wide text-muted">
                  Project / परियोजना
                </div>
                <div className="text-lg font-semibold leading-snug text-ink">{d.project || '—'}</div>
                <div className="text-sm text-muted">
                  {statuteLabel(d.statute)}
                  {d.sector ? ` · ${d.sector}` : ''}
                </div>
              </div>

              <Row
                label="Current stage"
                labelHi="वर्तमान चरण"
                value={
                  <span>
                    {titleize(d.stage)}
                    {d.stage && STAGE_HI[String(d.stage).toUpperCase()] ? (
                      <span className="block text-base font-normal text-muted">
                        {STAGE_HI[String(d.stage).toUpperCase()]}
                      </span>
                    ) : null}
                  </span>
                }
                note={d.stage_date ? `Recorded on ${formatDay(d.stage_date)}` : undefined}
              />

              <Row
                label="Next statutory milestone"
                labelHi="अगला वैधानिक चरण"
                value={d.next_milestone ? titleize(d.next_milestone) : 'None pending'}
                note={
                  d.next_due_month
                    ? `Due by ${formatMonth(d.next_due_month)}${
                        d.next_milestone_basis ? ` · ${d.next_milestone_basis}` : ''
                      }`
                    : d.next_milestone_basis ?? undefined
                }
              />

              {d.next_milestone_consequence ? (
                <p className="rounded border border-amber bg-amber/5 px-3 py-2 text-sm text-[#8A5300]">
                  If the deadline passes: {d.next_milestone_consequence}
                </p>
              ) : null}

              <Row
                label="Area of this plot"
                labelHi="इस भू-खंड का क्षेत्रफल"
                value={formatHa(d.area_ha)}
                note={
                  present(d.case_area_ha)
                    ? `Whole proceeding: ${formatHa(d.case_area_ha)}`
                    : undefined
                }
              />
            </section>

            <section className="card flex flex-col gap-3">
              <h2 className="text-base font-semibold text-ink">
                Compensation <span className="font-normal text-muted">/ मुआवजा</span>
              </h2>
              <p className="text-xs text-muted">
                Aggregate figures for the whole acquisition proceeding, not for one owner.
                कुल कार्यवाही के आंकड़े।
              </p>

              <div className="grid grid-cols-2 gap-3">
                <Figure label="Assessed" labelHi="निर्धारित" value={
                  present(d.comp_assessed_paise) ? formatINR(num(d.comp_assessed_paise)) : '—'
                } />
                <Figure label="Paid" labelHi="भुगतान" value={
                  present(d.comp_paid_paise) ? formatINR(num(d.comp_paid_paise)) : '—'
                } />
              </div>

              {present(d.comp_assessed_paise) && present(d.comp_paid_paise) ? (
                <PayBar
                  assessed={num(d.comp_assessed_paise)}
                  paid={num(d.comp_paid_paise)}
                />
              ) : null}

              <Row
                label="Possession"
                labelHi="कब्जा"
                value={
                  d.possession?.taken
                    ? 'Taken / लिया गया'
                    : 'Not taken / नहीं लिया गया'
                }
                note={
                  present(d.possession?.pct)
                    ? `${num(d.possession?.pct).toFixed(1)}% of the notified area is in possession${
                        d.possession?.parcel_status
                          ? ` · this plot: ${titleize(d.possession.parcel_status)}`
                          : ''
                      }`
                    : d.possession?.parcel_status
                      ? `This plot: ${titleize(d.possession.parcel_status)}`
                      : undefined
                }
              />
              <p className="text-xs text-muted">
                Possession can only be taken after compensation is paid or tendered (s.38).
                मुआवजे के भुगतान के बाद ही कब्जा लिया जा सकता है।
              </p>
            </section>

            <section className="card text-xs text-muted">
              <p className="font-semibold text-ink">
                No personal information is published on this page.
              </p>
              <p className="mt-0.5">इस पृष्ठ पर कोई व्यक्तिगत जानकारी प्रकाशित नहीं की जाती।</p>
              <p className="mt-2">
                {d.disclaimer ||
                  'Statutory position from the acquisition ledger. No personal information is published here.'}
              </p>
              <p className="mt-2">
                {d.village ? `Village ${d.village}` : ''}
                {d.village && d.survey_no ? ' · ' : ''}
                {d.survey_no ? `Survey no. ${d.survey_no}` : ''}
              </p>
              <p className="mt-2">
                As of{' '}
                {d.as_of_seq === null || d.as_of_seq === undefined
                  ? 'the latest'
                  : `ledger sequence ${d.as_of_seq}`}
                {d.as_of_date ? `, ${formatDay(d.as_of_date)}` : ''}. For a correction, contact the
                Land Acquisition Officer of your district.
              </p>
            </section>
          </>
        ) : null}

        <footer className="pb-8 text-xs text-muted">
          <a href="/login" className="text-accent underline decoration-dotted underline-offset-2">
            Officer sign-in / अधिकारी प्रवेश
          </a>
          <p className="mt-2">
            Prototype for SIH 2026 (PS 26016). Demonstration data is synthetic.
          </p>
        </footer>
      </main>
    </div>
  )
}

/* -------------------------------------------------------------- fragments */

function Row({
  label,
  labelHi,
  value,
  note,
}: {
  label: string
  labelHi: string
  value: ReactNode
  note?: string
}) {
  return (
    <div className="border-t border-border pt-3 first:border-0 first:pt-0">
      <div className="text-sm font-semibold uppercase tracking-wide text-muted">
        {label} <span className="normal-case">/ {labelHi}</span>
      </div>
      <div className="text-lg font-semibold leading-snug text-ink">{value}</div>
      {note ? <div className="text-sm text-muted">{note}</div> : null}
    </div>
  )
}

function Figure({
  label,
  labelHi,
  value,
}: {
  label: string
  labelHi: string
  value: string
}) {
  return (
    <div className="rounded border border-border bg-surface p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted">
        {label} / {labelHi}
      </div>
      <div className="text-2xl font-semibold tabular-nums text-ink">{value}</div>
    </div>
  )
}

/** Paid share of assessed. Text carries the number; the bar only reinforces it. */
function PayBar({ assessed, paid }: { assessed: number; paid: number }) {
  const pct = assessed > 0 ? Math.min(100, (100 * paid) / assessed) : 0
  return (
    <div>
      <div className="h-3 w-full overflow-hidden rounded border border-border bg-bg">
        <div className="h-full bg-ok" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 text-sm text-muted">
        {pct.toFixed(1)}% of the assessed amount has been paid.
        {assessed > paid ? ` Outstanding ${formatINR(assessed - paid)}.` : ''}
      </div>
    </div>
  )
}
