"""R&R and affected families — Docs/APIs.md §3.8, Docs/final-product.md §5F.

GET  /cases/{id}/families?purpose=&limit=&cursor=   masked by default; purpose + role unlocks (audited)
POST /cases/{id}/families                           {head:{...}, category, displaced, sc_st} -> FAMILY_ENUMERATED
POST /families/{id}/entitlements/{head}/deliver     {evidence_document_id?, delivered_on} -> RR_ENTITLEMENT_DELIVERED
GET  /cases/{id}/rr/summary                         heads x status counts + the s.38 R&R clocks

Transport only: the entitlement schedule, the encryption and the ledger writes all live
in `app.domain.rr.service`. Jurisdiction is resolved by `require_case` on every route,
including the family-addressed one — an out-of-scope family is a 404, never a 403
(Docs/APIs.md §1).

Who may see a name. Docs/rules.md C5 (DPDP Act 2023) allows a decrypt only for a role
with jurisdiction *and* a stated purpose, and requires every such read to be audited.
`PII_ROLES` is deliberately narrow: it does not include ADMIN, because a system
administrator has no statutory business reading an affected family's name, and it does
not include LAO/CALA, MINISTRY, AUDITOR or RB, who work from the masked view. Note that
Docs/APIs.md §2's RBAC table shows State as *masked*; this build follows the module
brief and admits STATE_REVENUE with a purpose — see the R&R notes for the owner to
settle before the finale.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_effective_today
from app.core.problems import Problem, not_found
from app.domain.dashboards.scope import require_case

router = APIRouter()

# Recording an affected family and delivering an entitlement are field acts.
ENUMERATE_ROLES = {"LAO", "CALA", "COLLECTOR", "ADMIN_RR", "ADMIN"}
DELIVER_ROLES = {"LAO", "CALA", "COLLECTOR", "ADMIN_RR", "ADMIN"}
# Roles that may see a name, and only with a purpose (Docs/rules.md C5).
PII_ROLES = {"COLLECTOR", "ADMIN_RR"}  # Docs/APIs.md §2: State sees masked rows

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


class HeadIn(BaseModel):
    name: str
    guardian: str | None = None
    id_ref: str | None = None
    id_ref_last4: str | None = None
    bank_ref: str | None = None
    bank_ref_last4: str | None = None
    village: str | None = None


class FamilyIn(BaseModel):
    head: HeadIn
    category: str | None = None
    displaced: bool = False
    sc_st: bool = False
    occurred_at: date | None = None


class DeliverIn(BaseModel):
    evidence_document_id: str | None = None
    delivered_on: date | None = None
    note: str | None = Field(default=None, max_length=500)


def _unlock(user: CurrentUser, purpose: str | None) -> tuple[bool, str]:
    """(may see names, why not). Both conditions must hold; neither implies the other."""
    purpose = (purpose or "").strip()
    if not user.has_role(*PII_ROLES):
        return False, (
            "your role may see the masked register only; names are released to "
            "Collector, Administrator R&R and State Revenue (Docs/rules.md C5)"
        )
    if not purpose:
        return False, (
            "add ?purpose=<why you need the names>; every PII read is recorded "
            "against that purpose (Docs/rules.md C5)"
        )
    return True, ""


@router.get("/cases/{case_id}/families")
def list_families_endpoint(
    case_id: str,
    purpose: str | None = Query(None),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """The affected-family register for a case. Masked unless the caller has both a
    PII role and a purpose; every unlocked read writes an `admin_audit` PII_READ row."""
    from app.domain.rr.service import list_families

    case = require_case(db, case_id, user)
    unlock, reason = _unlock(user, purpose)

    result = list_families(
        db,
        case,
        limit=limit,
        cursor=cursor,
        unlock=unlock,
        purpose=(purpose or "").strip(),
        actor_id=uuid.UUID(user.id),
    )
    result["case_id"] = str(case.id)
    result["case_no"] = case.case_no
    if not unlock:
        result["masked_reason"] = reason
    # The audit rows written above are part of this read and must survive it.
    db.commit()
    return result


@router.post("/cases/{case_id}/families", status_code=201)
def enumerate_family_endpoint(
    case_id: str,
    body: FamilyIn,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Enumerate one affected family: encrypted head-of-family record, Second/Third
    Schedule entitlement map, and `FAMILY_ENUMERATED` on the ledger."""
    from app.domain.rr.service import enumerate_family, family_view

    if not user.has_role(*ENUMERATE_ROLES):
        raise not_found()
    case = require_case(db, case_id, user)
    today = get_effective_today(request)

    try:
        enrolled = enumerate_family(
            db,
            case,
            uuid.UUID(user.id),
            head=body.head.model_dump(),
            category=body.category,
            displaced=body.displaced,
            sc_st=body.sc_st,
            occurred_at=body.occurred_at,
            today=today,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except Problem:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    db.commit()

    if enrolled.duplicate:
        response.headers["Idempotent-Replay"] = "true"
    return {
        **family_view(enrolled.family, enrolled.person),
        "seq": enrolled.seq,
        "stage": enrolled.stage,
        "duplicate": enrolled.duplicate,
    }


@router.post("/families/{family_id}/entitlements/{head}/deliver")
def deliver_entitlement_endpoint(
    family_id: str,
    head: str,
    body: DeliverIn,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Mark one Second/Third Schedule head delivered for one family, with evidence."""
    from app.domain.rr.service import deliver_entitlement, get_family

    if not user.has_role(*DELIVER_ROLES):
        raise not_found()
    family = get_family(db, family_id)
    case = require_case(db, family.case_id, user)
    today = get_effective_today(request)

    try:
        result = deliver_entitlement(
            db,
            case,
            family,
            head,
            uuid.UUID(user.id),
            delivered_on=body.delivered_on,
            evidence_document_id=body.evidence_document_id,
            today=today,
            idempotency_key=(idempotency_key or "").strip() or None,
        )
    except Problem:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    db.commit()
    return result


@router.get("/cases/{case_id}/rr/summary")
def rr_summary_endpoint(
    case_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Heads × status counts for the case and the s.38 R&R clocks. No PII at any role:
    this is the aggregate view Docs/APIs.md §2 gives even to Ministry."""
    from app.domain.rr.service import rr_summary

    case = require_case(db, case_id, user)
    today = get_effective_today(request)

    # Same contract as the case page: bring the clocks up to the effective date before
    # reporting them, so the s.38 R&R rows are honest under the demo clock.
    from app.domain.alerts.service import evaluate_case_clocks

    try:
        evaluate_case_clocks(db, case, today)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return rr_summary(db, case, today)
