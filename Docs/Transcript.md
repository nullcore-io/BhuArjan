# Transcript.md — What we say

Interpretation: this file is the spoken script for the pitches, the demo narration, and the question bank. The decision record for why 26016 was chosen is in the appendix.

Conventions: `[SLIDE n]` = advance; `[DEMO]` = switch to the running system; `[PAUSE]` = stop talking and let the screen do the work. Numbers in the script must match the seeded project on the day; the domain owner re-checks every cited section against the bare Act before each round.

---

## 1. Sixty-second version (for a judge who has just sat down)

"BhuArjan is a national system of record for land acquisition. Today the only digital system is Bhoomi Rashi, and it covers National Highways alone — everything else runs on paper and state-specific processes. BhuArjan encodes the Land Acquisition Act itself: every stage, and every statutory clock — the twelve months from notification to declaration, the twelve months from declaration to award — as live objects with alerts and consequences. Officers don't type; they upload the gazette notification or the award, the system extracts the fields, they confirm, and the ledger commits an immutable, hash-chained event. Every figure on the national dashboard traces back to an event and a document. It is seeded with real gazette notifications from a real highway project, and it runs on this laptop with no network. Would you like to see the award clock fire?"

---

## 2. Three-minute internal-round pitch

`[SLIDE 1]`
"We're `[TEAM NAME]`, problem statement 26016 from the Department of Land Resources. Our idea is BhuArjan — a national land acquisition stack."

`[SLIDE 2]`
"Land acquisition in India has one digital system: Bhoomi Rashi, built by the highways ministry in 2018. It only handles National Highways. Railways, irrigation, industrial corridors, urban development — paper files, state by state. The centre cannot see, today, how much land is notified versus acquired, how much compensation is assessed versus paid, or where the resettlement of families stands.

BhuArjan digitizes the full lifecycle under the 2013 Act and the Fourth Schedule acts. Three things make it different. One: it encodes the statute. The Act says the declaration must follow the preliminary notification within twelve months or the notification is rescinded — section 19(7). The award must follow the declaration within twelve months or the whole proceeding lapses — section 25. Our clocks are those sections, with alerts. Two: documents are the events. The officer uploads the notification; we extract; they confirm; the ledger commits. Three: the ledger is append-only and hash-chained, so audit, version history and dashboards come from one log."

`[SLIDE 3]`
"Stack is the one the ministry suggested — PostgreSQL with PostGIS, Leaflet, REST — plus FastAPI, React, MinIO for documents and an extraction step with an LLM and a regex fallback, because gazette notifications have a fixed format. Rules are data: a YAML rule-set per statute, with state overlays. Integration adapters for ULPIN, PFMS, e-Gazette, DigiLocker and Gati Shakti sit behind stable interfaces; in the prototype the connectors are mocked and we say so."

`[SLIDE 4]`
"Feasible because the rules are public, the data is public — we seeded a real highway project from real gazette notifications — and the stack is what NIC already hosts. Risks: state variation, which we handle as configuration; officer workload, which document-first ingestion removes; missing APIs, which the adapter layer isolates; and the DPDP Act, which we address with field-level encryption and audited access to family data."

`[SLIDE 5]`
"Impact: when highways digitized, notifications went from about a thousand a year to 2,842 in the first year. Delayed compensation costs the exchequer twelve percent interest. A missed award deadline restarts acquisition from zero. And for the first time, resettlement entitlements would be tracked family by family."

`[SLIDE 6]`
"References are on the slide; the repository and a ninety-second video are linked. Happy to show the live system."

---

## 3. Finale pitch with demo (seven minutes)

`[SLIDE 1]` (0:00)
"BhuArjan — a national system of record for land acquisition: every stage, every statutory clock, every rupee, every affected family."

`[SLIDE 2]` (0:20)
"Three numbers. One: one national digital system exists for acquisition, and it covers one statute. Two: twelve months — the two deadlines in the Act that, when missed, rescind a notification or lapse a proceeding. Three: twelve percent — the interest the state pays on every rupee of delayed compensation. Nobody at the centre sees any of this in real time."

`[SLIDE 3]` (0:50)
"How is this different from Bhoomi Rashi? Bhoomi Rashi handles NH Act notifications and PFMS payments for highway projects, and it works — its own numbers show notification throughput nearly tripling. BhuArjan is that idea for every statute and every requiring body, with three things Bhoomi Rashi doesn't have: statutory clocks, family-level R&R tracking, and a tamper-evident ledger."

`[DEMO]` (1:20)
"This is a real highway project. These villages and survey numbers come from the actual 3A notification in the Gazette of India. `[PAUSE]`

The officer receives the 3D declaration. Instead of typing it, they upload the PDF. `[upload]` The extractor proposes the fields — date of publication, villages, area — with confidence per field. The officer corrects one value and confirms. `[confirm]` The event is committed: who, when, which document, its hash, and the hash of the previous event. `[PAUSE]`

Look at the clock panel. The 3A-to-3D clock has closed at day 340 of 365 — legal. The award clock has started. Let me move the system date forward. `[advance date]` At 75 percent it's amber. At 90 it's red and the alert has escalated from the officer to the Collector. And the consequence is written next to the clock: if neither an award nor an extension is recorded by this date, section 25 — the proceeding lapses. `[PAUSE]`

The Collector records the award. `[record award]` Compensation lines are computed per parcel under the First Schedule — market value, factor, assets, hundred percent solatium, interest from the notification date. PFMS payment references are posted. Assessed versus paid moves. And notice: possession is greyed out. Section 38 — no possession until payment is complete. `[PAUSE]`

Here is the ledger for this case — every event, every document, every hash. And here is the national dashboard: area notified versus acquired, compensation assessed versus paid, families affected, timeline adherence — this district just moved. Finally, the public page: a citizen enters a survey number and sees the stage and the dates. No names. Nothing personal."

`[SLIDE 5]` (5:00)
"Under the hood: documents become events, events become projections, projections become dashboards. Nothing is edited; corrections are compensating events."

`[SLIDE 6]` (5:25)
"Rules are data. This is the RFCTLARR rule-set — stages, transitions, clocks, consequences, extendability. This is a state overlay — a fifteen-line diff. That's how we absorb amendments without a release."

`[SLIDE 7]` (5:50)
"Security: jurisdiction enforced on every query; family PII encrypted at the field level, decrypted only for a role with jurisdiction and purpose, every read audited; public page without identifiers. Deployable on MeghRaj today."

`[SLIDE 9–10]` (6:15)
"What we validated: the clock engine passes a test suite written from the statute — declaration on day 366 without an extension event rescinds the notification. What's next: R&R module to entitlement level, adapters against the real APIs when access is granted, and a delay-risk model once the ministry's history exists — which is why we did not fake one."

`[SLIDE 12]` (6:45)
"The one-pager and a short technical document — schemas, APIs, role matrix — are with you. Questions."

---

## 4. Question bank

**"How is this different from Bhoomi Rashi?"** Bhoomi Rashi is NH Act only, highway projects only, notifications and payments. We cover every statute as a configurable rule-set, every requiring body, and add statutory clocks, family-level R&R, and a hash-chained ledger. We treat Bhoomi Rashi as proof that the category works.

**"Where does your data come from?"** Real e-Gazette notifications for a real NH project, and public Bhoomi Rashi project pages. Family records in the demo are synthetic on real geography, and labelled. If DoLR provides data, the schema is ready for it.

**"What happens if the award isn't made within twelve months of the declaration?"** Section 25: the entire proceeding lapses, unless the appropriate Government extends the period for reasons recorded in writing under the proviso. The system shows the consequence next to the clock, escalates before it happens, and moves the case to Lapsed if it does.

**"And if the declaration is late?"** Section 19(7): the preliminary notification is deemed rescinded, again subject to extension by the appropriate Government.

**"Who enters the data — Collectors won't type."** They don't. They upload the document that already exists — the notification, the award, the payment record — and confirm extracted fields. It's less work than the paper file.

**"How do you handle state amendments?"** Rule-set overlays: versioned, effective-dated configuration, not code. We can show one as a diff.

**"Bhulekh differs in every state. How do you integrate?"** Through an adapter per state behind one ULPIN-keyed interface. ULPIN is DoLR's own standard; we key parcels to it from day one.

**"What is the AI here?"** Field extraction from statutory documents with confidence scores and human confirmation. We deliberately did not build a delay-prediction model on synthetic data; that needs the ministry's history — and that's problem statement 26017.

**"How do you prevent someone editing a record?"** Nobody can. Events are append-only and hash-chained; a nightly job re-verifies chains. Corrections are new events that reference the original.

**"Litigation stays — what happens to clocks?"** A suspension event with the court order as the document; the clock pauses and resumes on the vacate event. Both are visible in the ledger.

**"How do you handle possession under urgency?"** Section 40 track: possession allowed after 80 percent of compensation is tendered *(verify)*; the rule-set relaxes the section 38 gate only when an urgency event exists.

**"DPDP — you're storing family data."** Field-level encryption; role and jurisdiction scoped decryption; every read audited; purpose and consent flags per record; public surface has no identifiers.

**"Can this run on MeghRaj?"** Containers plus PostgreSQL/PostGIS and an S3-compatible store. Nothing exotic.

**"Scale to all states?"** Partition by state, read replicas for dashboards, projections precomputed; the ledger is append-only so writes are cheap.

**"Why not blockchain for the audit trail?"** A hash-chained ledger in PostgreSQL gives the tamper evidence at a fraction of the cost and complexity, and NIC can host it.

**"How do you measure R&R progress?"** Entitlement heads from the Second and Third Schedules tracked per family to delivery, with the section 38 timelines as clocks.

**"What if the extraction is wrong?"** Nothing enters the ledger without a human confirming each field; the confirming officer is recorded on the event.

**"What did you actually validate?"** A clock test suite written from the statute, and one real project seeded end to end.

**"What's the adoption path?"** The Bhoomi Rashi precedent: mandate for one class of projects, then extend. Requiring bodies want the visibility; states want the alerts before the lapse.

**"Team — who knows the Act?"** `[Domain owner]` answers the next statute question live.

---

## 5. Delivery notes
- Demo first, slides second, whenever the format allows. Judges remember the amber clock turning red, not the architecture slide.
- One presenter, one demo driver, one statute answerer. Nobody else speaks unless asked.
- Restate the one line and the Bhoomi Rashi distinction for every new panel.
- Say "verify" out loud rather than guess a section number wrongly; then verify.
- Never say "AI-powered" twice. Never say blockchain.
- If the network dies, nothing changes: the demo is local. If the laptop dies, the backup video is on a phone.

---

## Appendix — Decision record (why 26016)

Six statements were assessed against one team profile (no GIS pipeline experience, no drone data, no confirmed specialist or domain recruit):

- **SIH26047** (Ayush case-taking kiosk): strongest demo, but needs a voice/LLM builder and a committed vaidya; fragile in a noisy hall. First choice if both exist.
- **SIH26012** (cadastral parcel extraction): legal boundaries aren't visible boundaries; no Indian drone ORI with parcel labels; needs a GIS person and a tile. Dead for this team.
- **SIH26001** (NER landslide EWS): first statement on the list, most reproduced archetype, science owned by GSI/NRSC/NESAC, no open real-time data. Skip.
- **SIH26027** (railway block planning): no public data ever; a constraint-scheduling problem judged by operating officers; needs an OR person and, realistically, a railway insider.
- **SIH26017** (LA delay prediction): 26016's analytics half; lives or dies on historical data the team doesn't have; leakage and censoring traps.
- **SIH26016** (LA management system): no external dependency the team can't control; differentiator is reading a public statute and engineering it properly; demo fully controlled; field crowded with teams who think it's easy — the only way to lose is to build what they build.
