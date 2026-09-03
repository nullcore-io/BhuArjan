/**
 * Breadcrumb trail derived from the current route.
 *
 * Government portals are navigated by people who arrive from a deep link in an
 * email or an order sheet; the trail tells them where in the hierarchy they
 * landed. Labels are resolved from the path, never fetched — this component
 * must not add a request to any screen.
 */
import { Link, useLocation, useParams } from 'react-router-dom'

const SEGMENT_LABEL: Record<string, string> = {
  national: 'National Dashboard',
  projects: 'Projects',
  cases: 'Cases',
  alerts: 'Alert Centre',
  reports: 'Reports',
  districts: 'Districts',
  admin: 'Administration',
  rulesets: 'Rule-sets',
  integrations: 'Integrations',
  record: 'Record Event',
  public: 'Public Status',
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function labelFor(segment: string, params: Record<string, string | undefined>): string {
  if (SEGMENT_LABEL[segment]) return SEGMENT_LABEL[segment]
  // A bare uuid is noise in a trail; the first block is enough to tell two
  // open cases apart, and the case number itself is in the page heading.
  if (UUID.test(segment)) return `${segment.slice(0, 8)}…`
  // A district name or other readable :param — show it verbatim, decoded.
  if (Object.values(params).includes(segment)) return decodeURIComponent(segment)
  return segment
}

export default function Breadcrumbs() {
  const { pathname } = useLocation()
  const params = useParams()
  const segments = pathname.split('/').filter(Boolean)

  if (segments.length === 0) return null

  return (
    <nav aria-label="Breadcrumb" className="no-print">
      <ol className="mb-3 flex flex-wrap items-center gap-1 text-xs text-muted">
        <li>
          <Link to="/" className="hover:text-accent hover:underline">
            Home
          </Link>
        </li>
        {segments.map((seg, i) => {
          const to = '/' + segments.slice(0, i + 1).join('/')
          const last = i === segments.length - 1
          const label = labelFor(seg, params)
          return (
            <li key={to} className="flex items-center gap-1">
              <span aria-hidden="true" className="text-border">
                ›
              </span>
              {last ? (
                <span className="font-semibold text-ink" aria-current="page">
                  {label}
                </span>
              ) : (
                <Link to={to} className="hover:text-accent hover:underline">
                  {label}
                </Link>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
