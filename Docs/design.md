# design.md — Visual redesign: palette, typography, components

Status: approved direction, ready to implement in `web/`. This document covers **look and feel only**
— colors, type, and component visual treatment. It does not change IA, routes, data flow, or the
component inventory; those stay as defined in `Frontend.md`. Where this file and `Frontend.md §10`
(Design tokens) disagree, this file wins — `Frontend.md §10` should be updated to match once this
lands.

Direction chosen: **A — Refined institutional** (navy + saffron, polished). Two other directions
were evaluated and rejected:
- *Slate & teal* — sharper and more "analytical," but reads closer to a generic SaaS/fintech
  dashboard than a government system of record; risks the exact anti-pattern called out in
  `Key-Points.md` ("the generic admin template everyone else builds").
- *Earth & maroon* — most distinctly "government of India," but maroon-as-primary is harder to
  keep crisp across dense tables and needed more restraint than the timeline allows.

---

## 1. Design tokens

| Token | Value | Use |
|---|---|---|
| `--bg` | `#FFFFFF` | page background |
| `--surface` | `#F7F8FA` | cards, panels |
| `--surface-sunken` | `#EEF0F3` | table row stripe/hover |
| `--border` | `#D9DEE5` | default hairline |
| `--border-strong` | `#C3CAD3` | emphasized divider |
| `--ink` | `#0F1F3D` | primary text, headers |
| `--ink-secondary` | `#4A5568` | supporting text |
| `--ink-muted` | `#8891A0` | placeholders, hints |
| `--accent` | `#1F4E9C` | primary actions, links |
| `--accent-hover` | `#163D7D` | button/link hover |
| `--accent-2` | `#B9770E` | sparing: active-tab underline, brand marks only — never a CTA color |
| `--ok` | `#2E7D32` | clock running/healthy |
| `--amber` | `#C77700` | clock 75%+ elapsed |
| `--red` | `#B3261E` | clock 90%+ / breached |
| `--black` | `#1B1B1B` | clock lapsed |

**Amended 2026-09-03 — surface & density revision.** The original rule here was
`radius 4px · shadows none · borders 1px · row height 36px`. Flat *and* tight is the one
combination that always reads as cramped, and it was making the build look dated. Revised:

| | Was | Now |
|---|---|---|
| Card radius | 4px | **10px** (controls 6px, badges 4px) |
| Elevation | none | **one hairline shadow** `0 1px 2px rgba(15,31,61,.04), 0 1px 3px rgba(15,31,61,.06)` |
| Card surface | `--surface` on a white page | **white card on a `--surface` page** |
| Border | 1px `#D9DEE5` | 1px `#E4E9EF` — the elevation now does the separating |
| Card padding | (12px in practice) | **20px**, inside the 16–24px this file already asked for |
| Table row | 36px | **44px** default; `.dense` opts back to 36px for the ledger and risk queue, where rows-per-screen beats comfort |

Everything that signals *government* is untouched: no gradients, no illustrations, no
marketing imagery, statutory citations on every figure, bilingual labels, dense data tables.
Whitespace reads as authoritative, not playful — Polaris and USWDS are both business systems
and both are spacious.

`--accent` and `--amber`/`--red` are deliberately different hues (blue vs. amber/red) so that a
primary action button is never visually confused with a clock-warning state.

## 2. Typography

Font stack unchanged: **Noto Sans** (Latin) + **Noto Sans Devanagari** (Hindi), per `Frontend.md §9`.

**Type scale** (px): `12 · 14 · 16 · 18 · 24 · 32`
- 12 — table meta, timestamps, badge text
- 14 — body default, form labels, table cells
- 16 — section headers, card titles
- 18 — page subheaders
- 24 — page titles, KPI tile numbers
- 32 — dashboard hero numbers only (national/state KPI tiles)

**Weight system** — two weights carry the whole system, a third is reserved:
- 400 (regular) — body text, table cells, descriptions
- 500 (medium) — labels, form field labels, table headers, badges
- 600 (semibold) — page titles, KPI numbers, section headers only — used sparingly, not on every heading

**Numerals:** all numeric data columns (compensation amounts, area in hectares, day-counts on
clocks, ULPIN/survey numbers) use `font-variant-numeric: tabular-nums` so figures align vertically
in tables and don't shift width as values change — this matters here specifically because the
ledger and compensation tables update live during the demo.

**Line length / height:** body text 65–75 characters per line max; line-height 1.5 for body,
1.3 for headings.

## 3. Component treatment

- **Buttons** — primary: `--accent` fill, white text, 6px radius, no shadow. Secondary: outline
  `--accent`, transparent fill. Ghost: text-only, `--ink-secondary`. One primary button per screen —
  every other action is secondary or ghost (e.g. on the case page, "Record event" is the only
  primary; "Extend", "Export" are secondary).
- **Status chips/badges** — pale tint background + dark text from the *same* hue family (never
  plain gray on a colored background). Always paired with a text label, e.g. "Amber · 78%" — never
  color alone, both for accessibility and because clock status is legally meaningful here.
- **Tables** — 36px row height, `--surface-sunken` on hover/stripe, sticky header, numeric columns
  right-aligned with tabular numerals, sortable columns carry `aria-sort`.
- **Nav/header** — *amended:* a **white** bar with `--ink` text and `--accent-2` (saffron) as the
  active-item underline only — the GOV.UK / USWDS pattern. A full-bleed navy band reads heavier
  and older; navy now identifies in the masthead wordmark instead. Still never a fill or a button
  colour.
- **Forms** — visible labels always (never placeholder-as-label), inline error text in `--red`
  below the field with a specific cause + fix (not "Invalid input"), focus ring 2px `--accent` at
  40% opacity, required fields marked with an asterisk.
- **Cards** — `--bg` (white) background on a `--surface` page, 1px `--border` hairline,
  10px radius, one hairline shadow, 20px padding. See the amendment in §1.

## 4. Charts & data-viz accessibility

BhuArjan's dashboards (Recharts: assessed-vs-paid, stage funnel, clock-health stacked bars,
district choropleth) carry real statutory meaning, not decoration, so these are hard requirements,
not nice-to-haves:

- **Never red/green-only.** The clock-health stacked bar (running/amber/red/breached/lapsed) must
  pair each color with a text label or pattern — a colorblind viewer must be able to read status
  without relying on hue alone. This is already the rule for badges (§3); it applies equally inside
  chart legends and stacked-bar segments.
- **Contrast minimums** — data lines/bars against background ≥3:1; any text label on a chart
  (axis labels, data labels, tooltips) ≥4.5:1.
- **Every chart needs a table alternative** — required for accessibility, since charts alone are
  not screen-reader friendly. BhuArjan already does this for parcels (map + table together) — this
  section makes it an explicit requirement for every chart, not an incidental outcome.
- **Legends stay visible**, positioned near the chart, not below a scroll fold; legend items are
  clickable to toggle series visibility.
- **Gridlines subtle** — low-contrast gray, never competing visually with the data itself.
- **Tooltips are keyboard-reachable**, not hover-only.

## 5. Accessibility (carried forward from `Frontend.md §9`)

WCAG 2.1 AA contrast (4.5:1 body text), keyboard-navigable everything, visible focus rings,
bilingual labels (en/hi) on every statutory term, color never used as the sole signal anywhere in
the system — badges, charts, or clock cards alike.

## 6. Open items

- `Frontend.md §10` should be updated to point to this file once the palette lands in `web/`, so
  there's one source of truth instead of two token tables.
- Dark mode is not in scope for this pass — the whole product stance (`Frontend.md`) is a single
  light theme; revisit only if a future round asks for it.
