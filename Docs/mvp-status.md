# MVP status — overnight build of 2026-09-01 → 02

What exists, what was verified, and what is deliberately deferred. Read beside
`final-product.md` §5 (module table). Ports/logins: see the README.

## Verified working (browser-tested end to end, containerized)

- **The demo narrative** (final-product.md §6): LAO signs in → case `LAQ/SEO/2025/01`
  shows the 3D clock red at 93% with consequence text → uploads the 3D gazette PDF
  (`api/seed/demo_uploads/gazette_3D_LAQ-SEO-2025-01.pdf`) → regex extraction proposes
  DECLARATION_3D with 12 fields + confidence → confirm → committed with hash; stage
  NOTIFIED→DECLARED; 3D clock closed; award clock starts. Dashboard, alerts, public
  page update; every KPI carries "as of seq N" + Explain.
- Event ledger with per-case SHA-256 hash chain; integrity endpoint; idempotent append;
  transition/precondition/guard validation from rule-sets-as-data (RFCTLARR 2013 + NH
  Act 1956 YAML); clock engine (calendar months per General Clauses Act, extensions,
  court stays, breach consequences emitted as system actor).
- Documents in MinIO (content-addressed, presigned URLs), gazette regex extraction
  (offline; LLM hook behind `LLM_EXTRACTION_URL`), parcels GeoJSON + PostGIS areas +
  Leaflet map, First Schedule compensation with s.38 possession gate, alerts with
  escalation ladder, national dashboard, bilingual public status page.
- Backend test suite: 58+ tests incl. statutory fixtures (s.19(7) rescission, extension,
  stay suspension, s.25, s.38 gate, urgency 80%, tamper detection, idempotent replay).

An independent adversarial review (16 findings, all reproduced by execution) ran the
night of the build; the criticals and highs were fixed the same night with regression
tests. Its full report: session task output `wt3x1d7z4` (see git history for the fix
commit).

## Known deferrals (post-MVP; ordered by likely judge interest)

| Area | State | Note |
|---|---|---|
| Back-dated event rewinds clock projection | Deferred | Recording a payment with a past `occurred_at` re-evaluates clocks as of that date until the next sweep/read corrects it. Clamp planned. |
| Un-lapse / reinstatement flow | Partial | `EVENT_REVERSED` is appendable everywhere (audit-visible correction marker) but does not itself restore a stage; a wrongly-lapsed case needs a rebuild story. |
| R&R module (families, Second Schedule heads) | Not built | MVP column says "—" (final-product.md §5F). Tables exist; `families_affected` KPI reads 0. |
| Hindi i18n on case screens | Wiring only | Login/public/dashboard carry bilingual labels; case page + wizard are English. i18next is set up. |
| UI role gating | API-only | Extend/record buttons show for all roles; the API enforces (404/422). Thread roles from /auth/me. |
| Top-risk table badge | Cosmetic | Shows "On time" for a running clock at 87%; needs elapsed from API. |
| Reports (POST /reports), district choropleth, admin users/overlay-upload, webhooks | Not built | APIs.md documents the contract. |
| KML/zipped-SHP parcel import | 422 with message | GeoJSON path works. |
| OCR for scanned PDFs | Not enabled | Text-layer PDFs extract; scanned → `ocr=true` warning, no proposal. |
| OSM basemap tiles | Network | Leaflet CSS is bundled; tiles still fetch from OSM. Finale needs an offline tile pack (rules.md A4). |
| Public rate limit | nginx-level | 60 req/min via `limit_req` in `web/nginx.conf`; API itself unthrottled. |
| PII encryption plumbing | Schema only | `pii_enc` columns exist; no families seeded, no decrypt path yet (DPDP §C5). |
| Ruleset version sort | Lexicographic | `2026.9` would outrank `2026.10`; use zero-padded minor versions until fixed. |

## Demo-day notes

- `make demo` (first boot seeds). Web http://localhost:3016 · API docs :8016/api/v1/docs.
- Reset to pristine: `make destroy && make demo` (drops volumes, re-seeds).
- The 3D upload file lives at `api/seed/demo_uploads/gazette_3D_LAQ-SEO-2025-01.pdf`;
  the 3A twin is already attached to the case.
- Time travel: the demo-date picker in the header sends `X-Demo-Date` (DEMO_MODE only).
- Statute captions marked *(verify)* in the rulesets (NH award clock via the 2015
  order, s.40 80%) must be checked by the domain owner before any stage appearance
  (rules.md, Key-Points.md).
