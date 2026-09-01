# Key-Points.md — The page to re-read before every round

## Decisions made
- Problem statement: **SIH26016**, MoRD / Department of Land Resources, Software.
- Product: **BhuArjan** (placeholder name) — national land acquisition system of record; statute-encoded; event-sourced.
- Not chosen: 26047 (needs voice builder + vaidya), 26012 (needs GIS person + drone tile), 26001 (crowded, no data, institutional owners), 26027 (needs OR person + railway insider), 26017 (needs history the team lacks).
- Flip condition still open: a voice/LLM builder **and** a committed vaidya would make 26047 the better bet.

## The three differentiators (say them in this order, every time)
1. **Statute-encoded workflow** — clocks are sections: s.19(7) rescission, s.25 lapse, s.38 possession gate, s.30(3) 12% interest, s.101 five-year utilisation.
2. **Documents are the events** — upload, extract, confirm, commit; officers don't type; every figure traces to a document.
3. **Beyond Bhoomi Rashi** — all statutes and requiring bodies, plus R&R at family level and a hash-chained ledger.

## The Bhoomi Rashi line
"Bhoomi Rashi proved the category — NH notifications went from ~1,000 a year to 2,842 in year one after digitization. It is NH-only. DoLR has no equivalent for everything else. This is that equivalent."

## Traps that lose this PS
- Building the generic admin template everyone else builds (React dashboard, six roles, fake projects, three polygons).
- "AI-powered" as decoration; a fake delay-prediction model on synthetic data.
- Not knowing Bhoomi Rashi exists.
- Quoting a section wrongly on stage. Domain owner verifies against the bare Act; say "verify" rather than guess.
- Blockchain. Don't.
- Demo that needs the network.

## Dates (verify with SPOC on day one)
- Portal PS pages: idea deadline **20 September 2026**; general guides say 30 September. Plan for the 20th.
- Per-PS counter "0/500" — probably a submission cap; popular statements may close.
- Internal hackathon: date from SPOC; must finish before nomination.
- Grand Finale: December 2026, 36 hours, nodal centre.
- Team: 6 students, same institute, ≥1 woman; SPOC nominates.

## Build order (first ten days)
1. SPOC → dates, template, cap. Check the PS page for a dataset link and the listed contact.
2. Read the Act + 2014 Rules; encode RFCTLARR and NH rule-sets in YAML with tests.
3. Ledger + hash chain + projections.
4. Case page with clocks, ledger, documents; extraction review flow.
5. Seed one real NH project from e-Gazette; national dashboard; parcel import + map.
6. 90-second video; six-slide PDF; internal round.

## Statute index (memorize)
| Section | Meaning |
|---|---|
| s.4–9 | SIA → appraisal → government decision |
| s.11 | Preliminary notification (starts the 12-month clock to s.19) |
| s.14 | s.11 must follow appraisal within 12 months or SIA lapses |
| s.15 | Objections within 60 days |
| s.16–18 | R&R scheme prepared, approved, published |
| s.19 | Declaration + R&R summary; within 12 months of s.11 or notification rescinded (19(7)); extendable with reasons |
| s.21 | Notice to persons interested |
| s.23 / s.25 | Award; within 12 months of declaration or proceedings lapse; extendable with reasons |
| s.26–30 | Market value; First Schedule factor; assets; 100% solatium; 12% interest from s.11 to award/possession |
| s.31 | R&R award |
| s.38 | Possession only after payment; 3 months compensation, 6 months monetary R&R, 18 months infrastructure R&R |
| s.40 | Urgency; 80% compensation before possession *(verify)* |
| s.41–42 | Scheduled Areas; SC/ST entitlements |
| s.64 | Reference to LARR Authority |
| s.101 | Unused land returned after 5 years |
| s.105 + Fourth Schedule | NH, Railways, Metro, Coal Bearing Areas etc.; compensation and R&R extended to them |
| NH Act 3A / 3C / 3D / 3E / 3G / 3H | Intention; objections 21 days; declaration within 1 year (vesting); possession; amount; deposit |

## Judge one-liners
- *Different from Bhoomi Rashi?* All statutes, all bodies, clocks, R&R, ledger; Bhoomi Rashi is our proof the category works.
- *Data source?* Real e-Gazette notifications and Bhoomi Rashi public pages; families synthetic and labelled.
- *Award slips past 12 months?* s.25 — proceedings lapse unless extended with reasons; system escalates before, shows consequence, moves to Lapsed after.
- *Who enters data?* Nobody types; they upload and confirm.
- *State amendments?* Rule-set overlays; show the diff.
- *What's the AI?* Field extraction with confidence and human confirmation; no fake predictions.
- *Tampering?* Append-only, hash-chained, nightly verification.
- *DPDP?* Field-level encryption, jurisdiction + purpose, audited reads, public page without identifiers.
- *MeghRaj?* Containers + PostgreSQL/PostGIS + S3 store. Yes.

## Say / don't say
- Say: "system of record", "statutory clock", "documents are the events", "traceable to a document", "rule-sets as data", "we verified against the Act".
- Don't say: "AI-powered" (more than once), "blockchain", "predicts delays", "real-time" for anything that depends on an officer uploading, "fully integrated" for a mocked adapter.

## Files in this pack
`final-product.md` (what and why) · `rules.md` (competition, statute, product rules) · `pptx.md` (six slides + finale deck) · `Transcript.md` (scripts, Q&A, decision record) · `Backend.md` · `Frontend.md` · `APIs.md` · this file.
