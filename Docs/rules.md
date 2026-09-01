# rules.md — Competition rules, statutory rule-set, product rules

Three rulebooks in one file. Part A governs the team; Part B is what the software encodes; Part C is how the software behaves.
*(verify)* = confirm before relying on it. None of this is legal advice; the domain owner must read the bare Act and Rules.

---

## Part A — SIH 2026 rules and constraints

### A1. Team and eligibility
- Six members, all enrolled students of the same institute; at least one woman. *(verify current rulebook)*
- Entry only through the institute's SPOC after an internal hackathon; the SPOC nominates and submits on the portal.
- Non-students (e.g. an industry mentor) can mentor, not be members.
- AI tools are allowed in development; the team must be able to explain, modify and defend every part. Lifted repos are a disqualification risk.

### A2. Idea submission (the PDF)
- Maximum six slides **including the title slide**.
- Only the official template; do not change the section pointers; points/diagrams, not paragraphs.
- Save as **PDF** and upload; PPT/DOCX are rejected.
- Sections (2025 template; confirm 2026 file from the portal): Title · Proposed Solution · Technical Approach · Feasibility & Viability · Impact & Benefits · Research & References.
- Deadline: PS pages scraped from the portal show **20 September 2026**; general guides quote 30 September. Treat 20 September as the date until the SPOC says otherwise.
- Each PS page shows a "submitted ideas 0/500" counter — likely a per-statement cap. *(verify)* If real, popular statements close.

### A3. Judging (typical published criteria; *verify* the 2026 rubric)
Novelty · technical complexity and feasibility · clarity of the idea · completeness of prototype · user experience · potential impact · presentation. Screeners at the portal stage are generalists reading hundreds of PDFs; finale judges include the PS owner (DoLR) and technical evaluators.

### A4. Finale
- December 2026, 36 hours, nodal centre; multiple mentoring/evaluation rounds with rotating judges; final pitch with live demo.
- Prize for software statements listed as ₹1,00,000 in aggregator catalogues. *(verify)*
- Bring: laptop-only demo (no network dependency), recorded backup, one-page leave-behind, short technical document.

### A5. Data and IP
- Check the PS page for a dataset link; if DoLR provides one, use it and say so.
- Public data used: e-Gazette notifications, Bhoomi Rashi public project pages, MoSPI project-monitoring reports. Label anything synthetic.
- No real PII of landowners or families in the demo dataset. Use synthetic names on real geography if needed, and say so.

---

## Part B — The statutory rule-set the system encodes

### B1. RFCTLARR Act 2013 — primary track

| Stage / clock | Section | Clock | Consequence of breach | Extendable? |
|---|---|---|---|---|
| SIA notification | s.4(1) | SIA to be completed within 6 months of notification | Procedural default | — |
| Public hearing | s.5 | Part of SIA | — | — |
| SIA report publication | s.6 | — | — | — |
| Expert Group appraisal | s.7 | Recommendations within 2 months of constitution *(verify 7(4))* | — | — |
| Government decision on SIA | s.8 | — | — | — |
| Preliminary notification | s.11 | Must issue within **12 months of Expert Group appraisal** | SIA report lapses; fresh SIA (s.14) | — |
| Preliminary survey | s.12 | — | — | — |
| Objections window | s.15 | **60 days** from publication of s.11 notification (public window) | — | — |
| R&R scheme: preparation → Collector review → Commissioner approval → publication | ss.16–18 | Before s.19 | s.19 cannot issue without R&R scheme summary | — |
| Cost deposit by requiring body | s.19(2) | Before declaration | Declaration cannot be made | — |
| Declaration + summary of R&R scheme | s.19 | Within **12 months of s.11 notification** | s.11 notification **deemed rescinded** (s.19(7)) | Yes — appropriate Government, reasons in writing (proviso) |
| Marking, measuring, planning | s.20 | — | — | — |
| Notice to persons interested | s.21 | Claims window ≥30 days and ≤6 months | — | — |
| Award | s.23 | Within **12 months of s.19 declaration** | **Entire proceedings lapse** (s.25) | Yes — appropriate Government, reasons in writing (proviso) |
| Compensation determination | ss.26–30 | See B4 | — | — |
| R&R award | s.31 | With/after award | — | — |
| Possession | s.38 | Only after compensation paid/tendered within **3 months** of award; monetary R&R within **6 months**; infrastructural R&R within **18 months** (proviso) | Possession blocked | — |
| Reference to LARR Authority | s.64 | 6 weeks from award if present at award; otherwise 6 weeks from notice / 6 months from award *(verify)* | Litigation flag; clocks may be suspended by court order | — |
| Utilisation | s.101 | Land unused for **5 years** from possession | Return to owner(s) or State Land Bank | — |
| Legacy (1894 Act) cases | s.24(2) | Award ≥5 years before commencement and no possession/compensation | Deemed lapsed | — |
| Urgency | s.40 | Compresses s.11→possession; still requires 80% compensation before possession *(verify 40(3))* | — | — |
| Scheduled Areas | s.41 | Gram Sabha consent; special provisions | — | — |

### B2. NH Act 1956 track (Fourth Schedule; compensation and R&R per RFCTLARR apply via s.105 and the 2015 order)

| Stage | Section | Clock | Consequence |
|---|---|---|---|
| Notification of intention | 3A | — | Starts clocks |
| Objections | 3C | **21 days** from 3A publication | Public window |
| Declaration | 3D | Within **1 year of 3A** | 3A ceases to have effect (3D(3)); land vests in Central Government on 3D (3D(2)) |
| Possession | 3E | After 3D | — |
| Determination of amount | 3G | Competent authority; arbitrator if no agreement (3G(5)) | — |
| Deposit and payment | 3H | Interest on delayed payment (3H(5)) *(verify rate)* | — |

### B3. Other Fourth Schedule tracks (stubs; encode as config, demonstrate as extensible)
Railways Act 1989 Ch. IVA (ss.20A–20F: notification, objections 30 days, declaration within 1 year), Metro Railways (Construction of Works) Act 1978, Coal Bearing Areas (Acquisition and Development) Act 1957, Land Acquisition (Mines) Act 1885, Petroleum and Minerals Pipelines Act 1962, Electricity Act 2003, and others listed in the Fourth Schedule. *(verify list and clocks per statute)*

### B4. Compensation computation (First Schedule + ss.26–30)

```
MV   = market value per s.26(1): highest of
       (a) circle/guideline value, (b) average of top 50% of sale-deed prices
       in the vicinity over the preceding 3 years, (c) consented amount if any
F    = First Schedule factor: rural 1.00–2.00 by distance from urban area
       (as notified by the appropriate Government); urban 1.00
A    = value of assets attached to land (s.29): structures, trees, wells, crops
T    = MV × F + A
S    = solatium = 100% × T                              (s.30(1))
I    = 12% p.a. on MV from date of s.11 notification to
       date of award or possession, whichever earlier   (s.30(3))
Total compensation = T + S + I
```
R&R entitlements are separate (Second Schedule heads: subsistence allowance, transportation, resettlement allowance, house, employment/one-time payment/annuity, land-for-land where applicable, artisan/petty-shop grants, cattle-shed grant, stamp duty; Third Schedule: infrastructural amenities at resettlement site). Amounts are as per the Schedules and any indexation *(verify current values)*.

### B5. State variations (encode as rule-set overlays, not code)
Several states have amended or exempted categories (e.g. Gujarat, Tamil Nadu, Telangana, Maharashtra) — SIA exemptions, consent thresholds, timelines. Model each as an overlay on the base track with a version and effective date. Demonstrate one overlay as a config diff on stage.

---

## Part C — Product rules (business rules the software enforces)

### C1. Ledger
- Events are immutable and append-only. Corrections are compensating events (`EVENT_REVERSED` referencing the original), never edits.
- Every statutory event requires a document (or an explicit `no_document_reason` recorded by a Collector-level role).
- Each event stores `prev_hash` and `hash` (SHA-256 over canonical JSON of the event and `prev_hash`) per case → tamper-evident chain; a nightly job re-verifies chains and raises an alert on mismatch.
- Event `occurred_at` (legal date, e.g. gazette publication date) is distinct from `recorded_at` (system time). Clocks run on `occurred_at`.

### C2. Clocks
- Durations in months are calendar months (General Clauses Act 1897, s.3(35) — British calendar month). Day-N-of-month rule: due date is the same day of the target month; if it does not exist, the last day of that month. Days are calendar days unless the statute says otherwise. Time zone IST.
- Clock states: `running`, `closed` (terminating event occurred), `extended` (extension event with authority + reasons + new due date), `suspended` (court stay or statutory suspension event; resumes on vacate), `breached` (due date passed with no terminating or extension event), `lapsed` (breach whose statutory consequence is lapse/rescission — case moves to `LAPSED`).
- Alert thresholds: amber at 75% elapsed, red at 90%, black on breach. Escalation ladder: LAO → Collector (red) → State (breach) → Ministry (lapse). Configurable per rule-set.
- A clock's `basis` (section) and `consequence` text are shown wherever the clock is shown.

### C3. Stage transitions
- Allowed transitions come from the rule-set, not code. An event that is not a permitted transition from the current stage is rejected with the rule-set reference.
- Preconditions are enforced: no `DECLARATION_S19` without `RR_SCHEME_PUBLISHED_S18` and `COST_DEPOSITED_S19_2`; no `POSSESSION_TAKEN_S38` while `compensation_paid < compensation_assessed` for the case unless an `URGENCY_S40` event exists with ≥80% paid *(verify)*.

### C4. Documents
- Stored once (content-addressed by SHA-256); new versions supersede, never overwrite.
- Extraction output is a proposal with per-field confidence; nothing enters the ledger until a human confirms. Confirmed values and the confirming user are recorded on the event.

### C5. Data protection (DPDP Act 2023)
- Affected-family PII (names, ID numbers, bank details) is encrypted at the field level; decrypted only for roles with jurisdiction and purpose; every PII read is audited.
- Public status page exposes stage, dates, area and amounts at aggregate — never names or identifiers.
- Consent and purpose flags are stored with each family record; retention follows the acquisition lifecycle plus statutory retention *(verify)*.

### C6. Roles
- Jurisdiction is enforced server-side on every query (state/district/project scope).
- Segregation: the officer who records an award cannot be the one who confirms possession for the same case if a Collector-level approval is required by the rule-set.

### C7. Reporting integrity
- Every dashboard figure carries an "as of" event sequence number and can be exploded to the events that produced it.
- Exports (CSV/PDF/GeoJSON) embed the as-of sequence and a report hash.
