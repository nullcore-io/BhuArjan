"""Rule-set evaluation — transitions, preconditions, guards (Docs/rules.md C3).

Nothing here decides *what* the statute says; the YAML in `api/rulesets/` does. This
module only asks the loaded `Ruleset` four questions, in this order:

1. Is `type` a defined `EventType` at all?
2. Is it a **transition** in this rule-set? Then the case must be in one of
   `from_stages`, every event type in `requires[]` must already be in this case's
   ledger, and any `guard` must hold. The case moves to `to_stage`.
3. Otherwise it must appear on the current stage's `on:` list. The stage does not move.
4. A **statutory** event — defined here as any event type that is a transition key in
   the rule-set — needs a `document_id` or an explicit `no_document_reason`
   (Docs/rules.md C1).

Every rejection carries the rule-set reference that produced it, so an officer reading
the error can open the exact YAML stanza (Docs/APIs.md §3.4).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.problems import (
    Problem,
    document_required,
    guard_failed,
    precondition_failed,
    transition_not_allowed,
)
from app.domain.events.types import EVENT_TYPES
from app.domain.rules.loader import ClockSpec, Ruleset, TransitionSpec, get_ruleset
from app.models import Case, CaseState, Clock, Event

GUARD_POSSESSION_PAYMENT = "possession_payment_gate"
URGENCY_EVENT = "URGENCY_S40_INVOKED"
EXTENSION_EVENT = "EXTENSION_GRANTED"
URGENCY_FRACTION = 0.8

# Sections for event types that are preconditions but not transitions, so a
# `precondition_failed` can name the section the officer must satisfy. A rule-set may
# override any of these with its own top-level `sections:` map — code never wins over
# data here.
SECTION_HINTS: dict[str, str] = {
    "SIA_NOTIFIED": "s.4(1)",
    "SIA_PUBLIC_HEARING": "s.5",
    "SIA_REPORT_PUBLISHED": "s.6",
    "EXPERT_GROUP_APPRAISAL": "s.7",
    "GOVT_DECISION_S8": "s.8",
    "SIA_EXEMPTED_S40": "s.40",
    "PRELIM_NOTIFICATION_S11": "s.11",
    "NOTIFICATION_3A": "3A",
    "SURVEY_COMPLETED_S12": "s.12",
    "OBJECTION_RECEIVED": "s.15",
    "OBJECTIONS_DISPOSED": "s.15(2)",
    "RR_SCHEME_DRAFTED_S16": "s.16",
    "RR_SCHEME_APPROVED_S17": "s.17",
    "RR_SCHEME_PUBLISHED_S18": "s.18",
    "COST_DEPOSITED_S19_2": "s.19(2)",
    "DECLARATION_S19": "s.19",
    "DECLARATION_3D": "3D",
    "NOTICE_S21": "s.21",
    "CLAIMS_RECEIVED": "s.21",
    "AWARD_S23": "s.23",
    "AWARD_3G": "3G",
    "RR_AWARD_S31": "s.31",
    "COMPENSATION_ASSESSED": "ss.26–30",
    "PAYMENT_MADE": "s.38(1)",
    "COMPENSATION_PAID_FULL": "s.38(1)",
    "POSSESSION_TAKEN_S38": "s.38",
    "POSSESSION_3E": "3E",
    "URGENCY_S40_INVOKED": "s.40",
    "RR_ENTITLEMENT_DELIVERED": "Second Schedule",
    "REFERENCE_FILED_S64": "s.64",
    "COURT_STAY": "court order",
    "STAY_VACATED": "court order",
    "ARBITRATION_3G5": "3G(5)",
    "LAND_UTILISED": "s.101",
    "LAND_RETURNED_S101": "s.101",
    "CASE_LAPSED": "s.25 / s.19(7)",
    "NOTIFICATION_RESCINDED": "s.19(7) / 3D(3)",
    "EXTENSION_GRANTED": "s.19(7) proviso / s.25 proviso",
}


# --- rule-set access ---------------------------------------------------------------


def resolve_ruleset(case: Case) -> Ruleset:
    """The rule-set version pinned on the case. A missing pin is a hard failure: we
    will not silently evaluate a case against a rule-set it was not filed under."""
    rs = get_ruleset(case.statute_track, case.ruleset_version)
    if rs is None:
        raise Problem(
            "ruleset_unavailable",
            "Rule-set unavailable",
            503,
            f"rule-set {case.statute_track}@{case.ruleset_version} is not loaded; "
            "the case cannot be evaluated against a different version",
        )
    return rs


def initial_stage(rs: Ruleset) -> str:
    for name in rs.stages:
        return name
    return "PROPOSED"


def ruleset_ref(rs: Ruleset, *parts: str) -> str:
    tail = "/".join(p for p in parts if p)
    return f"{rs.track}@{rs.version}/{tail}" if tail else f"{rs.track}@{rs.version}"


def section_for(rs: Ruleset, event_type: str) -> str:
    declared = (rs.raw.get("sections") or {}) if isinstance(rs.raw, dict) else {}
    if event_type in declared:
        return str(declared[event_type])
    spec = rs.transitions.get(event_type)
    if spec is not None and spec.section:
        return spec.section
    return SECTION_HINTS.get(event_type, "")


def is_transition(rs: Ruleset, event_type: str) -> bool:
    return event_type in rs.transitions


def is_statutory(rs: Ruleset, event_type: str) -> bool:
    """A statutory event is one the rule-set treats as a step of the proceeding — a
    transition key, plus EXTENSION_GRANTED, which moves a deadline the Act fixed.
    Operational bookkeeping (PARCEL_ADDED, PAYMENT_MADE, …) is not, so it is never
    blocked for want of a gazette copy."""
    return is_transition(rs, event_type) or event_type == EXTENSION_EVENT


# --- ledger facts ------------------------------------------------------------------


def ledger_types(db: Session, case_id: uuid.UUID) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            select(Event.type).where(Event.case_id == case_id).distinct()
        ).all()
    }


def current_stage(db: Session, case: Case, rs: Ruleset | None = None) -> str:
    state = db.get(CaseState, case.id)
    if state is not None and state.stage:
        return state.stage
    return initial_stage(rs or resolve_ruleset(case))


def _money_from_ledger(db: Session, case_id: uuid.UUID) -> tuple[int, int]:
    """(assessed, paid) straight from event payloads — the projection's fallback."""
    rows = db.execute(
        select(Event.type, Event.payload)
        .where(
            Event.case_id == case_id,
            Event.type.in_(("COMPENSATION_ASSESSED", "PAYMENT_MADE")),
        )
        .order_by(Event.seq.asc())
    ).all()
    assessed = 0
    paid = 0
    for etype, payload in rows:
        payload = payload or {}
        try:
            if etype == "COMPENSATION_ASSESSED":
                assessed = int(float(payload.get("assessed_total_paise") or 0))
            else:
                paid += int(float(payload.get("amount_paise") or 0))
        except (TypeError, ValueError):
            continue
    return assessed, paid


def guard_facts(db: Session, case: Case) -> dict:
    """Everything the shipped guards need, read once."""
    state = db.get(CaseState, case.id)
    if state is not None:
        assessed = int(state.comp_assessed_paise or 0)
        paid = int(state.comp_paid_paise or 0)
    else:
        # No projection row yet (fresh replay): read the ledger rather than report a
        # confident zero into a statutory gate.
        assessed, paid = _money_from_ledger(db, case.id)
    present = ledger_types(db, case.id)
    return {
        "comp_assessed_paise": assessed,
        "comp_paid_paise": paid,
        "urgency_invoked": URGENCY_EVENT in present,
        "event_types": present,
    }


# --- guards ------------------------------------------------------------------------


def evaluate_guard(name: str, facts: dict) -> tuple[bool, str]:
    """Returns (ok, human detail). Unknown guard names fail closed and say so — a
    rule-set typo must never silently open a statutory gate."""
    if name == GUARD_POSSESSION_PAYMENT:
        assessed = int(facts.get("comp_assessed_paise") or 0)
        paid = int(facts.get("comp_paid_paise") or 0)
        # Nothing assessed is not "paid in full": `0 >= 0` would open the s.38 gate on
        # a case where no award has ever been valued. The award under ss.26–30 must
        # exist before the payment it requires can be satisfied.
        if assessed <= 0:
            return False, (
                "no compensation has been assessed on this case (COMPENSATION_ASSESSED "
                "is not in the ledger); s.38 requires the award to be assessed and paid "
                "before possession is taken"
            )
        # A recorded COMPENSATION_PAID_FULL is deliberately *not* accepted on its own:
        # it is a marker the compensation service emits, and it cannot be un-emitted by
        # a later s.64 enhancement, so trusting it would leave the gate latched open
        # against an award that has since grown. The paise decide.
        if paid >= assessed:
            return True, f"compensation paid {paid} of {assessed} paise"
        if facts.get("urgency_invoked") and paid >= URGENCY_FRACTION * assessed:
            return True, (
                f"urgency invoked (s.40) with {paid} of {assessed} paise paid "
                f"(>= {int(URGENCY_FRACTION * 100)}%)"
            )
        pct = round(100.0 * paid / assessed, 2) if assessed else 0.0
        return False, (
            f"compensation paid {paid} paise of {assessed} assessed ({pct}%); "
            "s.38 requires payment in full, or an URGENCY_S40_INVOKED event with "
            f"at least {int(URGENCY_FRACTION * 100)}% paid"
        )
    return False, f"guard '{name}' is not implemented; refusing to assume it holds"


def guard_status(rs: Ruleset, spec: TransitionSpec | None, facts: dict) -> dict | None:
    if spec is None or not spec.guard:
        return None
    ok, detail = evaluate_guard(spec.guard, facts)
    return {
        "guard": spec.guard,
        "ok": ok,
        "status": "ok" if ok else "blocked",
        "reason": None if ok else detail,
        "detail": detail,
        "comp_assessed_paise": int(facts.get("comp_assessed_paise") or 0),
        "comp_paid_paise": int(facts.get("comp_paid_paise") or 0),
        "ruleset_ref": ruleset_ref(rs, "transitions", spec.event_type, "guard"),
    }


# --- extensions --------------------------------------------------------------------


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def clock_spec(rs: Ruleset, clock_id: str) -> ClockSpec | None:
    return next((c for c in rs.clocks if c.id == clock_id), None)


def validate_extension(db: Session, case: Case, rs: Ruleset, payload: dict) -> None:
    """EXTENSION_GRANTED is the one event that moves a statutory deadline, so the
    rule-set — not the officer — decides whether it may (Docs/APIs.md §3.4).

    A clock is extendable only if its spec says so (3D(3) carries no proviso and so no
    `extendable:` stanza); where the stanza demands reasons, reasons must be recorded;
    and an extension may only ever move a deadline *forward* — a mistyped year that
    pushed `new_due_date` into the past used to lapse the case on the spot.
    """
    clock_id = str(payload.get("clock_id") or "").strip()
    spec = clock_spec(rs, clock_id)
    if spec is None:
        raise transition_not_allowed(
            f"EXTENSION_GRANTED must name a clock of this rule-set in payload.clock_id; "
            f"'{clock_id or '(missing)'}' is not one of "
            f"{', '.join(c.id for c in rs.clocks) or 'none'}",
            ruleset_ref(rs, "clocks", clock_id or "clock_id"),
        )
    if not spec.extendable:
        raise transition_not_allowed(
            f"clock {spec.id} ({spec.basis or 'see rule-set'}) is not extendable: the "
            "rule-set declares no `extendable:` stanza for it, so the deadline is a "
            "hard statutory limit",
            ruleset_ref(rs, "clocks", spec.id),
        )
    if spec.extendable.get("reasons_required") and not str(
        payload.get("reasons") or ""
    ).strip():
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            f"clock {spec.id} ({spec.basis or 'see rule-set'}) may be extended only "
            "with the reasons recorded in payload.reasons",
            errors=[{"field": "payload.reasons", "message": "reasons are required"}],
            ruleset_ref=ruleset_ref(rs, "clocks", spec.id, "extendable"),
        )

    new_due = _parse_date(payload.get("new_due_date"))
    if new_due is None:
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            "payload.new_due_date must be an ISO date (YYYY-MM-DD)",
            errors=[
                {
                    "field": "payload.new_due_date",
                    "message": "missing or not a date",
                    "value": payload.get("new_due_date"),
                }
            ],
            ruleset_ref=ruleset_ref(rs, "clocks", spec.id),
        )
    row = db.scalar(
        select(Clock).where(Clock.case_id == case.id, Clock.clock_id == spec.id)
    )
    current_due = row.due_date if row is not None else None
    if current_due is not None and new_due <= current_due:
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            f"new_due_date {new_due.isoformat()} is not later than the current due date "
            f"{current_due.isoformat()} of clock {spec.id}; an extension may only move a "
            "deadline forward",
            errors=[
                {
                    "field": "payload.new_due_date",
                    "message": "must be later than the clock's current due date",
                    "new_due_date": new_due.isoformat(),
                    "current_due_date": current_due.isoformat(),
                    "clock_id": spec.id,
                }
            ],
            ruleset_ref=ruleset_ref(rs, "clocks", spec.id),
        )


# --- the append-time check ---------------------------------------------------------


def validate_append(
    db: Session,
    case: Case,
    rs: Ruleset,
    event_type: str,
    stage: str,
    *,
    document_id: uuid.UUID | None = None,
    payload: dict | None = None,
    system: bool = False,
) -> dict:
    """Validate one candidate append. Returns `{to_stage, transition, statutory}`.

    `system=True` is the clock engine emitting a statutory consequence (s.19(7)
    rescission, s.25 lapse). The statute has already operated at that point; the
    precondition/guard/document checks describe what an *officer* may record, so they
    are bypassed — but `from_stages` is not. A consequence that is not available from
    the case's current stage is refused: dragging an AWARDED case into LAPSED along a
    transition the rule-set declares only `from: [NOTIFIED, DECLARED]` leaves a case
    that no officer can correct. The one exception is a consequence whose `to_stage`
    is the stage the case is already in — the `{emit, then}` cascade's second step,
    which writes the fact into the ledger and moves nothing.
    """
    payload = payload or {}

    if event_type not in EVENT_TYPES:
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            f"'{event_type}' is not a defined event type",
            errors=[{"field": "type", "message": "unknown event type"}],
        )

    spec = rs.transitions.get(event_type)
    # EXTENSION_GRANTED is not a transition, but it moves a statutory deadline, so it
    # is statutory paper like one (Docs/APIs.md §3.4).
    statutory = spec is not None or event_type == EXTENSION_EVENT

    if system:
        if (
            spec is not None
            and spec.from_stages
            and stage not in spec.from_stages
            and spec.to_stage != stage
        ):
            raise transition_not_allowed(
                f"consequence {event_type} is not available from stage {stage}; the "
                f"rule-set allows it from {', '.join(spec.from_stages)}",
                ruleset_ref(rs, "transitions", event_type),
            )
        return {
            "to_stage": spec.to_stage if spec else None,
            "transition": spec,
            "statutory": statutory,
        }

    if spec is not None:
        # (b) a transition: stage, preconditions, guard.
        if spec.from_stages and stage not in spec.from_stages:
            raise transition_not_allowed(
                f"current stage {stage}; {event_type} allowed from "
                f"{', '.join(spec.from_stages)}",
                ruleset_ref(rs, "transitions", event_type),
            )
        if spec.requires:
            present = ledger_types(db, case.id)
            missing = [r for r in spec.requires if r not in present]
            if missing:
                raise precondition_failed(
                    [{"missing": m, "section": section_for(rs, m)} for m in missing],
                    f"{event_type} requires {', '.join(missing)} on this case first",
                )
        if spec.guard:
            ok, detail = evaluate_guard(spec.guard, guard_facts(db, case))
            if not ok:
                facts = guard_facts(db, case)
                raise guard_failed(
                    detail,
                    errors=[
                        {
                            "guard": spec.guard,
                            "comp_paid": facts["comp_paid_paise"],
                            "comp_assessed": facts["comp_assessed_paise"],
                            "comp_paid_paise": facts["comp_paid_paise"],
                            "comp_assessed_paise": facts["comp_assessed_paise"],
                        }
                    ],
                )
    else:
        # (c) not a transition: it must be on the current stage's `on:` list.
        if event_type not in rs.allowed_event_types(stage):
            raise transition_not_allowed(
                f"current stage {stage} does not permit {event_type}; "
                f"permitted here: {', '.join(rs.allowed_event_types(stage)) or 'none'}",
                ruleset_ref(rs, "stages", stage),
            )
        if event_type == EXTENSION_EVENT:
            validate_extension(db, case, rs, payload)

    # (d) statutory events need paper.
    if statutory and document_id is None and not payload.get("no_document_reason"):
        raise document_required(
            f"{event_type} is a statutory step ({section_for(rs, event_type) or 'see rule-set'}); "
            "attach document_id or record no_document_reason"
        )

    return {
        "to_stage": spec.to_stage if spec else None,
        "transition": spec,
        "statutory": statutory,
    }


# --- what may be recorded next -----------------------------------------------------


def allowed_events(
    db: Session, case: Case, ruleset: Ruleset | None = None, stage: str | None = None
) -> list[dict]:
    """Every event type the rule-set permits from the case's current stage, each with
    its section, its unmet preconditions and its guard verdict (Docs/APIs.md §3.3)."""
    rs = ruleset or resolve_ruleset(case)
    stage = stage or current_stage(db, case, rs)
    facts = guard_facts(db, case)
    present: set[str] = facts["event_types"]

    candidates: list[str] = list(rs.allowed_event_types(stage))
    for event_type, spec in rs.transitions.items():
        if stage in spec.from_stages and event_type not in candidates:
            candidates.append(event_type)

    out: list[dict] = []
    seen: set[str] = set()
    for event_type in candidates:
        if event_type in seen or event_type not in EVENT_TYPES:
            continue
        seen.add(event_type)
        spec = rs.transitions.get(event_type)
        requires = [
            {
                "type": r,
                "missing": None if r in present else r,
                "section": section_for(rs, r),
                "satisfied": r in present,
            }
            for r in (spec.requires if spec else [])
        ]
        gs = guard_status(rs, spec, facts)
        out.append(
            {
                "type": event_type,
                "label": event_type.replace("_", " ").title(),
                "section": section_for(rs, event_type),
                "requires": requires,
                "requires_met": all(r["satisfied"] for r in requires),
                "guard_status": gs,
                "guard_ok": True if gs is None else bool(gs["ok"]),
                "is_transition": spec is not None,
                "to_stage": spec.to_stage if spec else stage,
                "document_required": is_statutory(rs, event_type),
                "already_recorded": event_type in present,
                "ruleset_ref": ruleset_ref(
                    rs, "transitions" if spec else "stages", event_type if spec else stage
                ),
            }
        )
    out.sort(key=lambda r: (not r["is_transition"], r["type"]))
    return out


def stage_entry_types(rs: Ruleset, stage: str) -> list[str]:
    """Event types whose transition lands on `stage` — used to date a stage."""
    return [t.event_type for t in rs.transitions.values() if t.to_stage == stage]
