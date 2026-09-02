"""Event append service — THE core write.

Contract (Docs/Backend.md §4, Docs/APIs.md §3.4):
- One transaction: lock the case (case_state row, then the chain head) FOR UPDATE →
  Idempotency-Key replay → validate transition against the pinned ruleset (stage,
  requires, guard) → insert with prev_hash/hash → update case_state projection →
  evaluate clocks (close/start/extend/suspend) → return AppendResult.
- Raises app.core.problems Problems: transition_not_allowed, precondition_failed,
  guard_failed, document_required, stale_state.

Idempotency. The key lookup runs *inside* the lock, so two retries of the same request
on one case cannot both miss the replay; the insert additionally runs in a savepoint and
answers a lost unique-index race as a replay rather than a 500. A key stands for one
request: replaying it with a different type, date, document or payload is a
validation_error, not a silently discarded statutory event.

The function flushes but never commits: the caller owns the transaction, so a router
that also writes parcels or compensation lines gets one atomic unit with the ledger.

Clock-evaluation date. Clocks are evaluated as of `min(today, case frontier)`, where the
frontier is the latest `occurred_at` the case's ledger already carries once this event
joins it. Recording something that happened today evaluates at today — the ordinary
case. Back-filling history in order (the seed, a scanned gazette from last year)
evaluates as of the legal date each event carries, so entering a case's past does not
trip a breach that the very next back-filled event closes. But a *back-dated* event on a
case that is already up to date never rewinds the projection to its own legal date:
see `_evaluation_date`. Bringing a case up to the present is still the job of the clock
evaluation on read (`GET /cases/{id}/clocks`) and of the hourly scheduler, both of
which pass a real `today`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.problems import Problem, stale_state
from app.core.time import ist_today
from app.domain.events.hash import compute_hash, event_fields, to_hex
from app.models import Case, CaseState, Clock, Event

REVERSAL_EVENT = "EVENT_REVERSED"
# Clock states that can only have been written by an evaluation past the due date.
BREACHED_CLOCK_STATUSES = ("breached", "lapsed")


@dataclass
class AppendResult:
    seq: int
    id: uuid.UUID
    hash: str  # hex
    prev_hash: str | None  # hex
    stage: str
    clocks_changed: list[dict] = field(default_factory=list)
    duplicate: bool = False  # idempotent replay


def _differences(
    existing: Event,
    event_type: str,
    occurred_at: date,
    document_id: uuid.UUID | None,
    payload: dict,
) -> list[str]:
    """How a replayed request differs from the event the key already bought."""
    diffs: list[str] = []
    if existing.type != event_type:
        diffs.append(f"type {existing.type!r} -> {event_type!r}")
    if existing.occurred_at != occurred_at:
        diffs.append(f"occurred_at {existing.occurred_at} -> {occurred_at}")
    if (existing.document_id or None) != (document_id or None):
        diffs.append(f"document_id {existing.document_id} -> {document_id}")
    if (existing.payload or {}) != (payload or {}):
        diffs.append("payload differs")
    return diffs


def _replay(
    db: Session,
    case: Case,
    existing: Event,
    event_type: str,
    occurred_at: date,
    document_id: uuid.UUID | None,
    payload: dict,
) -> AppendResult:
    """Return the event a re-used Idempotency-Key already bought.

    A key stands for one request, not for "whatever arrives next": replaying it with a
    different event silently discarded a statutory append and answered 201 with the
    first event's seq, so the officer's screen showed a success that never happened.
    """
    from app.domain.rules.engine import current_stage

    if existing.case_id != case.id:
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            "Idempotency-Key has already been used on a different case",
        )
    diffs = _differences(existing, event_type, occurred_at, document_id, payload)
    if diffs:
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            "Idempotency-Key has already been used on this case for a different "
            f"request ({'; '.join(diffs)}); use a fresh key to record a new event",
            errors=[
                {
                    "field": "Idempotency-Key",
                    "message": "already used for a different request",
                    "recorded_seq": existing.seq,
                    "recorded_type": existing.type,
                }
            ],
        )
    return AppendResult(
        seq=existing.seq,
        id=existing.id,
        hash=to_hex(existing.hash) or "",
        prev_hash=to_hex(existing.prev_hash),
        stage=current_stage(db, case),
        clocks_changed=[],
        duplicate=True,
    )


def _validate_reversal(db: Session, case: Case, payload: dict) -> None:
    """EVENT_REVERSED must name an event of *this* case (Docs/APIs.md §3.4).

    A correction is only meaningful against the event it corrects: an unparseable or
    foreign `reversed_event_id` recorded a permanent, hash-chained marker that points at
    nothing, and the projection below would silently do nothing with it.
    """
    raw = payload.get("reversed_event_id")
    text = str(raw if raw is not None else "").strip()
    try:
        target_id = uuid.UUID(text)
    except (TypeError, ValueError):
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            "EVENT_REVERSED must name the event it corrects in "
            "payload.reversed_event_id (that event's uuid)",
            errors=[
                {
                    "field": "payload.reversed_event_id",
                    "message": "missing or not a uuid",
                    "value": raw,
                }
            ],
        )
    owner = db.scalar(select(Event.case_id).where(Event.id == target_id))
    if owner is None or owner != case.id:
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            f"event {target_id} is not an event of this case; a correction may only "
            "reverse an event recorded on the case it is filed against",
            errors=[
                {
                    "field": "payload.reversed_event_id",
                    "message": "not an event of this case",
                    "value": str(target_id),
                }
            ],
        )


def _evaluation_date(
    db: Session, case_id: uuid.UUID, event_seq: int, occurred_at: date, today: date
) -> date:
    """The date this append evaluates the case's clocks at.

    `min(today, occurred_at)` alone let a back-dated append rewind the whole clock
    projection. An officer recording today a payment that legally happened fifteen
    months ago re-evaluated every clock as of that past date: breached clocks flipped
    back to 'running', the risk score collapsed, and the case dropped out of the breach
    list and the escalation ladder until the next hourly sweep.

    So the date is clamped to the case's *frontier*: the later of

      - the latest `occurred_at` already in its ledger, ignoring the event being
        appended, and
      - a date its own clock rows prove an evaluation has already reached — a row
        reading 'breached' or 'lapsed' can only have been written by an evaluation past
        its due date, and every clock of a case is evaluated in one pass, so
        `max(due_date) + 1` over those rows is a floor the projection demonstrably
        already stands on. Without it a case carried forward by a *read* rather than by
        an event — the ordinary way a breach appears on the dashboard — would still
        rewind, because nothing in its ledger is dated recently.

    Back-filling history in ascending order is unchanged: each back-filled event is
    itself the frontier, and a clock breached during the back-fill only floors the
    evaluation at a date the back-fill had already passed. The whole thing is capped at
    `today`, so a future-dated event never evaluates a case in the future, and moving
    the demo date backwards still shows the case as of that earlier date.
    """
    frontier = db.scalar(
        select(func.max(Event.occurred_at)).where(
            Event.case_id == case_id, Event.seq != event_seq
        )
    )
    if frontier is not None and frontier > occurred_at:
        occurred_at = frontier

    breached_due = db.scalar(
        select(func.max(Clock.due_date)).where(
            Clock.case_id == case_id, Clock.status.in_(BREACHED_CLOCK_STATUSES)
        )
    )
    if breached_due is not None and breached_due + timedelta(days=1) > occurred_at:
        occurred_at = breached_due + timedelta(days=1)

    return min(today, occurred_at)


def _is_idempotency_conflict(exc: IntegrityError) -> bool:
    """True when the insert lost the race for a unique Idempotency-Key."""
    orig = getattr(exc, "orig", None)
    constraint = getattr(getattr(orig, "diag", None), "constraint_name", None) or ""
    return "idempotency_key" in (constraint or str(orig))


def append_event(
    db: Session,
    case: Case,
    event_type: str,
    occurred_at: date,
    actor_id: uuid.UUID,
    payload: dict,
    document_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    if_match: int | None = None,
    today: date | None = None,
    system: bool = False,  # consequence events emitted by the clock engine
) -> AppendResult:
    from app.domain.cases.projections import apply_event, ensure_case_state
    from app.domain.rules import clocks as clock_engine
    from app.domain.rules.engine import initial_stage, resolve_ruleset, validate_append

    today = today or ist_today()
    payload = dict(payload or {})
    if system:
        # Stamped before the replay comparison so a replayed consequence compares equal
        # to the one already in the ledger.
        payload.setdefault("system", True)
    if isinstance(occurred_at, str):
        occurred_at = date.fromisoformat(occurred_at[:10])

    # --- 1. serialise appends on this case ----------------------------------------
    # The chain head is what two concurrent appends race for, so that is what we lock
    # (Docs/Backend.md §4). The projection row is locked too: it exists even when the
    # ledger is empty, so the very first append on a case is serialised as well.
    db.flush()
    rs = resolve_ruleset(case)
    state = ensure_case_state(db, case, initial_stage(rs))
    db.execute(
        select(CaseState.case_id).where(CaseState.case_id == case.id).with_for_update()
    ).first()

    # --- 2. idempotent replay, inside the lock ------------------------------------
    # Looking the key up before the lock let two concurrent retries of the same request
    # both miss the replay; the loser then died on the unique index with a 500 instead
    # of replaying. Everything on one case is serialised here, and the flush below
    # catches the cross-case race the row lock cannot cover.
    if idempotency_key:
        existing = db.scalar(
            select(Event).where(Event.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return _replay(
                db, case, existing, event_type, occurred_at, document_id, payload
            )

    head = db.execute(
        select(Event.hash)
        .where(Event.case_id == case.id)
        .order_by(Event.seq.desc())
        .limit(1)
        .with_for_update()
    ).first()
    prev_hash = bytes(head[0]) if head is not None and head[0] else None

    # --- 3. optimistic concurrency ------------------------------------------------
    if if_match is not None and int(if_match) != int(state.as_of_seq or 0):
        raise stale_state(
            f"If-Match {if_match} does not match case_state.as_of_seq "
            f"{state.as_of_seq or 0}; reload the case and retry"
        )

    # --- 4. the rule-set decides ---------------------------------------------------
    stage = state.stage or initial_stage(rs)
    verdict = validate_append(
        db, case, rs, event_type, stage,
        document_id=document_id, payload=payload, system=system,
    )
    if event_type == REVERSAL_EVENT:
        _validate_reversal(db, case, payload)

    # --- 5. append to the chain ----------------------------------------------------
    event = Event(
        id=uuid.uuid4(),
        case_id=case.id,
        type=event_type,
        occurred_at=occurred_at,
        actor_id=actor_id,
        payload=payload,
        document_id=document_id,
        idempotency_key=idempotency_key,
        prev_hash=prev_hash,
    )
    event.hash = compute_hash(prev_hash, event_fields(event))
    savepoint = db.begin_nested()
    try:
        db.add(event)
        db.flush()  # assigns seq
    except IntegrityError as exc:
        savepoint.rollback()
        if not (idempotency_key and _is_idempotency_conflict(exc)):
            raise
        # Another transaction committed this key while we were writing. It is the same
        # request arriving twice, so answer it the way the first one was answered.
        existing = db.scalar(
            select(Event).where(Event.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        return _replay(db, case, existing, event_type, occurred_at, document_id, payload)
    else:
        savepoint.commit()

    # --- 6. projection -------------------------------------------------------------
    state = apply_event(db, case, event, verdict["to_stage"], initial_stage(rs))

    # --- 7. clocks ------------------------------------------------------------------
    clocks_changed: list[dict] = []
    if not clock_engine.is_evaluating(case.id):
        as_of = _evaluation_date(db, case.id, event.seq, occurred_at, today)
        clocks_changed = clock_engine.evaluate(db, case, as_of, rs)
        state = db.get(CaseState, case.id) or state

    return AppendResult(
        seq=event.seq,
        id=event.id,
        hash=to_hex(event.hash) or "",
        prev_hash=to_hex(event.prev_hash),
        stage=state.stage,
        clocks_changed=clocks_changed,
        duplicate=False,
    )


# --- integrity ---------------------------------------------------------------------


def case_events(db: Session, case_id: uuid.UUID) -> list[Event]:
    return list(
        db.scalars(
            select(Event).where(Event.case_id == case_id).order_by(Event.seq.asc())
        ).all()
    )


def verify_case_chain(db: Session, case_id: uuid.UUID) -> dict:
    """Recompute the whole chain from the stored rows (Docs/APIs.md §3.3).

    Recomputing hashes catches an edited row and a deleted row in the middle of the
    chain, but not a *truncated tail*: delete the last event and the shortened chain
    still recomputes perfectly, because nothing in it says how long it should be. So
    the chain is also checked against `case_state.as_of_seq`, which the projection
    advances on every append — the one number outside the ledger that remembers how far
    the ledger reached. Deleting the head event, or every event of the case, leaves
    `as_of_seq` pointing past the end and is reported as the tampering it is.
    """
    from app.domain.events.hash import verify_chain

    # Expire first: a chain check must read the database, not a cached identity map.
    db.expire_all()
    events = case_events(db, case_id)
    result = verify_chain(events)
    if not result["verified"]:
        return result

    state = db.get(CaseState, case_id)
    as_of_seq = None if state is None or state.as_of_seq is None else int(state.as_of_seq)
    if as_of_seq is None:
        return result

    max_seq = max((int(e.seq) for e in events), default=None)
    if max_seq is None:
        return {
            **result,
            "verified": False,
            "first_bad_seq": as_of_seq,
            "reason": (
                f"the ledger for this case is empty, but case_state was folded up to "
                f"seq {as_of_seq}: every event has been deleted behind the API"
            ),
        }
    if max_seq < as_of_seq:
        return {
            **result,
            "verified": False,
            "first_bad_seq": as_of_seq,
            "reason": (
                f"the ledger ends at seq {max_seq} but case_state was folded up to seq "
                f"{as_of_seq}: the tail of the chain has been deleted behind the API"
            ),
        }
    return result
