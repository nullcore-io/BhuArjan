/**
 * The single source of colour truth — Docs/design.md §1.
 *
 * Imported by BOTH `tailwind.config.js` (so utility classes are generated from
 * it) and `src/theme/charts.ts` (so Recharts marks are generated from it). It
 * exists because the dashboards previously carried their own hardcoded `const C`
 * palette which silently drifted out of sync with the tokens.
 *
 * Plain .mjs, not .ts: PostCSS loads the Tailwind config in Node, which cannot
 * import TypeScript. Types live beside it in palette.d.ts.
 */
export const palette = {
  // Surface model (design.md §1, amended): cards are WHITE and sit on a tinted
  // page. Grey cards with a hard border on white read as a 2004 intranet; a
  // white plane lifted off a tint is what makes a dense UI feel current.
  bg: '#FFFFFF', //           cards, panels, chart ground
  surface: '#F4F6F9', //      page background
  surface2: '#EFF2F6', //     table stripe / hover, inset wells
  border: '#E4E9EF', //       hairline — lighter now that elevation does the work
  borderStrong: '#D3DAE3', // emphasized divider, form controls
  strong: '#C3CAD3', //       --border-strong   emphasized divider
  ink: '#0F1F3D', //          --ink             primary text
  muted: '#4A5568', //        --ink-secondary   supporting text, axis labels
  accent: '#1F4E9C', //       --accent          primary actions, links
  accentHover: '#163D7D', //  --accent-hover
  accent2: '#B9770E', //      --accent-2        active underline, brand
  ok: '#2E7D32', //           --ok              clock running
  red: '#B3261E', //          --red             clock 90%+ / breached
  breached: '#1B1B1B', //     --black           clock lapsed

  // DEVIATION — design.md says #8891A0, measured 3.18:1 on white; §5 mandates
  // 4.5:1 and it is used for placeholder/hint TEXT. Darkened until it clears AA
  // against the CARD surfaces (4.86:1 on --surface, 4.53:1 on --surface-sunken),
  // not merely against white — cards are the tinted plane in design.md §1, so
  // white is the wrong reference. Guarded by e2e/charts-a11y.spec.ts.
  hint: '#656E7A',
  // DEVIATION — design.md says #C77700 (3.46:1); darkened to 4.10:1.
  amber: '#B96A00',

  // Brand only — masthead tricolour rule. Never carries status meaning.
  saffron: '#FF9933',
  deepgreen: '#138808',
}
