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

## Stage 2 (2026-09-02) — delivered

R&R families module (F), integration adapters (J), report exports, district
dashboards, admin rule-set diff viewer + Maharashtra overlay, and the four deferred
statutory fixes. Test harness now runs in its own database (`bhuarjan_test`) with a
per-process schema — five parallel lanes had been dropping each other's shared
schema and silently writing into the demo data. 159 backend tests.

## Known deferrals (ordered by likely judge interest)

| Area | State | Note |
|---|---|---|
| Back-dated event rewinds clock projection | Done | Evaluation date is clamped to the case's frontier (`events/service.py::_evaluation_date`); a late-recorded payment cannot un-breach a clock. |
| Un-lapse / reinstatement flow | Partial | `EVENT_REVERSED` is Collector-level, must name an event of the same case, and unwinds money projections (payment/assessment), the award lines (`compensation/service.py::recompute_allocations`), a `COMPENSATION_PAID_FULL` the withdrawn payment bought, and the enumeration of a withdrawn family (row flagged, PII erased). It does not restore a stage, and reversing a reversal is refused with a 422 rather than silently doing nothing. |
| R&R module (families, Second Schedule heads) | Done | Second/Third Schedule heads as data; enumeration + per-head delivery on the ledger; PII AES-GCM, masked by default, unlocked for Collector/Admin R&R with a purpose, every read audited. 9 families seeded. Case-page R&R tab with purpose dialog. The s.38(1) clocks close on a predicate over the whole census (`rules/predicates.py`), not on the first delivery: every applicable Schedule head, every family. |
| Hindi i18n on case screens | Wiring only | Login/public/dashboard carry bilingual labels; case page + wizard are English. i18next is set up. |
| UI role gating | Done (core) | Record = LAO/Collector/State; Extend = Collector/State; no-document path = Collector-level, enforced server-side too (rules.md C1). Finer per-screen gating remains. |
| Top-risk table badge | Done | API now sends `level`/`elapsed_pct`; badge shows amber/red honestly. |
| Reports | Done (csv, geojson) | Synchronous jobs, MinIO-stored, `# as_of_seq=N` header + sha256 `report_hash`; PDF format not built. |
| District dashboards | Done | `/districts/:district` reuses the national layout (duplicated ~450 lines — factor into a shared view later); `/states/:state` backend exists, no page yet. |
| Integration adapters (Module J) | Done (mock) | Six adapters behind one interface answering from real tables/ledger/PDFs/MinIO; admin screen shows `mock` honestly; DigiLocker stamps nothing, eSign absent. |
| Admin rule-set diff | Done | Overlay merge in the loader; MH overlay shipped (illustrative, *(verify)*); `/admin/rulesets/diff` unified diff rendered on the admin page. |
| District choropleth, admin users/overlay-upload, webhooks, PDF reports | Not built | APIs.md documents the contract. |
| KML/zipped-SHP parcel import | 422 with message | GeoJSON path works. |
| OCR for scanned PDFs | Not enabled | Text-layer PDFs extract; scanned → `ocr=true` warning, no proposal. |
| OSM basemap tiles | Network | Leaflet CSS is bundled; tiles still fetch from OSM. Finale needs an offline tile pack (rules.md A4). |
| Public rate limit | nginx-level | 60 req/min via `limit_req` in `web/nginx.conf`; API itself unthrottled. |
| PII encryption plumbing | Done | `persons_interested.pii_enc` written/read via `app/core/crypto.py`; the key comes from `settings.PII_KEY` and the API refuses to start outside `DEMO_MODE` without a real 64-hex key; no PII in ledger payloads (tested). |
| Ruleset version sort | Done | Natural numeric ordering (`2026.9` < `2026.10`); overlays never become the no-pin default. |

## Demo-day notes

- `make demo` (first boot seeds). Web http://localhost:3016 · API docs :8016/api/v1/docs.
- Reset to pristine: `make destroy && make demo` (drops volumes, re-seeds).
- The 3D upload file lives at `api/seed/demo_uploads/gazette_3D_LAQ-SEO-2025-01.pdf`;
  the 3A twin is already attached to the case.
- Time travel: the demo-date picker in the header sends `X-Demo-Date` (DEMO_MODE only).
- Statute captions marked *(verify)* in the rulesets (NH award clock via the 2015
  order, s.40 80%) must be checked by the domain owner before any stage appearance
  (rules.md, Key-Points.md).
