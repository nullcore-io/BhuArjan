# Frontend.md — Screens, components, and the government look

Stack: **React 18 + TypeScript · Vite · React Router · TanStack Query · Zustand (UI state only) · Leaflet + react-leaflet (mirrors the PS's suggested GIS stack) · Recharts · react-i18next (en, hi) · Tailwind with a restrained token set · Vitest + Playwright.** PWA with an IndexedDB outbox for field mode.

Design stance: this is a government system of record, not a startup dashboard. Dense tables, clear hierarchy, statutory references visible everywhere, no gradients, no illustrations. Every screen must pass a GIGW 3.0 sanity check (bilingual, keyboard-navigable, WCAG 2.1 AA contrast).

---

## 1. Information architecture (routes)

```
/login
/                         → role landing (redirect)
/national                 Ministry dashboard
/states/:state            State dashboard
/districts/:district      District dashboard
/projects                 Project list (scoped)
/projects/:id             Project page (cases, map, KPIs)
/cases/:id                Case page  ← the product
/cases/:id/record         Record event: upload → extraction review → confirm
/cases/:id/parcels        Parcel table + import
/cases/:id/compensation   Award lines, payments, outstanding
/cases/:id/rr             Families & entitlements (restricted)
/alerts                   Alert centre (scoped)
/reports                  MIS report builder + exports
/public                   Citizen status lookup (no auth)
/admin/users  /admin/rulesets  /admin/integrations
```

Role → landing: Ministry → `/national`; State → `/states/:state`; Collector/LAO → `/districts/:district`; RB → `/projects`; Auditor → `/projects` read-only; Citizen → `/public`.

## 2. The case page (where the demo lives)

Layout: three columns on desktop, stacked on tablet.

```
┌ Header: case no · project · statute track (badge) · stage (badge) · risk score ┐
├───────────────────┬──────────────────────────────┬─────────────────────────────┤
│ Clock panel       │ Statutory timeline            │ Documents                   │
│ • per clock:      │ horizontal stages with dates; │ list with kind, date, hash, │
│   name, s. basis, │ current stage highlighted;    │ version; preview drawer     │
│   start → due,    │ future stages show due dates  │                             │
│   elapsed bar     │ from clocks                   ├─────────────────────────────┤
│   (amber/red),    ├──────────────────────────────┤ Parcels map (Leaflet)       │
│   consequence,    │ Ledger                        │ polygons coloured by        │
│   Extend / Record │ append-only list: seq, type,  │ possession status; click →  │
│   buttons         │ occurred_at, actor, doc, hash │ survey no, ULPIN, area      │
├───────────────────┴──────────────────────────────┴─────────────────────────────┤
│ Tabs: Compensation · R&R · Objections · Alerts · Integrity                      │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Components:
- `ClockCard` — props from `GET /cases/:id/clocks`; shows `basis` and `consequence` text verbatim; actions gated by role (`Extend` → Collector/State only; `Record terminating event` → LAO).
- `StatutoryTimeline` — stages from the rule-set; dates from events; dashed future stages; hover shows section.
- `Ledger` — virtualized list; each row expandable to payload + document link + hash; "Explain" on any KPI opens this filtered to contributing events.
- `DocumentDrawer` — PDF.js preview with extraction spans highlighted.
- `ParcelMap` — Leaflet; layers: parcels (GeoJSON from API), village boundary (if available), basemap (OSM tiles cached for demo). Legend: notified / awarded / paid / possessed / disputed.
- `IntegrityBadge` — chain verified ✓ / mismatch ✗ with last check time.

## 3. Record-event flow (`/cases/:id/record`)

Step 1 **Choose event** — dropdown restricted to allowed transitions from the current stage (from `GET /cases/:id/allowed-events`); each option shows its section.
Step 2 **Upload document** — drag-drop PDF/JPG; shows hash on upload; duplicate detection message.
Step 3 **Extraction review** — two-pane: PDF left with highlighted spans; form right with fields, confidence chips (green ≥0.9, amber 0.7–0.9, red <0.7 must be touched), `corrected` markers. Occurred-at date defaults to extracted publication date.
Step 4 **Confirm** — summary of the event, preconditions check (e.g. "R&R scheme published ✓", "Cost deposited ✗ — cannot declare") with links to fix; commit button disabled until preconditions pass.
Step 5 **Committed** — seq, hash, updated clocks; "Record next" suggestion.

## 4. Dashboards

`/national`, `/states/:state`, `/districts/:district` share one layout:
- KPI tiles (exact PS wording): Area notified · Area acquired · Compensation assessed · Compensation paid · Affected families · Displaced families · R&R status · Possession status · Timeline adherence.
- Charts (Recharts): assessed vs paid over time; stage funnel (notified → declared → awarded → possessed); clock health (running/amber/red/breached/lapsed) as stacked bar by state/district.
- Map: choropleth of districts by timeline adherence (Leaflet + GeoJSON of district boundaries).
- Tables: top-risk cases (risk score, next due clock, days left), lapsed/rescinded in period.
- Every tile has "as of seq N" and an Explain link.
- Filters: sector, statute track, requiring body, date range. Export: CSV/PDF with report hash.

## 5. Alert centre

Scoped list: level, case, clock, due date, escalated-to, age. Acknowledge (records `acknowledged_by`), open case. Sorting by days-to-due ascending by default. Badge count in nav.

## 6. Compensation and R&R screens

- **Compensation**: award lines per parcel/owner (owner shown as masked reference unless role permits PII), MV, factor, assets, solatium, interest, total, paid, outstanding; PFMS references; "Possession gate" indicator (paid ≥ assessed).
- **R&R** (restricted roles): family table with entitlement heads as columns (Second/Third Schedule), status per cell (due/delivered/overdue) with s.38 timelines; evidence document per delivery. PII revealed only after a purpose dialog; the read is audited and the UI says so.

## 7. Public status page (`/public`)

Single input: ULPIN or state/district/village/survey no. Output: project name, statute, current stage with date, next statutory milestone and due month, area, compensation assessed vs paid (aggregate), possession status. No names, no identifiers, no documents. Bilingual by default; large type; works on a 360-px phone.

## 8. Admin

- Users & roles with jurisdiction picker (org-unit tree).
- Rule-sets: list of tracks and overlays with version, effective date, diff viewer (base vs overlay) — this screen is shown on stage.
- Integrations: adapter status (mock/live), last sync, test call.

## 9. i18n and accessibility

- English and Hindi from day one via react-i18next; all statutory terms have both forms (e.g. "Preliminary notification / प्रारंभिक अधिसूचना"). Numbers in Indian grouping; dates dd-mm-yyyy; ₹ with lakh/crore toggle.
- Font: Noto Sans + Noto Sans Devanagari.
- Keyboard-navigable everything; focus rings visible; ARIA on tables and map alternatives (parcel table always available).
- Contrast AA; never colour alone — clock levels also carry text labels.

## 10. Design tokens

**Superseded by [`design.md`](design.md).** The palette, type scale, weight system and
component visual treatment now live there as the single source of truth; it is implemented in
`web/tailwind.config.js` and `web/src/styles/index.css`. Structure is unchanged and still
governed by this file: radius 4px, shadows none, borders 1px, table row height 36px.

Three values in `design.md` are deliberately deviated from in the implementation — the amber
token, the focus-ring opacity, and `--ink-muted` — each marked `DEVIATION` in
`web/tailwind.config.js` with the contrast measurement that justifies it.

## 11. Field mode (PWA)

- Installable; caches shell, rule-sets, assigned cases.
- Outbox: event drafts and document uploads queued in IndexedDB; sync on connectivity with idempotency keys; conflicts (e.g. stage changed server-side) surface as "rebase required".
- Camera capture for site documents and possession photos with GPS tag.

## 12. Performance

- Route-level code splitting; ledger and tables virtualized; GeoJSON simplified server-side per zoom; map tiles cached for demo; dashboards read materialized views.
- Demo laptop target: first paint < 1.5 s, case page interactive < 2 s with 500 events.

## 13. Testing

- Vitest for clock rendering states and role gating; Playwright end-to-end: record event from upload to commit; public lookup; dashboard explain.
- Visual regression on the case page (the slide screenshots come from here).
