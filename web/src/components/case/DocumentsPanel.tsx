/**
 * DocumentsPanel — every document on the case: kind, date, SHA-256, version.
 * Docs/Frontend.md §2. Files open through `GET /documents/{id}/file`, which
 * returns a short-lived signed URL (Docs/APIs.md §3.5) — never a raw key.
 */
import { useState } from 'react'
import { DocumentMeta, formatTs, hashPrefix, openDocumentInTab, titleize } from './caseApi'

export default function DocumentsPanel({
  documents,
  loading,
  error,
}: {
  documents: DocumentMeta[]
  loading?: boolean
  error?: unknown
}) {
  const [opening, setOpening] = useState<string | null>(null)
  const [openError, setOpenError] = useState<string | null>(null)

  const open = (id: string) => {
    setOpenError(null)
    setOpening(id)
    openDocumentInTab(id)
      .catch((err) => setOpenError(err instanceof Error ? err.message : 'Could not open document'))
      .finally(() => setOpening(null))
  }

  return (
    <section className="card" aria-labelledby="docs-h">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="docs-h" className="text-sm font-bold uppercase tracking-wide text-muted">
          Documents
        </h2>
        <span className="text-xs text-muted">{documents.length}</span>
      </div>

      {openError ? (
        <p role="alert" className="mt-2 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
          {openError}
        </p>
      ) : null}

      {loading ? (
        <p className="mt-3 text-xs text-muted">Loading documents…</p>
      ) : error ? (
        <p role="alert" className="mt-3 rounded border border-red bg-red/10 p-2 text-xs text-[#8C1D18]">
          Could not load documents: {error instanceof Error ? error.message : 'request failed'}
        </p>
      ) : documents.length === 0 ? (
        <p className="mt-3 text-xs text-muted">No documents attached to this case yet.</p>
      ) : (
        <ul className="mt-2 max-h-72 divide-y divide-border overflow-y-auto">
          {documents.map((d) => (
            <li key={d.id} className="py-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-ink" title={d.kind ?? ''}>
                    {titleize(d.kind) || 'Document'}
                    {d.version != null ? (
                      <span className="ml-1 font-normal text-muted">v{d.version}</span>
                    ) : null}
                  </p>
                  <p className="text-[11px] text-muted">{formatTs(d.uploaded_at)}</p>
                </div>
                <button
                  type="button"
                  className="btn shrink-0 px-2 py-0.5 text-xs"
                  onClick={() => open(d.id)}
                  disabled={opening === d.id}
                >
                  {opening === d.id ? 'Opening…' : 'Open'}
                </button>
              </div>
              <p
                className="mt-0.5 truncate font-mono text-[11px] text-muted"
                title={d.sha256 ?? ''}
              >
                sha256 {hashPrefix(d.sha256, 16)}
              </p>
              {d.supersedes_id ? (
                <p className="text-[11px] text-accent2">supersedes an earlier version</p>
              ) : null}
              {d.extraction_status ? (
                <p className="text-[11px] text-muted">
                  extraction: <span className="text-ink">{d.extraction_status}</span>
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
