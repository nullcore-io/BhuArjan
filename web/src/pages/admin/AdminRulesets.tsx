/**
 * AdminRulesets (/admin/rulesets) — Docs/Frontend.md §8, Docs/APIs.md §3.12.
 *
 *   GET /admin/rulesets                     → tracks, versions, overlays, counts
 *   GET /admin/rulesets/{track}/{version}   → the YAML exactly as it ships
 *   GET /admin/rulesets/diff?base=&overlay= → unified diff (text/plain)
 *
 * This is the screen shown on stage. It has one job: make it obvious that the
 * statutory timelines are configuration, not code (Docs/rules.md C3), and that a
 * **state variation is a config diff, not a fork** (Docs/rules.md B5). So the diff
 * is rendered as a diff — monospace, `+`/`-` markers, added lines green and removed
 * lines red — rather than summarised into prose a reviewer would have to trust.
 *
 * Colour is never the only signal: every changed line carries its `+` or `-`
 * character in its own column, with a screen-reader word beside it
 * (Docs/Frontend.md §9).
 */
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import Drawer from '../../components/ui/Drawer'
import { API_BASE, getDemoDate, getToken, api, apiText } from '../../lib/api'
import { errorText, listOf, titleize } from '../../components/ui/format'

/* ------------------------------------------------------------------- types */

interface RulesetEntry {
  track?: string | null
  version?: string | null
  ref?: string | null
  stages?: unknown
  clocks?: unknown
  transitions?: unknown
  stage_names?: unknown
  clock_ids?: unknown
  file?: string | null
  is_overlay?: boolean | null
  base_version?: string | null
  overlay_title?: string | null
}

/** `TRACK@VERSION` — the reference every admin endpoint speaks. */
function refOf(r: RulesetEntry): string {
  return r.ref || `${r.track ?? '?'}@${r.version ?? '?'}`
}

function isOverlay(r: RulesetEntry): boolean {
  if (typeof r.is_overlay === 'boolean') return r.is_overlay
  return r.base_version != null && r.base_version !== ''
}

/** Counts arrive as numbers; a list is accepted so a shape change does not blank it. */
function countOf(v: unknown): number | null {
  if (Array.isArray(v)) return v.length
  if (v == null || !Number.isFinite(Number(v))) return null
  return Number(v)
}

function countText(v: unknown): string {
  const n = countOf(v)
  return n == null ? '—' : String(n)
}

/* --------------------------------------------------------- text transports */

/**
 * Two of the three endpoints on this screen answer `text/yaml` and `text/plain`.
 * `lib/api.ts` is shared and always parses JSON, so the raw reads are done here.
 * Auth and the demo date come from the same helpers the JSON client uses, so a
 * token change can never leave this screen reading with a stale header.
 */

/* -------------------------------------------------------------- diff render */

type DiffKind = 'add' | 'del' | 'hunk' | 'file' | 'ctx'

function classify(line: string): DiffKind {
  if (line.startsWith('+++') || line.startsWith('---')) return 'file'
  if (line.startsWith('@@')) return 'hunk'
  if (line.startsWith('+')) return 'add'
  if (line.startsWith('-')) return 'del'
  return 'ctx'
}

const DIFF_CLS: Record<DiffKind, string> = {
  add: 'bg-ok/10 text-[#1B5E20]',
  del: 'bg-red/10 text-[#8C1D18]',
  hunk: 'bg-surface font-semibold text-accent',
  file: 'bg-surface font-semibold text-muted',
  ctx: 'text-ink',
}

const DIFF_WORD: Record<DiffKind, string> = {
  add: 'added',
  del: 'removed',
  hunk: 'hunk header',
  file: 'file header',
  ctx: 'unchanged',
}

function DiffView({ text }: { text: string }) {
  const lines = useMemo(() => text.replace(/\n$/, '').split('\n'), [text])
  const added = lines.filter((l) => classify(l) === 'add').length
  const removed = lines.filter((l) => classify(l) === 'del').length

  return (
    <div>
      <p className="mb-2 text-xs text-muted">
        <span className="badge border border-ok bg-ok/10 text-[#1B5E20]">+ {added} added</span>{' '}
        <span className="badge border border-red bg-red/10 text-[#8C1D18]">
          − {removed} removed
        </span>{' '}
        <span className="ml-1">
          {added + removed === 0
            ? 'The two rule-sets are identical.'
            : 'Every difference between the two effective rule-sets, line by line.'}
        </span>
      </p>
      <div className="max-h-[32rem] overflow-auto rounded border border-border bg-bg">
        <pre className="min-w-full text-[12px] leading-5">
          <code>
            {lines.map((line, i) => {
              const kind = classify(line)
              const marked = kind === 'add' || kind === 'del'
              // A context line carries a leading space of its own; strip it too, or
              // unchanged lines sit one column right of the changed ones.
              const stripped = marked || (kind === 'ctx' && line.startsWith(' '))
              const marker = marked ? line[0] : ' '
              const body = stripped ? line.slice(1) : line
              return (
                <span key={i} className={`flex ${DIFF_CLS[kind]}`}>
                  <span
                    aria-hidden="true"
                    className="w-5 shrink-0 select-none border-r border-border px-1 text-center font-bold"
                  >
                    {marker}
                  </span>
                  {marked ? <span className="sr-only">{DIFF_WORD[kind]}: </span> : null}
                  <span className="whitespace-pre px-2">{body || ' '}</span>
                </span>
              )
            })}
          </code>
        </pre>
      </div>
    </div>
  )
}

/* ================================================================== screen */

export default function AdminRulesets() {
  const [yamlRef, setYamlRef] = useState<RulesetEntry | null>(null)
  const [pair, setPair] = useState<{ base: string; overlay: string; title?: string | null } | null>(
    null,
  )

  const listQ = useQuery({
    queryKey: ['admin', 'rulesets'],
    queryFn: () => api<unknown>('/admin/rulesets'),
  })

  const items = useMemo(() => listOf<RulesetEntry>(listQ.data, 'rulesets'), [listQ.data])

  /** Overlay → its base, when both are loaded. This is what makes Compare offerable. */
  const pairs = useMemo(() => {
    const out: Array<{ base: RulesetEntry; overlay: RulesetEntry }> = []
    for (const o of items) {
      if (!isOverlay(o)) continue
      const sameTrack = items.filter((b) => b.track === o.track && !isOverlay(b))
      const base =
        sameTrack.find((b) => b.version === o.base_version) ??
        (sameTrack.length === 1 ? sameTrack[0] : undefined)
      if (base) out.push({ base, overlay: o })
    }
    return out
  }, [items])

  const yamlQ = useQuery({
    queryKey: ['admin', 'ruleset-yaml', yamlRef ? refOf(yamlRef) : ''],
    queryFn: () => apiText(`/admin/rulesets/${yamlRef?.track}/${yamlRef?.version}`),
    enabled: !!yamlRef,
    retry: false,
  })

  const diffQ = useQuery({
    queryKey: ['admin', 'ruleset-diff', pair?.base ?? '', pair?.overlay ?? ''],
    queryFn: () =>
      apiText(
        `/admin/rulesets/diff?base=${encodeURIComponent(pair!.base)}&overlay=${encodeURIComponent(
          pair!.overlay,
        )}`,
      ),
    enabled: !!pair,
    retry: false,
  })

  return (
    <div className="space-y-3">
      <header className="card">
        <h1 className="text-lg font-bold text-ink">Rule-sets</h1>
        <p className="mt-1 text-sm text-muted">
          Every statutory stage, clock and transition this system enforces is loaded from these
          files — not from code (Docs/rules.md C3). A state variation is an overlay on a base
          track with its own version and effective date, and existing cases stay pinned to the
          version they were opened under.
        </p>
        {listQ.data && typeof listQ.data === 'object' ? (
          <p className="mt-1 text-xs text-muted">
            {items.length} rule-set{items.length === 1 ? '' : 's'} loaded ·{' '}
            {items.filter(isOverlay).length} overlay
            {items.filter(isOverlay).length === 1 ? '' : 's'}
          </p>
        ) : null}
      </header>

      {pairs.length ? (
        <div className="card border-accent bg-accent/5">
          <h2 className="text-sm font-bold text-ink">A state variation is a config diff</h2>
          <p className="mt-1 text-xs text-muted">
            No fork, no branch, no second codebase — the amendment is a file, and the difference
            it makes to what the engine enforces is a diff a reviewer can read.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {pairs.map(({ base, overlay }) => (
              <button
                key={refOf(overlay)}
                type="button"
                className="btn-primary text-xs"
                onClick={() =>
                  setPair({
                    base: refOf(base),
                    overlay: refOf(overlay),
                    title: overlay.overlay_title,
                  })
                }
              >
                Compare {refOf(base)} → {refOf(overlay)}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <section className="card">
        <h2 className="sr-only">Loaded rule-sets</h2>
        {listQ.isLoading ? (
          <p className="text-sm text-muted">Loading rule-sets…</p>
        ) : listQ.isError ? (
          <p role="alert" className="rounded border border-red bg-red/10 p-2 text-sm text-[#8C1D18]">
            Could not load rule-sets: {errorText(listQ.error)}
          </p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted">
            No rule-sets are loaded. The engine has nothing to enforce until a track YAML is
            present in the rule-set directory.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="gov">
              <caption className="sr-only">
                Loaded statute tracks and overlays with their stage, clock and transition counts
              </caption>
              <thead>
                <tr>
                  <th scope="col">Track</th>
                  <th scope="col">Version</th>
                  <th scope="col">Kind</th>
                  <th scope="col" className="text-right">Stages</th>
                  <th scope="col" className="text-right">Clocks</th>
                  <th scope="col" className="text-right">Transitions</th>
                  <th scope="col">File</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => {
                  const overlay = isOverlay(r)
                  const mate = pairs.find((p) => refOf(p.overlay) === refOf(r))
                  return (
                    <tr key={refOf(r)}>
                      <td className="font-semibold">{titleize(r.track)}</td>
                      <td className="font-mono text-[12px]">{r.version ?? '—'}</td>
                      <td>
                        {overlay ? (
                          <>
                            <span className="badge border border-accent2 bg-accent2/10 text-[#7A4E09]">
                              Overlay
                            </span>
                            {r.overlay_title ? (
                              <span className="block text-[11px] text-muted">{r.overlay_title}</span>
                            ) : null}
                            {r.base_version ? (
                              <span className="block font-mono text-[11px] text-muted">
                                on {r.track}@{r.base_version}
                              </span>
                            ) : null}
                          </>
                        ) : (
                          <span className="badge border border-border bg-surface text-muted">
                            Base track
                          </span>
                        )}
                      </td>
                      <td className="text-right tabular-nums">{countText(r.stages)}</td>
                      <td className="text-right tabular-nums">{countText(r.clocks)}</td>
                      <td className="text-right tabular-nums">{countText(r.transitions)}</td>
                      <td className="font-mono text-[11px] text-muted">{r.file ?? '—'}</td>
                      <td className="whitespace-nowrap">
                        <button
                          type="button"
                          className="btn px-2 py-0.5 text-[11px]"
                          onClick={() => setYamlRef(r)}
                        >
                          View YAML
                        </button>
                        {mate ? (
                          <button
                            type="button"
                            className="btn ml-1 px-2 py-0.5 text-[11px]"
                            onClick={() =>
                              setPair({
                                base: refOf(mate.base),
                                overlay: refOf(mate.overlay),
                                title: r.overlay_title,
                              })
                            }
                          >
                            Compare
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-[11px] text-muted">
          Counts are read from the loaded rule-set, not from the file, so an overlay shows what
          the engine actually enforces after the merge.
        </p>
      </section>

      {/* ───────────────────────────────────────────────────────── the diff */}
      {pair ? (
        <section className="card" aria-labelledby="diff-h">
          <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border pb-2">
            <div>
              <h2 id="diff-h" className="text-base font-bold text-ink">
                Config diff — <span className="font-mono text-sm">{pair.base}</span>{' '}
                <span aria-hidden="true">→</span>{' '}
                <span className="font-mono text-sm">{pair.overlay}</span>
              </h2>
              <p className="mt-0.5 text-xs text-muted">
                {pair.title ? `${pair.title} · ` : ''}
                Unified diff of the two effective rule-sets — base merged against overlay merged,
                so this is what each case is actually judged against.
              </p>
            </div>
            <button type="button" className="btn text-xs" onClick={() => setPair(null)}>
              Close diff
            </button>
          </div>
          <div className="pt-3">
            {diffQ.isLoading ? (
              <p className="text-sm text-muted">Computing the diff…</p>
            ) : diffQ.isError ? (
              <p
                role="alert"
                className="rounded border border-red bg-red/10 p-2 text-sm text-[#8C1D18]"
              >
                Could not compute the diff: {errorText(diffQ.error)}
              </p>
            ) : (
              <DiffView text={diffQ.data ?? ''} />
            )}
          </div>
        </section>
      ) : null}

      {/* ─────────────────────────────────────────────────────── YAML drawer */}
      <Drawer
        open={!!yamlRef}
        title={yamlRef ? refOf(yamlRef) : 'Rule-set'}
        subtitle={
          yamlRef ? (
            <>
              {yamlRef.file ? <span className="font-mono">{yamlRef.file}</span> : null}
              {yamlRef.overlay_title ? ` · ${yamlRef.overlay_title}` : ''} — the YAML exactly as it
              ships
            </>
          ) : undefined
        }
        onClose={() => setYamlRef(null)}
      >
        {yamlQ.isLoading ? (
          <p className="text-sm text-muted">Loading YAML…</p>
        ) : yamlQ.isError ? (
          <p role="alert" className="rounded border border-red bg-red/10 p-2 text-sm text-[#8C1D18]">
            Could not load the rule-set file: {errorText(yamlQ.error)}
          </p>
        ) : (
          <pre className="overflow-auto rounded border border-border bg-surface p-3 text-[12px] leading-5 text-ink">
            <code>{yamlQ.data}</code>
          </pre>
        )}
      </Drawer>
    </div>
  )
}
