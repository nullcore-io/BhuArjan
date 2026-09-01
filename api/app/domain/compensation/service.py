"""First Schedule compensation (Docs/Backend.md §7, Docs/rules.md B4).

Per parcel/owner line:

    T        = MV x F + A                    market value x First Schedule factor
                                             plus s.29 value of attached assets
    solatium = 100% of T                     s.30(1)
    I        = MV x 12% p.a. simple, from the s.11 / 3A notification date to
               min(award date, possession date, today)          s.30(3)
    total    = T + solatium + I

All money is integer paise; arithmetic runs in Decimal and rounds half-up once, at
the end of each component, so the lines always sum to the stored totals.

The ledger is written only through `app.domain.events.service.append_event`:
`COMPENSATION_ASSESSED` on assess, `PAYMENT_MADE` per payment, and
`COMPENSATION_PAID_FULL` automatically when outstanding reaches zero.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.models import Case, CompensationLine, Event, Parcel

INTEREST_RATE = Decimal("0.12")  # s.30(3), 12% per annum simple
DAYS_PER_YEAR = Decimal("365")

# The notification that starts the interest clock, per track.
INTEREST_START_EVENTS = ("PRELIM_NOTIFICATION_S11", "NOTIFICATION_3A")
# Interest stops at the award or at possession, whichever comes first.
AWARD_EVENTS = ("AWARD_S23", "AWARD_3G")
POSSESSION_EVENTS = ("POSSESSION_TAKEN_S38", "POSSESSION_3E")


def _paise(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- pure computation (unit-tested by scripts_smoke_b2.py) -------------------------


def compute_line(
    market_value_paise: int,
    factor: float | Decimal | str,
    assets_paise: int,
    interest_from: date | None = None,
    interest_to: date | None = None,
) -> dict:
    """One award line. Pure — no DB, no clock, fully determined by its arguments."""
    mv = Decimal(int(market_value_paise))
    f = Decimal(str(factor))
    a = Decimal(int(assets_paise))

    base = _paise(mv * f) + int(a)  # T = MV x F + A
    solatium = base  # 100% of T, s.30(1)

    interest_days = 0
    if interest_from and interest_to:
        interest_days = max(0, (interest_to - interest_from).days)
    interest = _paise(mv * INTEREST_RATE * Decimal(interest_days) / DAYS_PER_YEAR)

    return {
        "market_value_paise": int(mv),
        "factor": float(f),
        "assets_paise": int(a),
        "base_paise": base,
        "solatium_paise": solatium,
        "interest_paise": interest,
        "interest_days": interest_days,
        "total_paise": base + solatium + interest,
    }


# --- interest window from the ledger ----------------------------------------------


def _first_event_date(db: Session, case_id: uuid.UUID, types: tuple[str, ...]) -> date | None:
    return db.scalar(
        select(Event.occurred_at)
        .where(Event.case_id == case_id, Event.type.in_(types))
        .order_by(Event.occurred_at.asc(), Event.seq.asc())
        .limit(1)
    )


def interest_window(db: Session, case: Case, today: date) -> tuple[date | None, date | None]:
    """(start, end) for s.30(3) interest: notification date -> min(award, possession, today)."""
    start = _first_event_date(db, case.id, INTEREST_START_EVENTS)
    if start is None:
        return None, None
    candidates = [today]
    for types in (AWARD_EVENTS, POSSESSION_EVENTS):
        d = _first_event_date(db, case.id, types)
        if d is not None:
            candidates.append(d)
    end = min(candidates)
    if end < start:
        end = start
    return start, end


# --- assessment --------------------------------------------------------------------


def assess(
    db: Session,
    case: Case,
    lines_in: list[dict],
    actor_id: uuid.UUID,
    today: date,
    idempotency_key: str | None = None,
) -> dict:
    """Compute and persist the award lines, then emit COMPENSATION_ASSESSED.

    Re-assessment replaces the previous lines. It is refused once any money has been
    paid against them — that correction is a ledger matter (EVENT_REVERSED), not a
    silent overwrite of a paid award (Docs/rules.md C1).
    """
    from app.domain.events.service import append_event

    if not lines_in:
        raise Problem("validation_error", "Validation error", 422,
                      "at least one compensation line is required")

    existing = db.scalars(
        select(CompensationLine).where(CompensationLine.case_id == case.id)
    ).all()
    if any(int(line.paid_paise or 0) > 0 for line in existing):
        raise Problem(
            "validation_error", "Validation error", 422,
            "compensation already partly paid; reverse the assessment before re-assessing",
        )
    for line in existing:
        db.delete(line)
    db.flush()

    start, end = interest_window(db, case, today)

    rows: list[dict] = []
    assessed_total = 0
    for raw in lines_in:
        parcel_id = raw.get("parcel_id")
        if parcel_id:
            parcel = db.get(Parcel, parcel_id)
            if parcel is None or parcel.case_id != case.id:
                raise Problem("validation_error", "Validation error", 422,
                              f"parcel {parcel_id} does not belong to this case")
        computed = compute_line(
            int(raw.get("market_value_paise") or 0),
            raw.get("factor") if raw.get("factor") is not None else 1,
            int(raw.get("assets_paise") or 0),
            start,
            end,
        )
        row = CompensationLine(
            case_id=case.id,
            parcel_id=parcel_id,
            owner_ref=raw.get("owner_ref"),
            market_value_paise=computed["market_value_paise"],
            mv_method=raw.get("mv_method"),
            factor=computed["factor"],
            assets_paise=computed["assets_paise"],
            base_paise=computed["base_paise"],
            solatium_paise=computed["solatium_paise"],
            interest_paise=computed["interest_paise"],
            total_paise=computed["total_paise"],
            paid_paise=0,
        )
        db.add(row)
        rows.append(computed)
        assessed_total += computed["total_paise"]
    db.flush()

    append_event(
        db, case, "COMPENSATION_ASSESSED", today, actor_id,
        {
            "assessed_total_paise": assessed_total,
            "line_count": len(rows),
            "interest_from": start.isoformat() if start else None,
            "interest_to": end.isoformat() if end else None,
        },
        idempotency_key=idempotency_key,
        today=today,
    )
    return summary(db, case, today)


# --- read model --------------------------------------------------------------------


def _line_dict(line: CompensationLine) -> dict:
    total = int(line.total_paise or 0)
    paid = int(line.paid_paise or 0)
    return {
        "id": str(line.id),
        "parcel_id": str(line.parcel_id) if line.parcel_id else None,
        "owner_ref": line.owner_ref,
        "market_value_paise": int(line.market_value_paise or 0),
        "mv_method": line.mv_method,
        "factor": float(line.factor or 0),
        "assets_paise": int(line.assets_paise or 0),
        "base_paise": int(line.base_paise or 0),
        "solatium_paise": int(line.solatium_paise or 0),
        "interest_paise": int(line.interest_paise or 0),
        "total_paise": total,
        "paid_paise": paid,
        "outstanding_paise": max(0, total - paid),
    }


def summary(db: Session, case: Case, today: date) -> dict:
    lines = db.scalars(
        select(CompensationLine)
        .where(CompensationLine.case_id == case.id)
        .order_by(CompensationLine.created_at.asc(), CompensationLine.id.asc())
    ).all()
    out = [_line_dict(line) for line in lines]
    assessed = sum(line["total_paise"] for line in out)
    paid = sum(line["paid_paise"] for line in out)
    start, end = interest_window(db, case, today)
    payments = db.scalars(
        select(Event)
        .where(Event.case_id == case.id, Event.type == "PAYMENT_MADE")
        .order_by(Event.seq.asc())
    ).all()
    return {
        "case_id": str(case.id),
        "lines": out,
        "assessed_total_paise": assessed,
        "paid_total_paise": paid,
        "outstanding_paise": max(0, assessed - paid),
        "interest_accrued_paise": sum(line["interest_paise"] for line in out),
        "interest_from": start.isoformat() if start else None,
        "interest_to": end.isoformat() if end else None,
        "possession_gate_open": assessed > 0 and paid >= assessed,
        "payments": [
            {
                "seq": p.seq,
                "event_id": str(p.id),
                "occurred_at": p.occurred_at.isoformat(),
                "pfms_ref": (p.payload or {}).get("pfms_ref"),
                "amount_paise": int((p.payload or {}).get("amount_paise") or 0),
                "payee_ref": (p.payload or {}).get("payee_ref"),
                "mode": (p.payload or {}).get("mode"),
            }
            for p in payments
        ],
    }


# --- payments ----------------------------------------------------------------------


def allocate_payment(
    db: Session,
    case: Case,
    amount_paise: int,
    line_id: uuid.UUID | None = None,
) -> list[dict]:
    """Apply a payment to award lines. A named line takes it directly; otherwise it
    is applied to lines in assessment order until exhausted. Returns the allocation
    so the caller can record it on the event and nothing is applied silently."""
    q = select(CompensationLine).where(CompensationLine.case_id == case.id)
    if line_id is not None:
        q = q.where(CompensationLine.id == line_id)
    lines = db.scalars(
        q.order_by(CompensationLine.created_at.asc(), CompensationLine.id.asc())
    ).all()
    if line_id is not None and not lines:
        raise Problem("not_found", "Not found", 404, "compensation line not found on this case")

    remaining = int(amount_paise)
    allocation: list[dict] = []
    for line in lines:
        if remaining <= 0:
            break
        room = max(0, int(line.total_paise or 0) - int(line.paid_paise or 0))
        if room <= 0:
            continue
        applied = min(room, remaining)
        line.paid_paise = int(line.paid_paise or 0) + applied
        db.add(line)
        remaining -= applied
        allocation.append({"line_id": str(line.id), "applied_paise": applied})
    db.flush()
    if remaining > 0:
        # Never dropped silently: the surplus is reported back on the event payload.
        allocation.append({"line_id": None, "unallocated_paise": remaining})
    return allocation


def record_payment(
    db: Session,
    case: Case,
    actor_id: uuid.UUID,
    today: date,
    *,
    pfms_ref: str,
    amount_paise: int,
    payee_ref: str | None = None,
    line_id: uuid.UUID | None = None,
    mode: str = "PFMS",
    occurred_at: date | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Emit PAYMENT_MADE, apply it to the lines, and close the case out with
    COMPENSATION_PAID_FULL the moment outstanding reaches zero."""
    from app.domain.events.service import append_event

    if int(amount_paise) <= 0:
        raise Problem("validation_error", "Validation error", 422,
                      "amount_paise must be positive")
    when = occurred_at or today
    allocation = allocate_payment(db, case, int(amount_paise), line_id)

    payment = append_event(
        db, case, "PAYMENT_MADE", when, actor_id,
        {
            "pfms_ref": pfms_ref,
            "amount_paise": int(amount_paise),
            "payee_ref": payee_ref,
            "mode": mode,
            "allocation": allocation,
        },
        idempotency_key=idempotency_key,
        today=today,
    )

    result = summary(db, case, today)
    paid_full = None
    already_full = db.scalar(
        select(Event.seq).where(
            Event.case_id == case.id, Event.type == "COMPENSATION_PAID_FULL"
        ).limit(1)
    )
    if (
        result["assessed_total_paise"] > 0
        and result["outstanding_paise"] == 0
        and already_full is None
    ):
        paid_full = append_event(
            db, case, "COMPENSATION_PAID_FULL", when, actor_id,
            {"assessed_total_paise": result["assessed_total_paise"],
             "paid_total_paise": result["paid_total_paise"]},
            today=today,
        )
        result = summary(db, case, today)

    result["payment"] = {
        "seq": payment.seq,
        "event_id": str(payment.id),
        "allocation": allocation,
        "duplicate": bool(getattr(payment, "duplicate", False)),
    }
    result["compensation_paid_full"] = (
        {"seq": paid_full.seq, "event_id": str(paid_full.id)} if paid_full else None
    )
    return result
