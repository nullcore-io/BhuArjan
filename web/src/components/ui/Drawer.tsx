/**
 * Right-hand drawer used by the dashboard's Explain link.
 *
 * Keyboard-navigable per Docs/Frontend.md §9: Escape closes, focus lands on
 * the panel when it opens, and the close control is a real button.
 */
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

export default function Drawer({
  open,
  title,
  subtitle,
  onClose,
  children,
}: {
  open: boolean
  title: string
  subtitle?: ReactNode
  onClose: () => void
  children: ReactNode
}) {
  const panelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    panelRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-breached/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="relative flex h-full w-full max-w-2xl flex-col border-l border-border bg-bg shadow-none focus:outline-none"
      >
        <div className="flex items-start justify-between gap-4 border-b border-border bg-surface px-4 py-3">
          <div>
            <h2 className="text-base font-bold text-ink">{title}</h2>
            {subtitle ? <div className="text-xs text-muted">{subtitle}</div> : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn"
            aria-label="Close panel"
          >
            Close
          </button>
        </div>
        <div className="flex-1 overflow-auto px-4 py-3">{children}</div>
      </div>
    </div>
  )
}
