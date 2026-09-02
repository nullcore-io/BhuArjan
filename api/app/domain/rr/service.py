"""R&R and affected families — module F (Docs/final-product.md §5F, Docs/APIs.md §3.8).

Three things happen here and nowhere else:

1. **Enumeration.** A family is written as an encrypted `persons_interested` row (the
   head of the family) plus an `affected_families` row carrying the Second/Third
   Schedule entitlement map, and a `FAMILY_ENUMERATED` event is appended to the case
   ledger. The event payload carries the family *id*, `displaced` and `sc_st` — and
   nothing else. **The ledger is not encrypted**: it is a hash-chained audit record
   that an auditor, a ministry dashboard and (in aggregate) the public page all read,
   so a name in a payload would be a name that can never be deleted. The name lives in
   `persons_interested.pii_enc` under AES-256-GCM, where it can be re-keyed and, at the
   end of the retention period, destroyed.

2. **Delivery.** `RR_ENTITLEMENT_DELIVERED` flips one head of one family from `due` to
   `delivered` and appends the fact to the ledger with its evidence document. The
   rule-set decides *when* that is legal — both shipped tracks put it on the
   `POSSESSED` stage, because s.38(1) measures the R&R clocks from the award and
   possession follows payment.

3. **Reading.** Every read is masked by default. Raw PII is returned only to a role
   with jurisdiction *and* a stated purpose, and every such read writes an
   `admin_audit` `PII_READ` row naming the purpose and the fields — Docs/rules.md C5
   (DPDP Act 2023): *"decrypted only for roles with jurisdiction and purpose; every PII
   read is audited."*

A note on when the audit fires. `mask_name` needs the name to derive initials, so a
literal reading of "every decrypt is audited" would file an audit row for every row of
every list view — thousands of rows that say nothing, in the register an investigator
has to read. So the masked reference is computed **once, at enumeration**, and stored in
the clear beside the ciphertext (`consent_flags.masked_ref`): initials are already
public-safe by rules.md C5. A masked read therefore never touches the key at all, and
an audit row means exactly one thing — someone saw a name.

Every ledger write goes through `app.domain.events.service.append_event`; this module
never touches the `events` table itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_pii, encrypt_pii, mask_name
from app.core.problems import Problem, not_found
from app.core.time import ist_today
from app.domain.rr.schedules import (
    HEADS_BY_ID,
    HEAD_IDS,
    initial_entitlements,
    is_head,
    normalise_entitlements,
    schedule_view,
)
from app.models import (
    AdminAudit,
    AffectedFamily,
    Case,
    CaseState,
    Clock,
    Document,
    PersonInterested,
)

# The fields the encrypted blob holds. Full identifiers are never stored: an Aadhaar or
# a bank account number is reduced to its last four digits on the way in, so the worst
# a key compromise can yield is a name, a guardian's name and a village.
PII_FIELDS = ("name", "guardian", "id_ref_last4", "bank_ref_last4", "village")

# s.38(1) and its proviso — the two R&R clocks the summary reports when the rule-set
# has started them (the NH track carries neither; see Docs/rules.md B2).
RR_CLOCK_IDS = ("RR_MONETARY_6M", "RR_INFRA_18M")

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

FAMILY_ENUMERATED = "FAMILY_ENUMERATED"
RR_ENTITLEMENT_DELIVERED = "RR_ENTITLEMENT_DELIVERED"


@dataclass
class Enumeration:
    family: AffectedFamily
    person: PersonInterested | None
    seq: int
    stage: str
    duplicate: bool = False  # an Idempotency-Key replay, not a new family


# --- helpers -----------------------------------------------------------------------


def _validation_error(detail: str, errors: list | None = None) -> Problem:
    return Problem("validation_error", "Validation error", 422, detail, errors=errors)


def _as_uuid(value) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _last4(value) -> str | None:
    """Keep the last four alphanumerics of a reference and drop the rest.

    An officer who pastes a full Aadhaar or account number into the form must not be
    able to put it in the database, encrypted or not (Docs/rules.md C5, A5)."""
    digits = "".join(ch for ch in str(value or "") if ch.isalnum())
    return digits[-4:] if digits else None


def _clean_pii(head: dict | None) -> dict:
    """Normalise the submitted head-of-family fields into the stored blob."""
    head = head if isinstance(head, dict) else {}
    name = str(head.get("name") or "").strip()
    if not name:
        raise _validation_error(
            "head.name is required to enumerate a family",
            errors=[{"field": "head.name", "message": "missing"}],
        )
    return {
        "name": name,
        "guardian": (str(head.get("guardian") or "").strip() or None),
        # Both spellings accepted; both reduced to four characters.
        "id_ref_last4": _last4(head.get("id_ref_last4") or head.get("id_ref")),
        "bank_ref_last4": _last4(head.get("bank_ref_last4") or head.get("bank_ref")),
        "village": (str(head.get("village") or "").strip() or None),
    }


def _parse_date(value, field: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        raise _validation_error(
            f"{field} must be an ISO date (YYYY-MM-DD)",
            errors=[{"field": field, "message": "not a date", "value": value}],
        )


def masked_ref(person: PersonInterested | None) -> str:
    """The public-safe reference, read from the clear column written at enumeration.

    Only a row written before this module existed falls back to the key, and that
    fallback returns initials — it never returns a name, so it needs no audit row."""
    flags = person.consent_flags if person is not None and isinstance(person.consent_flags, dict) else {}
    ref = str(flags.get("masked_ref") or "").strip()
    if ref:
        return ref
    if person is None:
        return "Family —"
    try:
        return mask_name(decrypt_pii(person.pii_enc))
    except Exception:
        return "Family —"


def entitlement_rollup(entitlements: dict[str, dict]) -> dict:
    delivered = sum(1 for row in entitlements.values() if row["status"] == "delivered")
    total = len(entitlements)
    return {
        "heads_total": total,
        "heads_delivered": delivered,
        "heads_due": total - delivered,
        "delivered_pct": round(100.0 * delivered / total, 2) if total else 0.0,
    }


# --- PII reads ---------------------------------------------------------------------


def audit_pii_read(
    db: Session,
    actor_id: uuid.UUID | None,
    family: AffectedFamily,
    purpose: str,
    fields: list[str],
    case: Case | None = None,
) -> None:
    """One row per family whose name actually left the server (Docs/rules.md C5)."""
    db.add(
        AdminAudit(
            user_id=actor_id,
            action="PII_READ",
            target=str(family.id),
            meta={
                "purpose": purpose,
                "fields": list(fields),
                "case_id": str(family.case_id) if family.case_id else None,
                "case_no": case.case_no if case is not None else None,
            },
        )
    )


def family_view(
    family: AffectedFamily,
    person: PersonInterested | None,
    *,
    unlock: bool = False,
) -> dict:
    entitlements = normalise_entitlements(family.rr_entitlements)
    flags = person.consent_flags if person is not None and isinstance(person.consent_flags, dict) else {}
    view = {
        "id": str(family.id),
        "case_id": str(family.case_id) if family.case_id else None,
        "ref": masked_ref(person),
        "category": person.category if person is not None else None,
        "displaced": bool(family.displaced),
        "sc_st": bool(person.sc_st) if person is not None else False,
        "enumerated_on": flags.get("enumerated_on"),
        "synthetic": bool(flags.get("synthetic")),
        "pii": "unlocked" if unlock else "masked",
        "entitlements": entitlements,
        **entitlement_rollup(entitlements),
    }
    if unlock and person is not None:
        view["head"] = decrypt_pii(person.pii_enc)
    return view


# --- enumeration -------------------------------------------------------------------


def _replayed_enumeration(
    db: Session, case: Case, idempotency_key: str | None
) -> Enumeration | None:
    """Answer a retried enumeration with the family the key already bought.

    Without this, a retry would mint a *second* `persons_interested` row and a second
    family before `append_event` ever saw the key — and then be refused, because the new
    family id makes the payload differ from the one the key recorded. The retry would
    read as a validation error on a request that had in fact already succeeded. So the
    key is resolved to its event here, before anything is written.

    A genuine race (two retries in flight at once) still falls through to
    `append_event`, which serialises on the case and answers the loser with the
    "key already used for a different request" validation error rather than a duplicate
    family — the safe end of the trade.
    """
    if not idempotency_key:
        return None
    from app.models import Event

    existing = db.scalar(select(Event).where(Event.idempotency_key == idempotency_key))
    if existing is None:
        return None
    if existing.type != FAMILY_ENUMERATED or existing.case_id != case.id:
        return None  # let append_event raise the right error for a mis-used key
    family_id = _as_uuid((existing.payload or {}).get("family_id"))
    family = db.get(AffectedFamily, family_id) if family_id else None
    if family is None:
        return None
    person = db.get(PersonInterested, family.head_person_id) if family.head_person_id else None
    state = db.get(CaseState, case.id)
    return Enumeration(
        family=family,
        person=person,
        seq=existing.seq,
        stage=state.stage if state is not None else "",
        duplicate=True,
    )


def enumerate_family(
    db: Session,
    case: Case,
    actor_id: uuid.UUID,
    *,
    head: dict,
    category: str | None = None,
    displaced: bool = False,
    sc_st: bool = False,
    occurred_at: date | None = None,
    today: date | None = None,
    idempotency_key: str | None = None,
    synthetic: bool = False,
) -> Enumeration:
    """Record one affected family and append `FAMILY_ENUMERATED` to the case ledger.

    The rows are written first because the event payload names the family id; if the
    rule-set refuses the append (the stage does not permit enumeration) the caller
    rolls back and nothing survives — the family row and its ledger entry are one
    transaction or neither.
    """
    from app.domain.events.service import append_event

    pii = _clean_pii(head)
    occurred = _parse_date(occurred_at, "occurred_at") or (today or ist_today())

    replay = _replayed_enumeration(db, case, idempotency_key)
    if replay is not None:
        return replay

    person = PersonInterested(
        case_id=case.id,
        pii_enc=encrypt_pii(pii),
        category=(str(category).strip() if category else None),
        sc_st=bool(sc_st),
        consent_flags={
            # Docs/rules.md C5: consent and purpose flags are stored with the record.
            "masked_ref": mask_name(pii),
            "purpose": "land acquisition compensation and R&R entitlement tracking",
            "enumerated_on": occurred.isoformat(),
            "retention": "acquisition lifecycle + statutory retention *(verify)*",
            "synthetic": bool(synthetic),
        },
    )
    db.add(person)
    db.flush()

    family = AffectedFamily(
        case_id=case.id,
        head_person_id=person.id,
        displaced=bool(displaced),
        rr_entitlements=initial_entitlements(),
    )
    db.add(family)
    db.flush()

    # No PII. `count`/`displaced_count` are what app.domain.cases.projections.apply_event
    # folds into case_state.families_affected / families_displaced.
    payload: dict = {
        "family_id": str(family.id),
        "displaced": bool(displaced),
        "sc_st": bool(sc_st),
        "count": 1,
    }
    if displaced:
        payload["displaced_count"] = 1
    if synthetic:
        payload["synthetic"] = True

    result = append_event(
        db,
        case,
        FAMILY_ENUMERATED,
        occurred,
        actor_id,
        payload,
        idempotency_key=idempotency_key,
        today=today,
    )
    return Enumeration(family=family, person=person, seq=result.seq, stage=result.stage)


# --- delivery ----------------------------------------------------------------------


def deliver_entitlement(
    db: Session,
    case: Case,
    family: AffectedFamily,
    head: str,
    actor_id: uuid.UUID,
    *,
    delivered_on: date | str | None = None,
    evidence_document_id: str | uuid.UUID | None = None,
    today: date | None = None,
    idempotency_key: str | None = None,
    synthetic: bool = False,
) -> dict:
    """Flip one Second/Third Schedule head to `delivered` and append the event.

    Re-delivering a head is allowed and appends a second event: the ledger is
    append-only, so a corrected delivery date is a new fact, never an edit
    (Docs/rules.md C1).
    """
    from app.domain.events.service import append_event

    head = str(head or "").strip()
    if not is_head(head):
        raise _validation_error(
            f"'{head or '(missing)'}' is not a Second/Third Schedule head; "
            f"expected one of {', '.join(HEAD_IDS)}",
            errors=[{"field": "head", "message": "unknown entitlement head", "value": head}],
        )

    when = _parse_date(delivered_on, "delivered_on") or (today or ist_today())

    doc_id = None
    if evidence_document_id not in (None, ""):
        doc_id = _as_uuid(evidence_document_id)
        if doc_id is None:
            raise _validation_error(
                "evidence_document_id is not a uuid",
                errors=[{"field": "evidence_document_id", "message": "not a uuid"}],
            )
        doc = db.get(Document, doc_id)
        if doc is None:
            raise _validation_error(
                "evidence_document_id does not name a stored document",
                errors=[{"field": "evidence_document_id", "message": "unknown document"}],
            )
        if doc.case_id is not None and doc.case_id != case.id:
            raise _validation_error(
                "evidence_document_id belongs to a different case",
                errors=[{"field": "evidence_document_id", "message": "wrong case"}],
            )

    # JSONB is not tracked for in-place mutation: assign a fresh dict or the update is
    # silently dropped on flush.
    entitlements = normalise_entitlements(family.rr_entitlements)
    entitlements[head] = {
        "status": "delivered",
        "delivered_on": when.isoformat(),
        "evidence_document_id": str(doc_id) if doc_id else None,
    }
    family.rr_entitlements = entitlements
    db.add(family)
    db.flush()

    payload: dict = {
        "family_id": str(family.id),
        "head": head,
        "evidence_doc": str(doc_id) if doc_id else None,
        "delivered_on": when.isoformat(),
    }
    if synthetic:
        payload["synthetic"] = True

    result = append_event(
        db,
        case,
        RR_ENTITLEMENT_DELIVERED,
        when,
        actor_id,
        payload,
        document_id=doc_id,
        idempotency_key=idempotency_key,
        today=today,
    )
    person = db.get(PersonInterested, family.head_person_id) if family.head_person_id else None
    return {
        "family": family_view(family, person),
        "head": HEADS_BY_ID[head] | {"status": "delivered", "delivered_on": when.isoformat()},
        "seq": result.seq,
        "stage": result.stage,
    }


# --- reads -------------------------------------------------------------------------


def get_family(db: Session, family_id) -> AffectedFamily:
    fid = _as_uuid(family_id)
    family = db.get(AffectedFamily, fid) if fid else None
    if family is None:
        raise not_found()
    return family


def list_families(
    db: Session,
    case: Case,
    *,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    unlock: bool = False,
    purpose: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> dict:
    """Families of one case, masked unless `unlock`. Ordered and paged by family id."""
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))

    q = select(AffectedFamily).where(AffectedFamily.case_id == case.id)
    total = int(
        db.scalar(
            select(func.count())
            .select_from(AffectedFamily)
            .where(AffectedFamily.case_id == case.id)
        )
        or 0
    )

    if cursor:
        after = _as_uuid(cursor)
        if after is None:
            raise _validation_error("malformed cursor")
        q = q.where(AffectedFamily.id > after)

    rows = list(db.scalars(q.order_by(AffectedFamily.id.asc()).limit(limit + 1)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    people = {
        p.id: p
        for p in db.scalars(
            select(PersonInterested).where(
                PersonInterested.id.in_([r.head_person_id for r in rows if r.head_person_id]
                                        or [uuid.UUID(int=0)])
            )
        ).all()
    }

    items = []
    for family in rows:
        person = people.get(family.head_person_id)
        items.append(family_view(family, person, unlock=unlock))
        if unlock and person is not None:
            audit_pii_read(db, actor_id, family, purpose or "", list(PII_FIELDS), case)

    return {
        "items": items,
        "families": items,
        "total": total,
        "next_cursor": str(rows[-1].id) if has_more and rows else None,
        "pii": "unlocked" if unlock else "masked",
        "purpose": purpose if unlock else None,
    }


def rr_summary(db: Session, case: Case, today: date) -> dict:
    """Heads × status counts for the case, plus the s.38 R&R clocks (APIs.md §3.8)."""
    families = list(
        db.scalars(select(AffectedFamily).where(AffectedFamily.case_id == case.id)).all()
    )
    people = {
        p.id: p
        for p in db.scalars(
            select(PersonInterested).where(PersonInterested.case_id == case.id)
        ).all()
    }

    counts = {head: {"due": 0, "delivered": 0} for head in HEAD_IDS}
    delivered_total = 0
    displaced = 0
    sc_st = 0
    for family in families:
        if family.displaced:
            displaced += 1
        person = people.get(family.head_person_id)
        if person is not None and person.sc_st:
            sc_st += 1
        for head, row in normalise_entitlements(family.rr_entitlements).items():
            counts[head][row["status"]] += 1
            if row["status"] == "delivered":
                delivered_total += 1

    heads = []
    for spec in schedule_view():
        head = spec["head"]
        due = counts[head]["due"]
        done = counts[head]["delivered"]
        heads.append(
            spec
            | {
                "counts": counts[head],
                "families": due + done,
                "delivered_pct": round(100.0 * done / (due + done), 2) if (due + done) else 0.0,
            }
        )

    cells = len(families) * len(HEAD_IDS)
    clocks = [
        row
        for row in db.scalars(
            select(Clock).where(
                Clock.case_id == case.id, Clock.clock_id.in_(RR_CLOCK_IDS)
            )
        ).all()
    ]
    from app.domain.rules.clocks import clock_view

    state = db.get(CaseState, case.id)
    return {
        "case_id": str(case.id),
        "case_no": case.case_no,
        "families": {
            "total": len(families),
            "displaced": displaced,
            "sc_st": sc_st,
        },
        "heads": heads,
        "status_counts": {
            "due": cells - delivered_total,
            "delivered": delivered_total,
        },
        "rr_progress_pct": round(100.0 * delivered_total / cells, 2) if cells else 0.0,
        "clocks": [clock_view(row) for row in sorted(clocks, key=lambda c: c.clock_id)],
        "as_of_seq": state.as_of_seq if state else None,
        "as_of_date": today.isoformat(),
        "schedule_note": (
            "Statuses only — the Second Schedule amounts are as notified by the "
            "appropriate Government (verify current indexation)."
        ),
    }
