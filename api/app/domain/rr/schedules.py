"""Second and Third Schedule entitlement heads — as data (Docs/rules.md B4, B1 s.38).

What this module deliberately does **not** hold is money. The Second Schedule amounts
are fixed by the appropriate Government and revised by notification and indexation; a
rupee table hard-coded here would be wrong within a year and wrong on stage. Docs/rules.md
B4 says so in as many words: *"Amounts are as per the Schedules and any indexation
(verify current values)"*. So every head carries its statutory basis and an `amount`
field that says, in words, that the figure must be read from the current notification.

What the system tracks instead is the thing nobody tracks today: **delivery status per
head per family**. `final-product.md` §3 is explicit that R&R is "not tracked" in
Bhoomi Rashi and §2 that "R&R — the part of the Act that touches families — has no
family-level tracking anywhere".

`applies_to` is advisory metadata for the screen, not a gate: a head marked `displaced`
is one the Schedule ties to displacement, `irrigation` one the Schedule confines to
irrigation projects. Every head still starts `due` on every family, because deciding
that a head does *not* apply to a particular family is an officer's determination
recorded against that family — never an inference this module makes on their behalf.

The Third Schedule (infrastructural amenities at the resettlement site — roads, water,
drainage, school, health centre, panchayat ghar, and the rest) is carried as a single
`resettlement_infrastructure` head: it is delivered to a *site*, not to a family, and
the s.38(1) proviso gives it its own 18-month clock (`RR_INFRA_18M`).
"""

from __future__ import annotations

AMOUNT_NOTE = (
    "as per the Schedule and any indexation notified by the appropriate Government "
    "(verify current indexation)"
)

# Kinds: monetary (a sum), land (an allotment in kind — a house or a parcel),
# employment (a job, annuity or one-time payment in its place), infra (amenities at
# the resettlement site, Third Schedule).
KINDS = ("monetary", "land", "employment", "infra")

SECOND_SCHEDULE: list[dict] = [
    {
        "head": "house",
        "label": "Housing unit at the resettlement site",
        "kind": "land",  # an allotment in kind, not a payment
        "basis": "Second Schedule element 1, s.31(2)(b) *(verify element numbering)*",
        "amount": AMOUNT_NOTE,
        "applies_to": "displaced",
    },
    {
        "head": "land_for_land",
        "label": "Land for land in the command area (irrigation projects)",
        "kind": "land",
        "basis": "Second Schedule element 2 (irrigation projects) *(verify)*",
        "amount": AMOUNT_NOTE,
        "applies_to": "irrigation",
    },
    {
        "head": "employment",
        "label": "Employment, annuity or one-time payment (family's choice)",
        "kind": "employment",
        "basis": "Second Schedule element 4, s.31(2)(c) *(verify)*",
        "amount": AMOUNT_NOTE,
        "applies_to": "all",
    },
    {
        "head": "subsistence_allowance",
        "label": "Subsistence grant for one year",
        "kind": "monetary",
        "basis": "Second Schedule element 5 *(verify)*",
        "amount": AMOUNT_NOTE,
        "applies_to": "displaced",
    },
    {
        "head": "transportation_allowance",
        "label": "Transportation cost for shifting",
        "kind": "monetary",
        "basis": "Second Schedule element 6 *(verify)*",
        "amount": AMOUNT_NOTE,
        "applies_to": "displaced",
    },
    {
        "head": "cattle_shed_grant",
        "label": "Cattle shed / petty shop cost",
        "kind": "monetary",
        "basis": "Second Schedule element 7 *(verify)*",
        "amount": AMOUNT_NOTE,
        "applies_to": "displaced",
    },
    {
        "head": "artisan_grant",
        "label": "One-time grant to artisan, small trader or self-employed",
        "kind": "monetary",
        "basis": "Second Schedule element 8 *(verify)*",
        "amount": AMOUNT_NOTE,
        "applies_to": "all",
    },
    {
        "head": "resettlement_allowance",
        "label": "One-time resettlement allowance",
        "kind": "monetary",
        "basis": "Second Schedule element 9 *(verify)*",
        "amount": AMOUNT_NOTE,
        "applies_to": "displaced",
    },
    {
        "head": "stamp_duty_exemption",
        "label": "Stamp duty and registration fee borne by the requiring body",
        "kind": "monetary",
        "basis": "Second Schedule element 10 *(verify)*",
        "amount": AMOUNT_NOTE,
        "applies_to": "all",
    },
    {
        "head": "resettlement_infrastructure",
        "label": "Infrastructural amenities at the resettlement site",
        "kind": "infra",
        "basis": "Third Schedule (25 amenities); s.38(1) proviso — 18 months",
        "amount": AMOUNT_NOTE,
        "applies_to": "displaced",
    },
]

HEAD_IDS: tuple[str, ...] = tuple(h["head"] for h in SECOND_SCHEDULE)
HEADS_BY_ID: dict[str, dict] = {h["head"]: h for h in SECOND_SCHEDULE}

# The two statuses a head can hold. `due` is what enumeration writes; `delivered` is
# what a recorded RR_ENTITLEMENT_DELIVERED writes. Nothing else is a status: an
# entitlement an officer decides does not apply is a determination that belongs in the
# ledger, not a silent third state written by the projection.
STATUSES: tuple[str, ...] = ("due", "delivered")


def initial_entitlements() -> dict[str, dict]:
    """The entitlement map a newly enumerated family starts with: every head due."""
    return {
        head: {"status": "due", "delivered_on": None, "evidence_document_id": None}
        for head in HEAD_IDS
    }


def is_head(head: str) -> bool:
    return head in HEADS_BY_ID


def normalise_entitlements(stored: dict | None) -> dict[str, dict]:
    """Read an `affected_families.rr_entitlements` blob defensively.

    A family enumerated under an earlier schedule is missing whatever heads have been
    added since; those read as `due`, never as absent, so a head can never be quietly
    dropped from a family's file by a schedule edit.
    """
    stored = stored if isinstance(stored, dict) else {}
    out: dict[str, dict] = {}
    for head in HEAD_IDS:
        row = stored.get(head)
        if not isinstance(row, dict):
            row = {}
        status = str(row.get("status") or "due")
        out[head] = {
            "status": status if status in STATUSES else "due",
            "delivered_on": row.get("delivered_on"),
            "evidence_document_id": row.get("evidence_document_id"),
        }
    return out


def schedule_view() -> list[dict]:
    """The heads as the API reports them — a copy, so no caller can edit the data."""
    return [dict(h) for h in SECOND_SCHEDULE]
