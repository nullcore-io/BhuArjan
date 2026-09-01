/**
 * Sign in — Docs/APIs.md §3.1, Docs/Frontend.md §1 (role → landing).
 *
 * Two ways in. The left column is the real form (POST /auth/token via
 * `login()`); the right column is the demo bench — the six seeded officers, one
 * click each. On a 36-hour finale floor with rotating judges, "show me what the
 * Collector sees" has to be one click, not a typed password.
 *
 * Nothing here decides where the user lands: `landingFor(me.roles)` does, so
 * the routing rule lives in one place (web/src/lib/auth.ts).
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getDemoDate, setDemoDate } from '../../lib/api'
import { landingFor, login } from '../../lib/auth'
import { errorText } from '../../components/ui/format'

const DEMO_PASSWORD = 'demo123'

interface DemoAccount {
  username: string
  role: string
  roleHi: string
  who: string
  scope: string
  can: string
}

/** Mirrors api/seed/seed_demo.py — the users the demo database actually has. */
const DEMO_ACCOUNTS: DemoAccount[] = [
  {
    username: 'lao@demo',
    role: 'LAO / CALA',
    roleHi: 'भू-अर्जन अधिकारी',
    who: 'A. Verma',
    scope: 'Seoni & Balaghat districts',
    can: 'Records statutory events, uploads gazettes, assesses compensation',
  },
  {
    username: 'collector@demo',
    role: 'Collector',
    roleHi: 'कलेक्टर',
    who: 'S. Iyer',
    scope: 'Seoni district',
    can: 'Award, possession, extension requests, approves assessments',
  },
  {
    username: 'state@demo',
    role: 'State Revenue',
    roleHi: 'राज्य राजस्व',
    who: 'R. Chauhan',
    scope: 'Madhya Pradesh',
    can: 'Grants extensions, manages rule-set overlays, state dashboard',
  },
  {
    username: 'ministry@demo',
    role: 'Ministry (DoLR)',
    roleHi: 'मंत्रालय',
    who: 'Programme Division',
    scope: 'National',
    can: 'National dashboard, all cases read-only, base rule-sets',
  },
  {
    username: 'auditor@demo',
    role: 'Auditor',
    roleHi: 'लेखा परीक्षक',
    who: 'CAG Audit Cell',
    scope: 'All jurisdictions',
    can: 'Reads every ledger and hash chain; writes nothing',
  },
  {
    username: 'rb@demo',
    role: 'Requiring body',
    roleHi: 'अपेक्षक निकाय',
    who: 'NHAI PIU Seoni',
    scope: 'Own projects',
    can: 'Creates projects, uploads proposal documents, tracks own cases',
  },
]

export default function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState(DEMO_PASSWORD)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [demoDate, setLocalDemoDate] = useState<string>(getDemoDate() ?? '')

  async function signIn(user: string, pass: string) {
    setError(null)
    setBusy(user)
    try {
      const me = await login(user, pass)
      navigate(landingFor(me.roles ?? []), { replace: true })
    } catch (err) {
      setError(errorText(err))
      setBusy(null)
    }
  }

  const inputCls =
    'w-full rounded border border-border bg-bg px-2 py-1.5 text-sm text-ink ' +
    'focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent'

  return (
    <div className="min-h-screen bg-surface">
      {/* Masthead — bilingual from the first screen (Docs/Frontend.md §9). */}
      <header className="border-b-4 border-accent2 bg-ink text-white">
        <div className="mx-auto flex max-w-screen-xl flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3">
          <span className="text-2xl font-bold tracking-tight">BhuArjan</span>
          <span className="text-xl font-semibold opacity-90">भू-अर्जन</span>
          <span className="ml-auto text-xs opacity-80">
            Department of Land Resources · Ministry of Rural Development
          </span>
        </div>
        <div className="mx-auto max-w-screen-xl px-4 pb-3 text-sm opacity-90">
          National Land Acquisition &amp; Management System
          <span className="mx-2 opacity-50">|</span>
          <span>राष्ट्रीय भूमि अर्जन एवं प्रबंधन प्रणाली</span>
        </div>
      </header>

      <main className="mx-auto grid max-w-screen-xl gap-4 px-4 py-6 lg:grid-cols-[22rem_1fr]">
        {/* --- credential form --- */}
        <section className="card h-fit">
          <h1 className="text-base font-bold text-ink">
            Sign in <span className="font-normal text-muted">/ साइन इन</span>
          </h1>
          <p className="mt-1 text-xs text-muted">
            Officer credentials. In production this is the department&apos;s OIDC
            provider; the prototype issues its own token (Docs/APIs.md §3.1).
          </p>

          <form
            className="mt-3 flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              if (username.trim()) void signIn(username.trim(), password)
            }}
          >
            <label className="flex flex-col gap-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted">
                Username / उपयोगकर्ता नाम
              </span>
              <input
                className={inputCls}
                value={username}
                autoComplete="username"
                autoFocus
                placeholder="lao@demo"
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted">
                Password / पासवर्ड
              </span>
              <input
                className={inputCls}
                type="password"
                value={password}
                autoComplete="current-password"
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted">
                Demo date / प्रदर्शन तिथि
              </span>
              <input
                className={inputCls}
                type="date"
                value={demoDate}
                onChange={(e) => {
                  setLocalDemoDate(e.target.value)
                  setDemoDate(e.target.value || null)
                }}
              />
              <span className="text-[11px] text-muted">
                Sent as <code>X-Demo-Date</code>; honoured only when the server runs
                with <code>DEMO_MODE=true</code>.
              </span>
            </label>

            {error ? (
              <div
                className="rounded border border-red bg-red/5 px-2 py-1.5 text-xs text-[#8C1D18]"
                role="alert"
              >
                {error}
              </div>
            ) : null}

            <button
              type="submit"
              className="btn-primary justify-center"
              disabled={busy !== null || !username.trim()}
            >
              {busy === username.trim() ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <div className="mt-4 border-t border-border pt-3 text-xs">
            <a
              href="/public"
              className="text-accent underline decoration-dotted underline-offset-2"
            >
              Citizen status lookup — no sign-in needed / नागरिक स्थिति देखें
            </a>
          </div>
        </section>

        {/* --- demo bench --- */}
        <section className="card">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-base font-bold text-ink">
              Demo quick sign-in <span className="font-normal text-muted">/ त्वरित प्रवेश</span>
            </h2>
            <span className="text-xs text-muted">
              Seeded accounts · password <code className="font-semibold">{DEMO_PASSWORD}</code>
            </span>
          </div>
          <p className="mt-1 text-xs text-muted">
            The same ledger seen through six jurisdictions. Every read and write below is
            scoped server-side (Docs/APIs.md §2) — an out-of-scope case returns 404, not 403.
          </p>

          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {DEMO_ACCOUNTS.map((a) => (
              <button
                key={a.username}
                type="button"
                disabled={busy !== null}
                onClick={() => void signIn(a.username, DEMO_PASSWORD)}
                className="flex flex-col items-start gap-1 rounded border border-border bg-bg p-3 text-left hover:border-accent hover:bg-surface focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-50"
              >
                <div className="flex w-full items-baseline justify-between gap-2">
                  <span className="text-sm font-bold text-ink">{a.role}</span>
                  <span className="text-[11px] text-muted">{a.roleHi}</span>
                </div>
                <span className="text-xs text-muted">{a.who}</span>
                <span className="text-xs">
                  <span className="font-semibold text-ink">Scope:</span>{' '}
                  <span className="text-muted">{a.scope}</span>
                </span>
                <span className="text-[11px] leading-snug text-muted">{a.can}</span>
                <span className="mt-1 w-full border-t border-border pt-1 font-mono text-[11px] text-accent">
                  {busy === a.username ? 'Signing in…' : a.username}
                </span>
              </button>
            ))}
          </div>
        </section>
      </main>

      <footer className="mx-auto max-w-screen-xl px-4 pb-8 text-xs text-muted">
        Prototype for SIH 2026 (PS 26016). Demonstration data is synthetic; no real
        landowner information is present (Docs/rules.md A5, C5).
      </footer>
    </div>
  )
}
