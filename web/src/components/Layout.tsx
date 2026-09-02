import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api, getDemoDate, setDemoDate, setToken } from '../lib/api'

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
  const nav = [
    { to: '/national', label: 'National' },
    { to: '/projects', label: 'Projects' },
    { to: '/alerts', label: `Alerts${alertCount ? ` (${alertCount})` : ''}` },
    { to: '/reports', label: 'Reports' },
    ...(roles.includes('STATE_REVENUE') || roles.includes('MINISTRY') || roles.includes('AUDITOR')
      ? [{ to: '/admin/rulesets', label: 'Rule-sets' }]
      : []),
    { to: '/public', label: 'Public' },
  ]

  return (
    <div className="min-h-screen">
      <header className="bg-ink text-white">
        <div className="mx-auto flex max-w-screen-2xl items-center gap-6 px-4 py-2">
          <Link to="/" className="flex items-baseline gap-2">
            <span className="text-lg font-bold">BhuArjan</span>
            <span className="text-sm opacity-80">भू-अर्जन</span>
          </Link>
          <nav className="flex gap-1">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) =>
                  `rounded px-3 py-1 text-sm ${isActive ? 'bg-accent' : 'hover:bg-white/10'}`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <label className="flex items-center gap-1 opacity-90">
              <span className="text-xs uppercase tracking-wide opacity-70">Demo date</span>
              <input
                type="date"
                defaultValue={demoDate ?? ''}
                onChange={(e) => {
                  setDemoDate(e.target.value || null)
                  location.reload()
                }}
                className="rounded border border-white/30 bg-transparent px-1 py-0.5 text-white [color-scheme:dark]"
              />
            </label>
            <span className="opacity-80">{me?.name}</span>
            <span className="rounded bg-white/15 px-2 py-0.5 text-xs">{me?.roles?.join(', ')}</span>
            <button
              className="rounded px-2 py-1 text-xs hover:bg-white/10"
              onClick={() => {
                setToken(null)
                navigate('/login')
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-screen-2xl px-4 py-4">
        <Outlet />
      </main>
    </div>
  )
}
