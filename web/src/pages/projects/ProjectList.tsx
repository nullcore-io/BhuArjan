/**
 * Project list — Docs/APIs.md §3.2, Docs/Frontend.md §1.
 *
 * The list is already jurisdiction-scoped by the server (Docs/APIs.md §2), so
 * this screen never filters by role; it only decides who is offered the
 * "New project" action — the requiring body that raises the proposal and the
 * Ministry that administers the register.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Empty, ErrorNote, Loading } from '../../components/ui/Feedback'
import { StatuteBadge } from '../../components/ui/StatBadge'
import { errorText, formatCount, listOf, textOf } from '../../components/ui/format'
import { api } from '../../lib/api'
import type { Me } from '../../lib/auth'

export interface ProjectRow {
  id: string
  name?: string | null
  sector?: string | null
  statute_track?: string | null
  ruleset_version?: string | null
  state_code?: string | null
  state?: string | null
  requiring_body?: string | { name?: string } | null
  requiring_body_name?: string | null
  requiring_body_id?: string | null
  case_count?: number | null
  cases_count?: number | null
  cases?: unknown[] | null
  created_at?: string | null
}

/** `case_count`, `cases_count` or the length of an embedded `cases[]`. */
export function caseCountOf(p: ProjectRow): number | null {
  if (typeof p.case_count === 'number') return p.case_count
  if (typeof p.cases_count === 'number') return p.cases_count
  if (Array.isArray(p.cases)) return p.cases.length
  return null
}

export function requiringBodyOf(p: ProjectRow): string {
  const name = textOf(p as unknown as Record<string, unknown>, 'requiring_body_name', 'requiring_body')
  if (name) return name
  return p.requiring_body_id ? `${p.requiring_body_id.slice(0, 8)}…` : '—'
}

const CREATOR_ROLES = ['RB', 'MINISTRY']

const inputCls =
  'w-full rounded border border-border bg-bg px-2 py-1 text-sm text-ink ' +
  'focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent'

export default function ProjectList() {
  const queryClient = useQueryClient()
  const [showNew, setShowNew] = useState(false)

  const me = useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/auth/me'), retry: false })
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api<unknown>('/projects'),
  })

  const rows = listOf<ProjectRow>(projects.data, 'projects')
  const canCreate = (me.data?.roles ?? []).some((r) => CREATOR_ROLES.includes(r))

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-ink">
            Projects <span className="font-normal text-muted">/ परियोजनाएँ</span>
          </h1>
          <p className="text-xs text-muted">
            Acquisition proceedings are grouped under the project that requires the land.
            The register below is scoped to your jurisdiction.
          </p>
        </div>
        {canCreate ? (
          <button type="button" className="btn-primary" onClick={() => setShowNew((v) => !v)}>
            {showNew ? 'Cancel' : 'New project'}
          </button>
        ) : null}
      </header>

      {showNew && canCreate ? (
        <NewProjectForm
          onDone={() => {
            setShowNew(false)
            void queryClient.invalidateQueries({ queryKey: ['projects'] })
          }}
        />
      ) : null}

      {projects.isLoading ? <Loading label="Loading projects…" /> : null}
      {projects.isError ? <ErrorNote error={projects.error} what="Project register" /> : null}

      {projects.isSuccess ? (
        rows.length === 0 ? (
          <Empty>
            No projects in your jurisdiction yet.
            {canCreate ? ' Use “New project” to register one.' : ''}
          </Empty>
        ) : (
          <div className="card overflow-x-auto p-0">
            <table className="gov">
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Sector</th>
                  <th>Statute track</th>
                  <th>State</th>
                  <th>Requiring body</th>
                  <th className="text-right">Cases</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id} className="hover:bg-surface">
                    <td>
                      <Link
                        to={`/projects/${p.id}`}
                        className="font-medium text-accent underline decoration-dotted underline-offset-2"
                      >
                        {p.name || 'Untitled project'}
                      </Link>
                      {p.ruleset_version ? (
                        <span className="ml-2 text-[11px] text-muted">
                          rule-set {p.ruleset_version}
                        </span>
                      ) : null}
                    </td>
                    <td>{p.sector || '—'}</td>
                    <td>
                      <StatuteBadge track={p.statute_track} />
                    </td>
                    <td>{p.state_code || p.state || '—'}</td>
                    <td className="max-w-[18rem] truncate">{requiringBodyOf(p)}</td>
                    <td className="text-right tabular-nums">
                      {caseCountOf(p) === null ? '—' : formatCount(caseCountOf(p))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------ new project */

function NewProjectForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('')
  const [sector, setSector] = useState('')
  const [statuteTrack, setStatuteTrack] = useState('RFCTLARR_2013')
  const [stateCode, setStateCode] = useState('')
  const [requiringBodyId, setRequiringBodyId] = useState('')

  const create = useMutation({
    mutationFn: () =>
      api('/projects', {
        method: 'POST',
        json: {
          name: name.trim(),
          sector: sector.trim() || null,
          statute_track: statuteTrack,
          state_code: stateCode.trim().toUpperCase() || null,
          requiring_body_id: requiringBodyId.trim() || null,
        },
      }),
    onSuccess: onDone,
  })

  return (
    <form
      className="card flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (name.trim()) create.mutate()
      }}
    >
      <h2 className="text-sm font-bold text-ink">Register a project</h2>
      <p className="text-xs text-muted">
        The statute track is pinned to the project and inherited by every case under it;
        the rule-set version is pinned at creation so a later overlay never rewrites
        history (Docs/Backend.md §5).
      </p>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="flex flex-col gap-1 sm:col-span-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">
            Project name
          </span>
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">Sector</span>
          <input
            className={inputCls}
            value={sector}
            placeholder="National Highways"
            onChange={(e) => setSector(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">
            Statute track
          </span>
          <select
            className={inputCls}
            value={statuteTrack}
            onChange={(e) => setStatuteTrack(e.target.value)}
          >
            <option value="RFCTLARR_2013">RFCTLARR 2013</option>
            <option value="NH_ACT_1956">NH Act 1956</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">
            State code
          </span>
          <input
            className={inputCls}
            value={stateCode}
            placeholder="MP"
            onChange={(e) => setStateCode(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">
            Requiring body (org-unit id)
          </span>
          <input
            className={inputCls}
            value={requiringBodyId}
            placeholder="optional uuid"
            onChange={(e) => setRequiringBodyId(e.target.value)}
          />
        </label>
      </div>

      {create.isError ? <ErrorNote error={create.error} what="Project creation" /> : null}

      <div className="flex items-center gap-2">
        <button type="submit" className="btn-primary" disabled={!name.trim() || create.isPending}>
          {create.isPending ? 'Creating…' : 'Create project'}
        </button>
        {create.isError ? (
          <span className="text-xs text-muted">{errorText(create.error)}</span>
        ) : null}
      </div>
    </form>
  )
}
