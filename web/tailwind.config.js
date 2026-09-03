/**
 * Design tokens — implements Docs/design.md §1 (palette) and §2 (typography).
 *
 * design.md is the source of truth for look and feel and supersedes
 * Frontend.md §10. Three values deliberately deviate; each is marked DEVIATION
 * below with the measurement that justifies it.
 *
 * Tailwind key names are load-bearing (≈850 usages in src/) so the original
 * eleven keep their names; design.md's semantic names are given beside them.
 */
import { palette } from './src/theme/palette.mjs'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    // fontSize is REPLACED, not extended: design.md §2 defines a closed
    // six-step scale, so an off-scale class must fail loudly rather than
    // silently resolve to some other size.
    // §2: two weights carry the system, 600 is reserved and used sparingly.
    // Replaced, not extended — `font-bold` (700) must not resolve.
    fontWeight: { normal: '400', medium: '500', semibold: '600' },
    fontSize: {
      xs: ['0.75rem', { lineHeight: '1rem' }], //     12 — table meta, timestamps, badges
      sm: ['0.875rem', { lineHeight: '1.5' }], //     14 — body, form labels, table cells
      base: ['1rem', { lineHeight: '1.5' }], //       16 — section headers, card titles
      lg: ['1.125rem', { lineHeight: '1.3' }], //     18 — page subheaders
      '2xl': ['1.5rem', { lineHeight: '1.3' }], //    24 — page titles, KPI numbers
      hero: ['2rem', { lineHeight: '1.2' }], //       32 — dashboard hero numbers only
    },
    extend: {
      colors: {
        // Every value comes from src/theme/palette.mjs so the charts and the
        // utility classes cannot drift apart. Keys keep their historical names
        // (~850 usages); design.md's semantic name is noted in the palette file.
        bg: palette.bg,
        surface: palette.surface,
        surface2: palette.surface2,
        border: palette.border,
        strong: palette.borderStrong,
        ink: palette.ink,
        muted: palette.muted,
        accent: palette.accent,
        'accent-hover': palette.accentHover,
        accent2: palette.accent2,
        ok: palette.ok,
        amber: palette.amber,
        red: palette.red,
        breached: palette.breached,
        hint: palette.hint,
        saffron: palette.saffron,
        deepgreen: palette.deepgreen,
      },
      // Amended from design.md's flat 4px. Cards read as objects at 8px;
      // controls stay tighter so a form still feels like a form.
      borderRadius: {
        DEFAULT: '6px', // buttons, inputs
        sm: '4px', //     badges, chips, swatches
        card: '10px', //  cards, panels, modals
      },
      // One barely-there elevation. Not decoration — it is what separates a
      // card from the page now that the border is nearly invisible.
      boxShadow: {
        card: '0 1px 2px rgba(15,31,61,0.04), 0 1px 3px rgba(15,31,61,0.06)',
        raised: '0 2px 4px rgba(15,31,61,0.06), 0 6px 16px rgba(15,31,61,0.08)',
      },
      fontFamily: {
        sans: ['"Noto Sans"', '"Noto Sans Devanagari"', 'system-ui', 'sans-serif'],
      },
      spacing: {
        row: '2.25rem', //   36px — dense tables (ledger, risk queue)
        rowlg: '2.75rem', // 44px — default, comfortable scanning
      },
      maxWidth: { prose: '70ch' }, // §2: 65–75 characters
    },
  },
  plugins: [],
}
