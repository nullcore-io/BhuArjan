# Backend.md — Ledger, rules engine, extraction, projections

Stack: **Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 + PostGIS 3.4 · MinIO (S3 API) · Redis (queue) · APScheduler/Celery worker · Pydantic v2**. NestJS is an acceptable swap if the team is Node-native; the design below is language-agnostic.

Why event sourcing: the PS asks for audit history, version control, dashboards and alerts. One append-only log gives all four, and it is the design an NIC engineer will respect.

---

## 1. Repository layout

```
bhuarjan/
  api/                 # FastAPI app
    app/
      main.py
      core/            # config, security, db, audit middleware
      domain/
        events/        # event types, append service, hash chain
        rules/         # rule-set loader, state machine, clock engine
        cases/         # case aggregate, projections
        documents/     # storage, extraction pipeline
        parcels/       # PostGIS import/export
        compensation/  # First Schedule computation
        rr/            # R&R entitlements
        alerts/        # thresholds, escalation
        dashboards/    # aggregation queries
        integrations/  # adapters: ulpin, pfms, gazette, digilocker, gatishakti
      api/v1/          # routers
    rulesets/          # YAML: rfctlarr_2013.yaml, nh_act_1956.yaml, overlays/
    tests/             # statutory fixtures, clock tests
  worker/              # extraction + clock evaluation + notifications
  infra/               # docker-compose.yml, init.sql, nginx
  seed/                # gazette scraper, seed scripts
```

## 2. Data model

Principle: **the `events` table is the truth; everything else is a projection that can be rebuilt.** Reference tables (users, projects, parcels, documents) are stored normally; case state, KPIs and clocks are derived.

```sql
-- identity & jurisdiction
CREATE TABLE org_units (
  id uuid PRIMARY KEY, kind text NOT NULL,          -- ministry|state|district|requiring_body
  name text NOT NULL, parent_id uuid REFERENCES org_units(id),
  lgd_code text                                      -- Local Government Directory code
);
CREATE TABLE users (
  id uuid PRIMARY KEY, email text UNIQUE, name text, active bool DEFAULT true
);
CREATE TABLE role_assignments (
  user_id uuid REFERENCES users(id), role text NOT NULL,
  org_unit_id uuid REFERENCES org_units(id),         -- jurisdiction scope
  PRIMARY KEY (user_id, role, org_unit_id)
);

-- projects & cases
CREATE TABLE projects (
  id uuid PRIMARY KEY, name text NOT NULL, sector text,
  requiring_body_id uuid REFERENCES org_units(id),
  statute_track text NOT NULL,                       -- 'RFCTLARR_2013' | 'NH_ACT_1956' | ...
  ruleset_version text NOT NULL,                     -- pinned at creation
  state_code text, created_at timestamptz DEFAULT now()
);
CREATE TABLE cases (                                  -- one acquisition proceeding (one s.11 / 3A)
  id uuid PRIMARY KEY, project_id uuid REFERENCES projects(id),
  district_id uuid REFERENCES org_units(id), case_no text,
  statute_track text NOT NULL, ruleset_version text NOT NULL,
  created_at timestamptz DEFAULT now()
);

-- the ledger
CREATE TABLE events (
  seq bigserial PRIMARY KEY,                          -- global order
  id uuid UNIQUE NOT NULL,
  case_id uuid NOT NULL REFERENCES cases(id),
  type text NOT NULL,
  occurred_at date NOT NULL,                          -- legal date (e.g. gazette publication)
  recorded_at timestamptz NOT NULL DEFAULT now(),
  actor_id uuid NOT NULL REFERENCES users(id),
  payload jsonb NOT NULL,
  document_id uuid,                                   -- REFERENCES documents(id)
  idempotency_key text UNIQUE,
  prev_hash bytea, hash bytea NOT NULL
);
CREATE INDEX ON events (case_id, seq);

-- documents (content-addressed)
CREATE TABLE documents (
  id uuid PRIMARY KEY, case_id uuid REFERENCES cases(id),
  kind text NOT NULL,                                 -- notification_s11|declaration_s19|award|payment|court_order|...
  storage_key text NOT NULL, sha256 bytea NOT NULL,
  mime text, pages int, uploaded_by uuid, uploaded_at timestamptz DEFAULT now(),
  supersedes_id uuid REFERENCES documents(id),
  extraction jsonb, extraction_status text            -- pending|proposed|confirmed|rejected
);

-- parcels & GIS
CREATE TABLE parcels (
  id uuid PRIMARY KEY, case_id uuid REFERENCES cases(id),
  village_lgd text, survey_no text, ulpin text,
  area_ha numeric(12,4),                              -- from geometry unless overridden
  land_type text,                                     -- rural|urban (First Schedule factor)
  geom geometry(MultiPolygon, 4326)
);
CREATE INDEX ON parcels USING gist (geom);

-- persons & families (PII encrypted at application layer)
CREATE TABLE persons_interested (
  id uuid PRIMARY KEY, case_id uuid, parcel_id uuid REFERENCES parcels(id),
  pii_enc bytea NOT NULL,                             -- AES-GCM: name, id numbers, bank
  category text,                                      -- owner|tenant|sharecropper|artisan|...
  sc_st bool, consent_flags jsonb
);
CREATE TABLE affected_families (
  id uuid PRIMARY KEY, case_id uuid, head_person_id uuid REFERENCES persons_interested(id),
  displaced bool, rr_entitlements jsonb                -- heads per Second Schedule + status
);

-- projections (rebuildable)
CREATE TABLE case_state (
  case_id uuid PRIMARY KEY, stage text, as_of_seq bigint,
  area_notified_ha numeric, area_acquired_ha numeric,
  comp_assessed numeric, comp_paid numeric,
  families_affected int, families_displaced int,
  possession_pct numeric, risk_score numeric, updated_at timestamptz
);
CREATE TABLE clocks (
  id uuid PRIMARY KEY, case_id uuid, clock_id text,     -- e.g. AWARD_S23
  basis text, consequence text,
  started_seq bigint, start_date date, due_date date,
  status text,                                          -- running|closed|extended|suspended|breached|lapsed
  closed_seq bigint, suspended_days int DEFAULT 0
);
CREATE TABLE alerts (
  id uuid PRIMARY KEY, case_id uuid, clock_id text, level text,   -- amber|red|black
  raised_at timestamptz, escalated_to_role text, acknowledged_by uuid, acknowledged_at timestamptz
);

-- non-domain audit (logins, role changes, PII reads)
CREATE TABLE admin_audit (
  seq bigserial PRIMARY KEY, at timestamptz DEFAULT now(), user_id uuid,
  action text, target text, meta jsonb
);
```

## 3. Event types (enum)

| Group | Types |
|---|---|
| Project | `PROJECT_CREATED`, `PROPOSAL_SUBMITTED`, `PROPOSAL_SCRUTINY`, `PROPOSAL_APPROVED`, `PROPOSAL_RETURNED` |
| SIA | `SIA_NOTIFIED`, `SIA_PUBLIC_HEARING`, `SIA_REPORT_PUBLISHED`, `EXPERT_GROUP_APPRAISAL`, `GOVT_DECISION_S8`, `SIA_EXEMPTED_S40` |
| Notification | `PRELIM_NOTIFICATION_S11`, `NOTIFICATION_3A`, `SURVEY_COMPLETED_S12`, `OBJECTION_RECEIVED`, `OBJECTIONS_DISPOSED` |
| R&R scheme | `RR_SCHEME_DRAFTED_S16`, `RR_SCHEME_APPROVED_S17`, `RR_SCHEME_PUBLISHED_S18` |
| Declaration | `COST_DEPOSITED_S19_2`, `DECLARATION_S19`, `DECLARATION_3D`, `EXTENSION_GRANTED` (payload: `clock_id`, `authority`, `reasons`, `new_due_date`) |
| Award | `NOTICE_S21`, `CLAIMS_RECEIVED`, `AWARD_S23`, `AWARD_3G`, `RR_AWARD_S31`, `COMPENSATION_ASSESSED` |
| Payment | `PAYMENT_MADE` (payload: `pfms_ref`, `amount`, `payee_ref`), `COMPENSATION_PAID_FULL` |
| Possession | `POSSESSION_TAKEN_S38`, `POSSESSION_3E`, `URGENCY_S40_INVOKED` |
| R&R delivery | `RR_ENTITLEMENT_DELIVERED` (payload: `family_id`, `head`, `evidence_doc`) |
| Legal | `REFERENCE_FILED_S64`, `COURT_STAY`, `STAY_VACATED`, `ARBITRATION_3G5` |
| Closure | `LAND_UTILISED`, `LAND_RETURNED_S101`, `CASE_CLOSED`, `CASE_LAPSED`, `NOTIFICATION_RESCINDED` |
| Parcel/people | `PARCEL_ADDED`, `PARCEL_UPDATED`, `FAMILY_ENUMERATED` |
| Control | `EVENT_REVERSED` (payload: `reversed_event_id`, `reason`) |

## 4. Hash chain

```python
def compute_hash(prev_hash: bytes | None, event: dict) -> bytes:
    canonical = json.dumps(
        {k: event[k] for k in ("id","case_id","type","occurred_at","actor_id","payload","document_id")},
        sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256((prev_hash or b"") + canonical).digest()
```
Append is one transaction: `SELECT hash FROM events WHERE case_id=$1 ORDER BY seq DESC LIMIT 1 FOR UPDATE` → validate transition against the rule-set → insert with `prev_hash`/`hash` → update projections. A nightly job recomputes each case chain and raises an `INTEGRITY` alert on mismatch.

## 5. Rules engine — rule-sets as data

`rulesets/rfctlarr_2013.yaml` (excerpt):

```yaml
track: RFCTLARR_2013
version: 2026.09
stages:
  PROPOSED:        { on: [SIA_NOTIFIED, SIA_EXEMPTED_S40] }
  SIA:             { on: [SIA_PUBLIC_HEARING, SIA_REPORT_PUBLISHED, EXPERT_GROUP_APPRAISAL, GOVT_DECISION_S8] }
  APPRAISED:       { on: [PRELIM_NOTIFICATION_S11] }
  NOTIFIED:        { on: [SURVEY_COMPLETED_S12, OBJECTION_RECEIVED, OBJECTIONS_DISPOSED,
                          RR_SCHEME_DRAFTED_S16, RR_SCHEME_APPROVED_S17, RR_SCHEME_PUBLISHED_S18,
                          COST_DEPOSITED_S19_2, DECLARATION_S19, EXTENSION_GRANTED, NOTIFICATION_RESCINDED] }
  DECLARED:        { on: [NOTICE_S21, CLAIMS_RECEIVED, AWARD_S23, EXTENSION_GRANTED, CASE_LAPSED] }
  AWARDED:         { on: [RR_AWARD_S31, COMPENSATION_ASSESSED, PAYMENT_MADE, COMPENSATION_PAID_FULL,
                          POSSESSION_TAKEN_S38, URGENCY_S40_INVOKED, REFERENCE_FILED_S64] }
  POSSESSED:       { on: [RR_ENTITLEMENT_DELIVERED, LAND_UTILISED, LAND_RETURNED_S101, CASE_CLOSED] }
transitions:
  PRELIM_NOTIFICATION_S11: { from: APPRAISED, to: NOTIFIED }
  DECLARATION_S19:
    from: NOTIFIED
    to: DECLARED
    requires: [RR_SCHEME_PUBLISHED_S18, COST_DEPOSITED_S19_2]
  AWARD_S23:      { from: DECLARED, to: AWARDED }
  POSSESSION_TAKEN_S38:
    from: AWARDED
    to: POSSESSED
    guard: "comp_paid >= comp_assessed or (has(URGENCY_S40_INVOKED) and comp_paid >= 0.8*comp_assessed)"
  CASE_LAPSED:    { from: [NOTIFIED, DECLARED], to: LAPSED }
clocks:
  - id: S11_AFTER_APPRAISAL
    starts_on: EXPERT_GROUP_APPRAISAL
    ends_on: PRELIM_NOTIFICATION_S11
    duration: { months: 12 }
    basis: "s.14"
    consequence: "SIA report lapses; fresh SIA required"
    on_breach: { mark: breached }        # s.14 requires a fresh SIA; no automatic case lapse
  - id: OBJECTION_WINDOW
    starts_on: PRELIM_NOTIFICATION_S11
    duration: { days: 60 }
    basis: "s.15(1)"
    kind: window
  - id: DECLARATION_S19
    starts_on: PRELIM_NOTIFICATION_S11
    ends_on: DECLARATION_S19
    duration: { months: 12 }
    basis: "s.19(7)"
    consequence: "Preliminary notification deemed rescinded"
    extendable: { by: appropriate_government, reasons_required: true }
    on_breach: { emit: NOTIFICATION_RESCINDED, then: CASE_LAPSED }
  - id: AWARD_S23
    starts_on: DECLARATION_S19
    ends_on: AWARD_S23
    duration: { months: 12 }
    basis: "s.25"
    consequence: "Entire proceedings lapse"
    extendable: { by: appropriate_government, reasons_required: true }
    suspend_on: [COURT_STAY]
    resume_on: [STAY_VACATED]
    on_breach: { emit: CASE_LAPSED }
  - id: COMPENSATION_3M
    starts_on: AWARD_S23
    ends_on: COMPENSATION_PAID_FULL
    duration: { months: 3 }
    basis: "s.38(1)"
    consequence: "Possession cannot be taken; interest accrues"
  - id: RR_MONETARY_6M
    starts_on: AWARD_S23
    duration: { months: 6 }
    basis: "s.38(1)"
  - id: RR_INFRA_18M
    starts_on: AWARD_S23
    duration: { months: 18 }
    basis: "s.38(1) proviso"
  - id: UTILISATION_5Y
    starts_on: POSSESSION_TAKEN_S38
    ends_on: LAND_UTILISED
    duration: { years: 5 }
    basis: "s.101"
    consequence: "Return to original owner(s) or State Land Bank"
alerts:
  thresholds: { amber: 0.75, red: 0.90 }
  escalation: { amber: LAO, red: COLLECTOR, breached: STATE_REVENUE, lapsed: MINISTRY }
```

Overlay example `rulesets/overlays/<state>_2026.yaml` — same schema, keys override or add; loader merges base + overlay and pins `ruleset_version` on the case.

### Clock evaluation algorithm

```
for each running/extended/suspended clock c of case:
    start   = occurred_at(start event)
    due     = add_months/days(start, duration) + suspended_days + extension delta
    if terminating event exists (occurred_at <= today): c.status = closed
    elif suspended (COURT_STAY without STAY_VACATED): c.status = suspended
    elif today > due: c.status = breached; apply on_breach (emit consequence events as system actor)
    else: elapsed = (today - start) / (due - start); raise amber/red alerts per thresholds
```
Calendar-month arithmetic: same day of target month; if it doesn't exist, last day of that month (General Clauses Act 1897 s.3(35)). All dates IST. `today` is overridable via `X-Demo-Date` header in demo mode only (off in production).

## 6. Documents-as-events pipeline

1. `POST /documents` → store in MinIO under `sha256`; dedupe on hash.
2. Worker: text layer via `pdfplumber`; if scanned → OCR (Tesseract, Hindi+English) — mark `ocr=true`.
3. Extraction, two paths:
   - **Regex templates** for gazette formats (NH 3A/3D, s.11/s.19 notifications follow fixed phrasing: "…hereby declares…", "Schedule", village/tehsil/district tables, survey numbers, areas in hectares).
   - **LLM extraction** to a strict JSON schema with per-field `confidence` and `source_span` (page, char offsets). Prompt: system role = "extract fields for the schema; return null when absent; never infer." Provider-agnostic client; no PII sent beyond the document itself; India-hosted endpoint preferred *(verify provider region)*.
4. Result stored as `documents.extraction` with `status=proposed`; the proposed event is **not** in the ledger.
5. Officer confirms/corrects in the UI → `POST /cases/{id}/events` with `document_id` and confirmed payload → ledger commit; the event payload records `confirmed_fields` and `corrected_fields`.

Extraction schema (notification):
```json
{ "statute": "NH_ACT_1956", "section": "3D", "gazette_no": "...", "publication_date": "2025-11-14",
  "state": "...", "district": "...", "villages": [ { "name": "...", "tehsil": "...",
  "survey_nos": ["123/1","124"], "area_ha": 3.412 } ], "total_area_ha": 12.9,
  "competent_authority": "...", "confidence": { "publication_date": 0.98, "villages[0].area_ha": 0.71 },
  "source_spans": { "publication_date": { "page": 1, "start": 233, "end": 243 } } }
```

## 7. Compensation service

Inputs per parcel/owner: `market_value` (s.26 method and evidence), `factor` (First Schedule, from `land_type` + notified distance band), `assets_value` (s.29), `s11_date`, `award_date`/`possession_date`. Output lines: `T = MV*F + A`, `solatium = T`, `interest = MV * 0.12 * years(s11_date → min(award, possession))`, `total`. Stored as `COMPENSATION_ASSESSED` payload; payments reduce `outstanding` via `PAYMENT_MADE`. Interest continues to accrue on unpaid amounts per s.80 *(verify rates: 9% first year, 15% thereafter)* — computed in the projection, shown as liability.

## 8. Projections

- `case_state` updated synchronously on append (small); rebuildable by replay (`bhuarjan rebuild --case <id>` / `--all`).
- Dashboard aggregates: materialized views `mv_kpi_district`, `mv_kpi_state`, `mv_kpi_national` refreshed on a schedule (5 min in demo) with `as_of_seq`.
- Every aggregate row stores `as_of_seq`; `GET /dashboards/.../explain` returns the contributing event ids.

## 9. Alerts and notifications

Worker evaluates clocks every hour (demo: on every append and on `X-Demo-Date` change). Alert dedupe per `(case, clock, level)`. Escalation resolves roles → users by jurisdiction. Notification gateway interface: `send(channel, recipient, template, vars)` with `console`, `smtp`, `sms_mock` implementations; DLT-registered SMS provider later.

## 10. Security

- OIDC/JWT (Keycloak-compatible); roles + org_unit scope in claims; every repository query filtered by jurisdiction server-side.
- PII: AES-256-GCM at application layer with a KMS-backed key (env key in demo); decrypt only for permitted roles with `purpose` param; each decrypt writes `admin_audit(PII_READ)`.
- Rate limiting on public endpoints; CSRF not applicable (token auth); strict CORS.
- Secrets via environment; no secrets in repo; `.env.example` only.
- Logs are structured JSON without PII.

## 11. Deployment

`infra/docker-compose.yml`: `postgres` (postgis/postgis:16-3.4), `minio`, `redis`, `api`, `worker`, `web`, `nginx`. Single `make demo` target: migrate → load rule-sets → seed real project → start. Offline-capable: extraction falls back to regex when no LLM endpoint is configured. MeghRaj: same containers on NIC cloud; PostgreSQL managed or self-hosted.

## 12. Testing

- **Statutory fixtures**: YAML scenarios → expected clock states. Examples: `s19_on_day_366_no_extension → NOTIFICATION_RESCINDED`; `s19_on_day_366_with_extension → DECLARED`; `award_day_400_with_stay_60_days → running`; `possession_before_full_payment → rejected`; `possession_urgency_80pct → allowed`.
- Hash-chain tests: mutation detection, replay determinism.
- Extraction tests on 20 real gazette PDFs with golden JSON.
- API contract tests from the OpenAPI spec (schemathesis).
- Load: 10k cases synthetic for dashboard latency.

## 13. Seeding real data

`seed/gazette_scraper.py`: pull NH 3A/3D notifications for one project from egazette.gov.in (respect robots/rate limits; store PDFs with source URLs); extract; write events with `actor=system:seed` and `payload.source_url`. `seed/bhoomirashi_public.py`: project metadata from public project search pages. Families: synthetic, flagged `synthetic=true`, no real names.
