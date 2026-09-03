/**
 * The thin strip above the masthead that Indian government portals carry:
 * government attribution, skip-to-content, text sizing, high contrast and the
 * language toggle (GIGW 3.0 §§ accessibility + bilingual).
 *
 * Presentation only — it changes how the page renders, never what it fetches.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  getContrast,
  getTextSize,
  setContrast,
  setTextSize,
  type Contrast,
  type TextSize,
} from '../../lib/prefs'

const SIZES: { key: TextSize; label: string; title: string }[] = [
  { key: 'sm', label: 'A-', title: 'Decrease text size' },
  { key: 'md', label: 'A', title: 'Default text size' },
  { key: 'lg', label: 'A+', title: 'Increase text size' },
]

export default function UtilityStrip() {
  const { i18n } = useTranslation()
  const [size, setSize] = useState<TextSize>(getTextSize)
  const [contrast, setContrastState] = useState<Contrast>(getContrast)
  const lang = i18n.language?.startsWith('hi') ? 'hi' : 'en'

  function chooseSize(v: TextSize) {
    setTextSize(v)
    setSize(v)
  }

  function toggleContrast() {
    const next: Contrast = contrast === 'high' ? 'normal' : 'high'
    setContrast(next)
    setContrastState(next)
  }

  function chooseLang(v: 'en' | 'hi') {
    i18n.changeLanguage(v)
    try {
      localStorage.setItem('bhuarjan.lang', v)
    } catch {
      /* non-fatal */
    }
  }

  return (
    <div className="no-print border-b border-border bg-surface2 text-xs text-muted">
      <div className="mx-auto flex max-w-screen-2xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1">
        <span className="font-semibold text-ink">
          भारत सरकार
          <span className="mx-1.5 font-normal text-muted">|</span>
          Government of India
        </span>
        <span className="hidden sm:inline">Ministry of Rural Development · Department of Land Resources</span>

        <div className="ml-auto flex items-center gap-x-3">
          <a href="#main" className="sr-only-focusable">
            Skip to main content
          </a>

          {/* text size */}
          <div className="flex items-center gap-0.5" role="group" aria-label="Text size">
            {SIZES.map((s) => (
              <button
                key={s.key}
                type="button"
                title={s.title}
                aria-pressed={size === s.key}
                onClick={() => chooseSize(s.key)}
                className={`rounded border px-1.5 leading-5 ${
                  size === s.key
                    ? 'border-accent bg-accent text-white'
                    : 'border-border bg-bg hover:bg-surface'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={toggleContrast}
            aria-pressed={contrast === 'high'}
            title="Toggle high contrast"
            className={`rounded border px-1.5 leading-5 ${
              contrast === 'high'
                ? 'border-breached bg-breached text-white'
                : 'border-border bg-bg hover:bg-surface'
            }`}
          >
            ◐ Contrast
          </button>

          {/* language */}
          <div className="flex items-center gap-0.5" role="group" aria-label="Language">
            <button
              type="button"
              aria-pressed={lang === 'en'}
              onClick={() => chooseLang('en')}
              className={`rounded border px-1.5 leading-5 ${
                lang === 'en' ? 'border-accent bg-accent text-white' : 'border-border bg-bg hover:bg-surface'
              }`}
            >
              English
            </button>
            <button
              type="button"
              aria-pressed={lang === 'hi'}
              onClick={() => chooseLang('hi')}
              className={`rounded border px-1.5 leading-5 ${
                lang === 'hi' ? 'border-accent bg-accent text-white' : 'border-border bg-bg hover:bg-surface'
              }`}
            >
              हिन्दी
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
