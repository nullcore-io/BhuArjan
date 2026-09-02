"""`case_state` — the synchronous projection (Docs/Backend.md §8).

The ledger is the truth; this table is a convenience. Every figure here is derived
from event payloads and can be thrown away and rebuilt by replay, which is exactly
what `rebuild_case` does. Nothing in the API may write to `case_state` except through
these functions.

Derivations:
  stage                 the `to_stage` of the last transition the rule-set recognised
  as_of_seq             the seq of the last event folded in (Docs/rules.md C7)
  comp_assessed_paise   COMPENSATION_ASSESSED.payload.assessed_total_paise (replaces —
                        a re-assessment supersedes, it does not add)
  comp_paid_paise       sum of PAYMENT_MADE.payload.amount_paise
  area_notified_ha      NOTIFICATION_3A / PRELIM_NOTIFICATION_S11 payload.total_area_ha
  area_acquired_ha      = area notified once possession is taken; possession_pct = 100
  families_*            FAMILY_ENUMERATED payloads
  risk_score            the most-elapsed open clock, as a percentage

EVENT_REVERSED withdraws the *figures* the event it names contributed: a reversed
payment stops counting towards `comp_paid_paise`, a reversed assessment falls back to
the newest assessment nobody has reversed, a reversed enumeration stops counting a
family. It does not move the stage back. Un-lapsing a case — restoring the stage a
reversed transition moved it out of — is deliberately out of scope here and in
`rebuild_case`: a reversed transition still replays.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import ist_today
from app.models import Case, CaseState, Clock, Event

NOTIFICATION_EVENTS = ("NOTIFICATION_3A", "PRELIM_NOTIFICATION_S11")
POSSESSION_EVENTS = ("POSSESSION_TAKEN_S38", "POSSESSION_3E")
REVERSAL_EVENT = "EVENT_REVERSED"
ASSESSMENT_EVENT = "COMPENSATION_ASSESSED"
OPEN_CLOCK_STATUSES = ("running", "extended", "suspended")
# Clocks that count towards the risk score. A clock a court has suspended is
# deliberately absent: the elapsed fraction keeps climbing while the stay is on (the
# due date only moves when the stay is vacated), so a case lawfully frozen by a writ
# would pin the top of every district ranking, indistinguishable from a case in
# statutory default. Nobody is in default while a court has stopped the proceeding.
RISK_CLOCK_STATUSES = ("running", "extended")
BREACHED_STATUSES = ("breached", "lapsed")


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def ensure_case_state(db: Session, case: Case, initial_stage: str = "PROPOSED") -> CaseState:
    state = db.get(CaseState, case.id)
    if state is None:
        state = CaseState(
            case_id=case.id,
            stage=initial_stage,
            as_of_seq=None,
            area_notified_ha=0,
            area_acquired_ha=0,
            comp_assessed_paise=0,
            comp_paid_paise=0,
            families_affected=0,
            families_displaced=0,
            possession_pct=0,
            risk_score=0,
        )
        db.add(state)
        db.flush()
    return state


def reversed_event_ids(
    db: Session,
    case_id: uuid.UUID,
    through_seq: int | None = None,
    *,
    before_seq: int | None = None,
) -> set[uuid.UUID]:
    """The event ids this case's EVENT_REVERSED markers withdraw.

    Bounded by seq — `through_seq` inclusive, `before_seq` exclusive — so a replay sees
    exactly the reversals that had been recorded by the point it has reached, which is
    what makes the incremental fold and `rebuild_case` land on the same numbers.
    """
    q = select(Event.payload).where(
        Event.case_id == case_id, Event.type == REVERSAL_EVENT
    )
    if through_seq is not None:
        q = q.where(Event.seq <= through_seq)
    if before_seq is not None:
        q = q.where(Event.seq < before_seq)
    out: set[uuid.UUID] = set()
    for (payload,) in db.execute(q).all():
        raw = str((payload or {}).get("reversed_event_id") or "").strip()
        try:
            out.add(uuid.UUID(raw))
        except (TypeError, ValueError):
            continue  # append_event refuses these; an old row is simply not a reversal
    return out


def _assessed_after_reversal(db: Session, case_id: uuid.UUID, through_seq: int) -> int:
    """The assessed total once a reassessment is withdrawn: the newest
    COMPENSATION_ASSESSED no reversal recorded by `through_seq` names, or 0 when every
    assessment on the case has been reversed. 0 closes the s.38 gate (Docs/rules.md C3),
    which is the right answer when nothing stands assessed."""
    withdrawn = reversed_event_ids(db, case_id, through_seq)
    rows = db.execute(
        select(Event.id, Event.payload)
        .where(Event.case_id == case_id, Event.type == ASSESSMENT_EVENT)
        .order_by(Event.seq.desc())
    ).all()
    for event_id, payload in rows:
        if event_id in withdrawn:
            continue
        return _int((payload or {}).get("assessed_total_paise"))
    return 0


def _apply_reversal(db: Session, case: Case, event: Event, state: CaseState) -> None:
    """Withdraw from `case_state` what the event this EVENT_REVERSED names contributed.

    Only the figures a *non-transition* event folds in are withdrawn — money and
    families; that is exactly the set `rebuild_case` drops by skipping the reversed
    event, so the two projections agree. Areas and possession come only from
    transitions, which replay regardless, and no stage is moved: see the module
    docstring on un-lapsing.
    """
    raw = str((event.payload or {}).get("reversed_event_id") or "").strip()
    try:
        target_id = uuid.UUID(raw)
    except (TypeError, ValueError):
        return
    if target_id in reversed_event_ids(db, case.id, before_seq=event.seq):
        # An earlier marker already withdrew this event. Subtracting again would take
        # the money out twice, while `rebuild_case` skips the event exactly once — the
        # two projections have to agree even when a correction is recorded twice.
        return
    target = db.scalar(
        select(Event).where(Event.id == target_id, Event.case_id == case.id)
    )
    if target is None:
        return
    payload = target.payload or {}

    if target.type == "PAYMENT_MADE":
        state.comp_paid_paise = max(
            0, int(state.comp_paid_paise or 0) - _int(payload.get("amount_paise"))
        )
    elif target.type == ASSESSMENT_EVENT:
        state.comp_assessed_paise = _assessed_after_reversal(db, case.id, event.seq)
    elif target.type == "FAMILY_ENUMERATED":
        count = _int(payload.get("count"), 1) or 1
        state.families_affected = max(0, int(state.families_affected or 0) - count)
        if payload.get("displaced"):
            displaced = _int(payload.get("displaced_count"), count) or count
            state.families_displaced = max(
                0, int(state.families_displaced or 0) - displaced
            )


def apply_event(
    db: Session,
    case: Case,
    event: Event,
    to_stage: str | None = None,
    initial_stage: str = "PROPOSED",
    *,
    reversal_effects: bool = True,
) -> CaseState:
    """Fold one event into `case_state`. Called inside the append transaction.

    `reversal_effects=False` is `rebuild_case` speaking: a replay drops the reversed
    events themselves rather than adding them and subtracting them again, so the
    EVENT_REVERSED marker must not subtract a second time.
    """
    state = ensure_case_state(db, case, initial_stage)
    payload = event.payload or {}

    if to_stage:
        state.stage = to_stage
    state.as_of_seq = event.seq

    if event.type in NOTIFICATION_EVENTS:
        area = _num(payload.get("total_area_ha"))
        if area:
            state.area_notified_ha = area

    elif event.type == ASSESSMENT_EVENT:
        state.comp_assessed_paise = _int(payload.get("assessed_total_paise"))

    elif event.type == "PAYMENT_MADE":
        state.comp_paid_paise = int(state.comp_paid_paise or 0) + _int(
            payload.get("amount_paise")
        )

    elif event.type in POSSESSION_EVENTS:
        taken = _num(payload.get("area_ha"), 0.0) or float(state.area_notified_ha or 0)
        state.area_acquired_ha = taken
        state.possession_pct = 100

    elif event.type == "FAMILY_ENUMERATED":
        count = _int(payload.get("count"), 1) or 1
        state.families_affected = int(state.families_affected or 0) + count
        if payload.get("displaced"):
            displaced = _int(payload.get("displaced_count"), count) or count
            state.families_displaced = int(state.families_displaced or 0) + displaced

    elif event.type == REVERSAL_EVENT and reversal_effects:
        _apply_reversal(db, case, event, state)

    db.add(state)
    db.flush()
    return state


def update_risk_score(db: Session, case_id: uuid.UUID) -> float:
    """Risk = the most-elapsed *running* clock on the case, 0–100. A breached or lapsed
    clock pins the case at 100 — there is no worse position than being in default. A
    clock suspended by a court order scores nothing: see RISK_CLOCK_STATUSES."""
    state = db.get(CaseState, case_id)
    if state is None:
        return 0.0
    rows = db.scalars(select(Clock).where(Clock.case_id == case_id)).all()
    score = 0.0
    for row in rows:
        if row.status in BREACHED_STATUSES:
            score = 100.0
            break
        if row.status in RISK_CLOCK_STATUSES and row.elapsed_pct is not None:
            score = max(score, float(row.elapsed_pct))
    state.risk_score = round(score, 2)
    db.add(state)
    db.flush()
    return state.risk_score


def risk_drivers(db: Session, case_id: uuid.UUID, today: date) -> list[dict]:
    """What is actually driving the score — the clocks, named, with their sections.

    `weight` is what the row contributes to `risk_score`, not how far its clock has run.
    The two differ on a suspended clock: its elapsed fraction keeps climbing while the
    stay is on (the due date only moves when the court vacates it), but it scores
    nothing (RISK_CLOCK_STATUSES), so reporting the fraction as the weight put a 100
    beside a score of 0 and made the drivers panel contradict the number above it. The
    row stays — the Collector must still see the stayed clock — carrying weight 0, the
    real elapsed fraction as `elapsed_pct`, and `counts_towards_score: false` to say why.
    """
    rows = db.scalars(
        select(Clock)
        .where(Clock.case_id == case_id)
        .order_by(Clock.elapsed_pct.desc().nulls_last())
    ).all()
    drivers: list[dict] = []
    for row in rows:
        if row.status not in OPEN_CLOCK_STATUSES + BREACHED_STATUSES:
            continue
        days_left = (row.due_date - today).days if row.due_date else None
        elapsed = float(row.elapsed_pct) if row.elapsed_pct is not None else None
        counts = row.status in RISK_CLOCK_STATUSES + BREACHED_STATUSES
        drivers.append(
            {
                "clock_id": row.clock_id,
                "label": f"{row.clock_id} ({row.basis})" if row.basis else row.clock_id,
                "detail": row.consequence,
                "basis": row.basis,
                "status": row.status,
                "due_date": row.due_date.isoformat() if row.due_date else None,
                "days_left": days_left,
                "weight": (elapsed if counts else 0.0),
                "elapsed_pct": elapsed,
                "counts_towards_score": counts,
            }
        )
    return drivers


def rebuild_case(db: Session, case_id: uuid.UUID, today: date | None = None) -> CaseState:
    """Throw the projection away and replay the ledger (Docs/Backend.md §8).

    The rule-set decides the stage, exactly as it did on append; this never re-validates
    the events — they are already in the chain, and replay must be able to reproduce
    history recorded under any earlier reading of the rules.

    An event an EVENT_REVERSED has withdrawn is skipped rather than folded in and taken
    back out, so the replay lands on the same figures the incremental fold does. Only
    *non-transition* events are skipped: a reversed transition, and any system
    consequence (a s.19(7) rescission, a s.25 lapse), replays regardless. Reversing a
    transition therefore does not un-lapse or otherwise rewind a case's stage — that
    reinstatement flow is not built (Docs/mvp-status.md); the marker records the
    correction in the ledger and the figures follow it, the stage does not.
    """
    from app.domain.rules.clocks import evaluate
    from app.domain.rules.engine import initial_stage, resolve_ruleset

    case = db.get(Case, case_id)
    if case is None:
        raise ValueError(f"case {case_id} not found")
    rs = resolve_ruleset(case)

    state = ensure_case_state(db, case, initial_stage(rs))
    state.stage = initial_stage(rs)
    state.as_of_seq = None
    state.area_notified_ha = 0
    state.area_acquired_ha = 0
    state.comp_assessed_paise = 0
    state.comp_paid_paise = 0
    state.families_affected = 0
    state.families_displaced = 0
    state.possession_pct = 0
    state.risk_score = 0
    db.add(state)
    db.flush()

    events = db.scalars(
        select(Event).where(Event.case_id == case_id).order_by(Event.seq.asc())
    ).all()
    withdrawn = reversed_event_ids(db, case_id)
    for event in events:
        spec = rs.transitions.get(event.type)
        if (
            spec is None
            and event.id in withdrawn
            and not (event.payload or {}).get("system")
        ):
            continue
        apply_event(
            db,
            case,
            event,
            spec.to_stage if spec else None,
            initial_stage(rs),
            reversal_effects=False,
        )

    evaluate(db, case, today or ist_today(), rs)
    return db.get(CaseState, case_id)
