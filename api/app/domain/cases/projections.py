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


def apply_event(
    db: Session,
    case: Case,
    event: Event,
    to_stage: str | None = None,
    initial_stage: str = "PROPOSED",
) -> CaseState:
    """Fold one event into `case_state`. Called inside the append transaction."""
    state = ensure_case_state(db, case, initial_stage)
    payload = event.payload or {}

    if to_stage:
        state.stage = to_stage
    state.as_of_seq = event.seq

    if event.type in NOTIFICATION_EVENTS:
        area = _num(payload.get("total_area_ha"))
        if area:
            state.area_notified_ha = area

    elif event.type == "COMPENSATION_ASSESSED":
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
    """What is actually driving the score — the clocks, named, with their sections."""
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
        drivers.append(
            {
                "clock_id": row.clock_id,
                "label": f"{row.clock_id} ({row.basis})" if row.basis else row.clock_id,
                "detail": row.consequence,
                "basis": row.basis,
                "status": row.status,
                "due_date": row.due_date.isoformat() if row.due_date else None,
                "days_left": days_left,
                "weight": float(row.elapsed_pct) if row.elapsed_pct is not None else None,
            }
        )
    return drivers


def rebuild_case(db: Session, case_id: uuid.UUID, today: date | None = None) -> CaseState:
    """Throw the projection away and replay the ledger (Docs/Backend.md §8).

    The rule-set decides the stage, exactly as it did on append; this never re-validates
    the events — they are already in the chain, and replay must be able to reproduce
    history recorded under any earlier reading of the rules.
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
    for event in events:
        spec = rs.transitions.get(event.type)
        apply_event(db, case, event, spec.to_stage if spec else None, initial_stage(rs))

    evaluate(db, case, today or ist_today(), rs)
    return db.get(CaseState, case_id)
