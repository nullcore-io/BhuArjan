# Demo runbook — the 90-second walk (final-product.md §6)

Stack is already running (`bhuarjan` group in Docker Desktop). If not: `make demo`.
Reset to pristine at any time: `make destroy && make demo` (≈2 min, re-seeds).

**Web** http://localhost:3016 · **API docs** http://localhost:8016/api/v1/docs
**All logins** password `demo123`: `lao@demo`, `collector@demo`, `state@demo`,
`ministry@demo`, `auditor@demo`, `rb@demo`.

## The walk

1. **Sign in as LAO** (quick sign-in card). Projects → *NH-44 Lakhnadon–Seoni
   4-laning (Pkg II)* → case **LAQ/SEO/2025/01**.
   *Point at:* the DECLARATION 3D clock — **red, 93% elapsed, 26 days left**, basis
   3D(3), consequence verbatim: "3A notification ceases to have effect". Chain
   verified badge. Parcel polygons on the map (18.64 ha, 3 villages).

2. **Record event** → *Declaration 3D* (note: the list is the rule-set — only
   transitions legal from NOTIFIED appear, each with its section) → upload
   `api/seed/demo_uploads/gazette_3D_LAQ-SEO-2025-01.pdf` → **Upload and extract**.
   *Point at:* SHA-256 shown; extraction proposes DECLARATION_3D with 12 fields.

3. **Review** — fields with confidence chips beside the PDF; publication date
   28-08-2026 became the legal `occurred_at`. → **Confirm** → **Commit**.
   *Point at:* seq + hash on the committed screen; **3D clock closed at day ~335;
   AWARD 3G clock started, due 28-08-2027**. Stage NOTIFIED → DECLARED.

4. **Back to case** — ledger now has the 3D event with document and hash; the
   public consequence: open a new tab → **Public** → Survey no. → village
   `Adegaon`, survey `112/1` → stage DECLARED, next milestone AWARD 3G with due
   month, no names anywhere. Bilingual.

5. **Sign in as ministry@demo** → National dashboard.
   *Point at:* KPI tiles in the PS's exact wording, every tile "as of seq N" with
   **Explain** (opens the contributing events); assessed vs paid ₹45.06 Cr (the
   completed case LAQ/SEO/2024/07); stage funnel; clock health. **Alerts** — the
   escalation ladder (amber→LAO, red→Collector), the RFCTLARR case at amber.

6. If asked "what if the officer is late?": open case **LAQ/BLG/2025/03**
   (s.19 clock amber, 49 days left) and set the **demo date** in the header to
   `2026-11-01` — the clock breaches, the engine emits NOTIFICATION_RESCINDED +
   CASE_LAPSED as the *system* actor, in the ledger, hash-chained. (Reset the demo
   date after, or `make destroy && make demo` before the next run.)

## One-liners that are true of the running system

- "Nobody typed that declaration — the document is the event."
- "Every figure traces to a sequence number; Explain shows the events behind it."
- "The clocks are sections of the Act, loaded from YAML — a state amendment is a
  config diff, not a release." (show `/api/v1/admin/rulesets` if pressed)
- "Court stays suspend the statutory clocks — a stayed case cannot auto-lapse."
- "Possession is blocked until compensation is paid in full — s.38(1); with an
  urgency invocation, 80%." (the gate refuses ₹0-assessed cases too)
- "Tamper with a row in SQL and the integrity check fails; a nightly job
  re-verifies every chain." (Integrity tab on the case)

## Do not say (Key-Points.md)

"AI-powered" more than once · "blockchain" · "predicts delays" · "fully
integrated" (adapters are mocks and the admin screen says so honestly).

## If something breaks

- Blank map: OSM tiles need network; the parcel table under the map is the fallback.
- Wrong demo state (someone already committed the 3D): `make destroy && make demo`.
- API down: `docker compose -f infra/docker-compose.yml logs api --tail 50`.
