/**
 * Copy-to-clipboard control, used for report hashes and sequence numbers.
 *
 * A report hash is the whole point of an export (Docs/rules.md C7): it has to be
 * transcribable into a file note or an email without a typo. `navigator.clipboard`
 * only exists in a secure context, so there is a selection fallback — and if both
 * paths fail the button says "Copy failed" rather than showing a tick it has not
 * earned. Silently pretending to copy an integrity hash is exactly the class of
 * small lie this system exists to remove.
 */
import { useEffect, useRef, useState } from 'react'

type State = 'idle' | 'copied' | 'failed'

/** Selection-based fallback for browsers without the async clipboard API. */
function legacyCopy(text: string): boolean {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.top = '-1000px'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  document.body.removeChild(ta)
  return ok
}

export default function CopyButton({
  value,
  label = 'Copy',
  title,
  className = 'btn text-xs',
}: {
  value: string | null | undefined
  label?: string
  title?: string
  className?: string
}) {
  const [state, setState] = useState<State>('idle')
  const timer = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    },
    [],
  )

  function settle(next: State) {
    setState(next)
    if (timer.current !== null) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setState('idle'), 2500)
  }

  async function onClick() {
    const text = String(value ?? '')
    if (!text) return settle('failed')
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
        return settle('copied')
      }
    } catch {
      /* fall through to the selection fallback */
    }
    settle(legacyCopy(text) ? 'copied' : 'failed')
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!value}
      className={className}
      title={title ?? (value ? `Copy ${value}` : 'Nothing to copy')}
      aria-live="polite"
    >
      {state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : label}
    </button>
  )
}
