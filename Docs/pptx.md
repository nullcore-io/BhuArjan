# pptx.md — The idea deck (official 6-slide template) and the finale deck

Rules of the template: six slides including the title, official file only, section pointers unchanged, points not paragraphs, export to PDF. Download the 2026 template from the portal and confirm the section names below have not changed.

Design rule for every slide: one screenshot or one diagram, six to eight bullets maximum, nothing the team cannot defend line by line. No stock icons, no gradients, no "AI-powered" more than once in the whole deck, no blockchain.

Replace `[TEAM NAME]`, `[TEAM ID]`, `[VIDEO LINK]`, `[REPO LINK]` before export.

---

## Slide 1 — Title page

- Problem Statement ID — **SIH26016**
- Problem Statement Title — Real-Time National Land Acquisition & Management System for End-to-End Digital Monitoring and Decision Support
- Theme — as shown on the portal for SIH26016 (aggregators disagree: Miscellaneous / Smart Automation — copy the portal)
- PS Category — Software
- Team ID — `[TEAM ID]`
- Team Name — `[TEAM NAME]`

Idea title line (bottom of slide): **BhuArjan — National Land Acquisition Stack**

---

## Slide 2 — Proposed Solution

**Idea title:** BhuArjan — a national system of record for land acquisition: every stage, every statutory clock, every rupee, every affected family.

**Detailed explanation**
- Digitizes the full lifecycle — proposal → SIA → s.11 notification → objections → s.19 declaration → award → compensation → possession → R&R → closure — under RFCTLARR 2013 and the Fourth Schedule acts (NH, Railways, Metro…) as configurable rule-sets.
- Documents are the events: officers upload the gazette notification, award or payment record; the system extracts the fields, the officer confirms, the ledger commits.
- National → state → district → project dashboards computed from the ledger, so every figure is traceable to a document.

**How it addresses the problem**
- Statutory clocks as first-class objects with alerts and consequences (s.19(7) rescission, s.25 lapse, s.38 possession gate, 12% interest under s.30(3)).
- Single national view replacing quarterly paper returns; parcel-level GIS keyed to ULPIN.

**Innovation and uniqueness**
- Statute-encoded workflow, not a generic tracker — legally correct deadline alerts.
- Event-sourced, hash-chained ledger: audit trail, version history and dashboards from one log.
- Beyond Bhoomi Rashi: all statutes, all requiring bodies, plus R&R and family-level tracking it does not have. Seeded with real e-Gazette notifications.

**Visual:** screenshot of the case page — timeline with clocks (one amber), ledger, document panel.

---

## Slide 3 — Technical Approach

**Technologies** (mirrors the PS's own suggested stack)
- PostgreSQL + PostGIS · GeoServer / Leaflet · REST APIs (OpenAPI 3.1) · FastAPI (Python) · React + TypeScript · MinIO (S3-compatible documents) · LLM-based field extraction with regex fallback for gazette formats · Docker, MeghRaj-deployable · Keycloak-compatible JWT/RBAC.

**Methodology**
- Rule-sets as data (YAML): stages, transitions, clocks, extensions, suspensions, consequences — versioned per statute and state.
- Event ledger → projections → dashboards; nightly clock evaluation and alert escalation.
- Integration adapters behind stable interfaces: ULPIN/Bhulekh, PFMS, e-Gazette, DigiLocker/e-Sign, PM Gati Shakti (GeoJSON/WMS export).

**Visual:** one flow diagram — the lifecycle across the top (SIA → s.11 → objections → s.19 → award → compensation → possession → R&R → closure) with integration points labelled beneath. QR code → `[VIDEO LINK]` (90-second prototype video) and `[REPO LINK]`.

---

## Slide 4 — Feasibility and Viability

**Feasibility**
- Rules are public (the Act and 2014 Rules); data is public (e-Gazette notifications, Bhoomi Rashi project pages); stack is open source and NIC-hostable.
- Working prototype: one real NH project walked from 3A notification to award with clocks and audit trail (see video).

**Challenges and risks → strategies**
- State process variation → rule-set overlays per state, versioned, effective-dated; shown as a config diff.
- Officer data-entry burden → document-first ingestion: upload + confirm, not typing.
- Government APIs not yet available → adapter layer with mock connectors behind real interfaces; standards-based (REST, GeoJSON, ULPIN).
- DPDP Act 2023 → field-level encryption of family PII, jurisdiction-scoped access, audited PII reads, public page without identifiers.
- Adoption → Bhoomi Rashi precedent: made mandatory for all NH projects from 1 April 2018.

**Visual:** small risk → mitigation table (the bullets above, two columns).

---

## Slide 5 — Impact and Benefits

**Target audience:** DoLR and sectoral ministries · state revenue departments · District Collectors and LAOs · requiring bodies · affected families.

**Benefits**
- **Time:** digitizing NH acquisition raised notifications from ~1,000/year to 2,842 in the first year; BhuArjan extends that to every statute and sector.
- **Money:** every month of delayed compensation accrues 12% interest; a missed s.25 deadline means re-acquisition from zero. Clocks with escalation stop both.
- **Transparency:** family-level R&R entitlements visible to the Commissioner and the Ministry; public parcel status for citizens.
- **Governance:** national real-time view replacing quarterly paper returns; every dashboard figure traceable to an event and a document.
- **Social:** families see entitlements tracked to delivery; SC/ST and Scheduled Area provisions (ss.41–42) modelled explicitly.

**Visual:** national dashboard screenshot (area notified vs acquired, compensation assessed vs paid, families, timeline adherence).

---

## Slide 6 — Research and References

- Right to Fair Compensation and Transparency in Land Acquisition, Rehabilitation and Resettlement Act, 2013, and the RFCTLARR Rules, 2014 (India Code)
- National Highways Act, 1956, ss.3A–3J
- Bhoomi Rashi portal (MoRTH) — PIB releases on adoption and throughput
- Department of Land Resources — DILRMP, ULPIN (Bhu-Aadhaar) documentation
- MoSPI, Infrastructure and Project Monitoring Division — project monitoring reports (land acquisition as a delay cause)
- e-Gazette of India (egazette.gov.in) — source of seeded notifications
- Digital Personal Data Protection Act, 2023 · MeitY e-Governance standards · MeghRaj (NIC Cloud) · GIGW 3.0
- Prototype: `[REPO LINK]` · Demo video: `[VIDEO LINK]`

---

## Export checklist
1. Template downloaded from the portal, section pointers untouched.
2. Team name in the footer of every slide as the template expects.
3. Six slides exactly; the "Important Pointers" instruction slide deleted.
4. Every screenshot is of the running prototype, not a mock-up.
5. Fonts embedded / text not clipped; export PDF; open the PDF on a phone — screeners do.
6. File name per SPOC instruction.

---

## Internal-round variant
Same six slides. Add nothing. Bring the 90-second video and, if allowed, a 2-minute live walk-through of the case page. The internal panel is generalist: lead with the Bhoomi Rashi table and the clock alert firing.

---

## Finale deck (your own format; ~10–12 slides, 5–7 minutes plus demo)
1. Title and the one line
2. The problem in DoLR's terms (three numbers)
3. Bhoomi Rashi vs BhuArjan (the table)
4. **Live demo** (see Transcript.md) — 3 to 4 minutes; slides pause here
5. How the ledger works (documents → events → projections; hash chain)
6. Rules as data (YAML excerpt; a state overlay diff)
7. Security and DPDP (RBAC, jurisdiction, PII encryption, audited reads)
8. Integration layer (adapters; which are mocked and why)
9. What we validated (real seeded project; clock tests against statutory fixtures)
10. Roadmap (F/I/J modules, ML risk model once history exists — link to 26017)
11. Team and roles
12. Leave-behind: one-page summary and the technical document

Judges rotate: the presenter restates the one line and the Bhoomi Rashi distinction for every new panel, even if it feels repetitive.
