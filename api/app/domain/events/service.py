"""Event append service — THE core write.

Contract (Docs/Backend.md §4, Docs/APIs.md §3.4):
- One transaction: lock last event hash per case FOR UPDATE → validate transition
  against the pinned ruleset (stage, requires, guard) → insert with prev_hash/hash →
  update case_state projection → evaluate clocks (close/start/extend/suspend) →
  return AppendResult. Idempotency-Key replay returns the original result.
- Raises app.core.problems Problems: transition_not_allowed, precondition_failed,
  guard_failed, document_required, stale_state.

The function flushes but never commits: the caller owns the transaction, so a router
that also writes parcels or compensation lines gets one atomic unit with the ledger.

Clock-evaluation date. Clocks are evaluated as of `min(today, occurred_at)`. Recording
something that happened today evaluates at today — the ordinary case. Back-filling
history (the seed, a scanned gazette from last year) evaluates as of the legal date the
event carries, so entering a case's past does not trip a breach that the very next
back-filled event closes. Bringing a case up to the present is the job of the clock
evaluation on read (`GET /cases/{id}/clocks`) and of the hourly scheduler, both of
which pass a real `today`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.problems import Problem, stale_state
from app.domain.events.hash import compute_hash, event_fields, to_hex
from app.models import Case, CaseState, Event


@dataclass
class AppendResult:
    seq: int
    id: uuid.UUID
    hash: str  # hex
    prev_hash: str | None  # hex
    stage: str
    clocks_changed: list[dict] = field(default_factory=list)
    duplicate: bool = False  # idempotent replay


def _replay(db: Session, case: Case, existing: Event) -> AppendResult:
    from app.domain.rules.engine import current_stage

    return AppendResult(
        seq=existing.seq,
        id=existing.id,
        hash=to_hex(existing.hash) or "",
        prev_hash=to_hex(existing.prev_hash),
        stage=current_stage(db, case),
        clocks_changed=[],
        duplicate=True,
    )


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

    today = today or date.today()
    payload = dict(payload or {})
    if isinstance(occurred_at, str):
        occurred_at = date.fromisoformat(occurred_at[:10])

    # --- 1. idempotent replay -----------------------------------------------------
    if idempotency_key:
        existing = db.scalar(
            select(Event).where(Event.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if existing.case_id != case.id:
                raise Problem(
                    "validation_error",
                    "Validation error",
                    422,
                    "Idempotency-Key has already been used on a different case",
                )
            return _replay(db, case, existing)

    # --- 2. serialise appends on this case ----------------------------------------
    # The chain head is what two concurrent appends race for, so that is what we lock
    # (Docs/Backend.md §4). The projection row is locked too: it exists even when the
    # ledger is empty, so the very first append on a case is serialised as well.
    db.flush()
    rs = resolve_ruleset(case)
    state = ensure_case_state(db, case, initial_stage(rs))
    db.execute(
        select(CaseState.case_id).where(CaseState.case_id == case.id).with_for_update()
    ).first()
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
    if system:
        payload.setdefault("system", True)

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
    db.add(event)
    db.flush()  # assigns seq

    # --- 6. projection -------------------------------------------------------------
    state = apply_event(db, case, event, verdict["to_stage"], initial_stage(rs))

    # --- 7. clocks ------------------------------------------------------------------
    clocks_changed: list[dict] = []
    if not clock_engine.is_evaluating(case.id):
        clocks_changed = clock_engine.evaluate(db, case, min(today, occurred_at), rs)
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
    """Recompute the whole chain from the stored rows (Docs/APIs.md §3.3)."""
    from app.domain.events.hash import verify_chain

    # Expire first: a chain check must read the database, not a cached identity map.
    db.expire_all()
    return verify_chain(case_events(db, case_id))
