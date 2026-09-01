"""Compensation and payments — Docs/APIs.md §3.7, Docs/Backend.md §7.

POST /cases/{id}/compensation/assess  {lines:[...]}  -> computed lines, emits COMPENSATION_ASSESSED
GET  /cases/{id}/compensation                        -> lines, totals, outstanding, payments
POST /cases/{id}/payments                            -> emits PAYMENT_MADE (+ COMPENSATION_PAID_FULL)

The arithmetic lives in `app.domain.compensation.service`; this module is transport
only. Every ledger write goes through `app.domain.events.service.append_event` — this
router never touches the `events` table itself.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_effective_today
from app.core.problems import Problem, not_found
from app.domain.dashboards.scope import require_case

router = APIRouter()

ASSESS_ROLES = {"LAO", "CALA", "COLLECTOR", "ADMIN"}
PAY_ROLES = {"LAO", "CALA", "COLLECTOR", "STATE_REVENUE", "ADMIN"}


class AssessLineIn(BaseModel):
    parcel_id: str | None = None
    owner_ref: str | None = None
    market_value_paise: int = 0
    mv_method: str | None = None
    factor: float = 1.0
    assets_paise: int = 0


class AssessIn(BaseModel):
    lines: list[AssessLineIn] = Field(default_factory=list)


class PaymentIn(BaseModel):
    pfms_ref: str
    amount_paise: int
    payee_ref: str | None = None
    line_id: str | None = None
    mode: str = "PFMS"
    occurred_at: date | None = None


def _uuid_or_400(value: str | None, field: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise Problem("validation_error", "Validation error", 422, f"{field} is not a uuid")


def _with_aliases(summary: dict) -> dict:
    """Money keys are `*_paise` on the wire (Docs/APIs.md §1). Docs/APIs.md §3.7 and the
    web client also name the totals without the suffix, so both spellings are emitted
    from the one computed figure — never two independently computed numbers."""
    summary = dict(summary)
    summary["assessed_total"] = summary["assessed_total_paise"]
    summary["paid_total"] = summary["paid_total_paise"]
    summary["outstanding"] = summary["outstanding_paise"]
    summary["interest_accrued"] = summary["interest_accrued_paise"]
    return summary


def _ledger_unavailable(exc: NotImplementedError) -> Problem:
    return Problem(
        "ledger_unavailable", "Ledger unavailable", 503,
        "the event append service is not available in this build; "
        f"compensation cannot be recorded without it ({exc})",
    )


@router.post("/cases/{case_id}/compensation/assess")
def assess_compensation(
    case_id: str,
    body: AssessIn,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Compute T = MV x F + A, solatium = T, s.30(3) interest, and persist the lines."""
    from app.domain.compensation.service import assess

    if not user.has_role(*ASSESS_ROLES):
        raise not_found()
    case = require_case(db, case_id, user)
    today = get_effective_today(request)

    lines = [line.model_dump() for line in body.lines]
    for line in lines:
        _uuid_or_400(line.get("parcel_id"), "parcel_id")

    try:
        result = assess(db, case, lines, uuid.UUID(user.id), today,
                        idempotency_key=idempotency_key)
    except NotImplementedError as exc:
        db.rollback()
        raise _ledger_unavailable(exc)
    except Problem:
        db.rollback()
        raise
    db.commit()
    return _with_aliases(result)


@router.get("/cases/{case_id}/compensation")
def get_compensation(
    case_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.domain.compensation.service import summary

    case = require_case(db, case_id, user)
    return _with_aliases(summary(db, case, get_effective_today(request)))


@router.post("/cases/{case_id}/payments", status_code=201)
def record_payment_endpoint(
    case_id: str,
    body: PaymentIn,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Record a PFMS payment against the award lines. `COMPENSATION_PAID_FULL` is
    emitted automatically the moment outstanding reaches zero (Docs/Backend.md §7)."""
    from app.domain.compensation.service import record_payment

    if not user.has_role(*PAY_ROLES):
        raise not_found()
    case = require_case(db, case_id, user)
    today = get_effective_today(request)
    line_id = _uuid_or_400(body.line_id, "line_id")

    try:
        result = record_payment(
            db, case, uuid.UUID(user.id), today,
            pfms_ref=body.pfms_ref,
            amount_paise=int(body.amount_paise),
            payee_ref=body.payee_ref,
            line_id=line_id,
            mode=body.mode,
            occurred_at=body.occurred_at,
            idempotency_key=idempotency_key,
        )
    except NotImplementedError as exc:
        db.rollback()
        raise _ledger_unavailable(exc)
    except Problem:
        db.rollback()
        raise
    db.commit()
    return _with_aliases(result)
