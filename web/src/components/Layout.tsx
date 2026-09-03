/**
 * Application chrome: tricolour rule → utility strip → masthead → nav band →
 * breadcrumbs → main → footer.
 *
 * Restyle only. The two queries below (`me`, `alerts/summary`), the demo-date
 * header contract and the role-gated nav are unchanged from the previous
 * layout — this file decides how the shell looks, never what it fetches.
 */
import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api, getDemoDate, setDemoDate, setToken } from '../lib/api'
import Breadcrumbs from './gov/Breadcrumbs'
import Logo from './gov/Logo'
import SiteFooter from './gov/SiteFooter'
import TricolourRule from './gov/TricolourRule'
import UtilityStrip from './gov/UtilityStrip'

export default function Layout() {
  const navigate = useNavigate()
  const { data: me } = useQuery({ queryKey: ['me'], queryFn: () => api('/auth/me') })
  const { data: alertSummary } = useQuery({
    queryKey: ['alertSummary'],
    queryFn: () => api('/alerts/summary'),
    refetchInterval: 30_000,
  })
  const alertCount = alertSummary
    ? Object.values(alertSummary.counts ?? {}).reduce((a: number, b: any) => a + Number(b || 0), 0)
    : 0
  const demoDate = getDemoDate()

  const roles: string[] = me?.roles ?? []
  const nav: { to: string; label: string; badge?: number }[] = [
    { to: '/national', label: 'National' },
    { to: '/projects', label: 'Projects' },
    { to: '/alerts', label: 'Alerts', badge: alertCount || undefined },
    { to: '/reports', label: 'Reports' },
    ...(roles.includes('STATE_REVENUE') || roles.includes('MINISTRY') || roles.includes('AUDITOR')
      ? [{ to: '/admin/rulesets', label: 'Rule-sets' }]
      : []),
    { to: '/public', label: 'Public' },
  ]

  return (
    <div className="flex min-h-screen flex-col">
      <TricolourRule />
      <UtilityStrip />

      {/* ---------------------------------------------------------- masthead */}
      <header className="border-b border-border bg-bg">
        <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center gap-4 px-6 py-4">
          <Link to="/" className="flex items-center gap-3 rounded">
            <Logo size={38} className="shrink-0" />
            <span className="leading-tight">
              <span className="block text-2xl font-semibold tracking-tight text-ink">
                BhuArjan <span className="font-semibold text-accent">भू-अर्जन</span>
              </span>
              <span className="block text-xs uppercase tracking-[0.12em] text-muted">
                National Land Acquisition &amp; Management System
              </span>
            </span>
          </Link>

          <div className="ml-auto flex flex-wrap items-center gap-3 no-print">
            {/* Demo clock — honoured only when the API runs with DEMO_MODE=true. */}
            <label className="flex items-center gap-1.5 rounded border border-accent2/40 bg-accent2/5 px-2 py-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-accent2">
                Demo date
              </span>
              <input
                type="date"
                defaultValue={demoDate ?? ''}
                onChange={(e) => {
                  setDemoDate(e.target.value || null)
                  location.reload()
                }}
                className="rounded border border-border bg-bg px-1 py-0.5 text-xs text-ink"
              />
            </label>

            {me ? (
              <div className="flex items-center gap-2 border-l border-border pl-3">
                <div className="leading-tight">
                  <div className="text-sm font-semibold text-ink">{me.name}</div>
                  <div className="text-xs uppercase tracking-wide text-muted">
                    {me.roles?.join(' · ')}
                  </div>
                </div>
                <button className="btn btn-sm" onClick={() => { setToken(null); navigate('/login') }}>
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      {/* --------------------------------------------------------- nav band */}
      {/* White bar with ink text and a saffron active underline — the GOV.UK /
          USWDS pattern. A full-bleed navy band reads heavier and older; the
          navy now survives in the masthead wordmark, where it identifies. */}
      <nav className="no-print border-b border-border bg-bg" aria-label="Primary">
        <div className="mx-auto flex max-w-screen-2xl flex-wrap items-stretch px-6">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `flex items-center gap-2 border-b-[3px] px-4 py-3 text-sm transition-colors ${
                  isActive
                    ? 'border-accent2 font-semibold text-ink'
                    : 'border-transparent font-medium text-muted hover:border-border hover:text-ink'
                }`
              }
            >
              {n.label}
              {n.badge ? (
                <span className="rounded-sm bg-red px-1.5 text-xs font-semibold leading-5 text-white">
                  {n.badge}
                </span>
              ) : null}
            </NavLink>
          ))}
        </div>
      </nav>

      <main id="main" className="mx-auto w-full max-w-screen-2xl flex-1 px-6 pb-10 pt-5">
        <Breadcrumbs />
        <Outlet />
      </main>

      <SiteFooter />
    </div>
  )
}
