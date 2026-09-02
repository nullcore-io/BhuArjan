"""Cases and the ledger — Docs/APIs.md §3.3 and §3.4.

POST  /cases                      {project_id, district_id, case_no?}
GET   /cases/{id}                 -> case + case_state + clocks[] + last 20 events
GET   /cases/{id}/allowed-events  -> [{type, section, requires[], guard_status}]
GET   /cases/{id}/events?type=&cursor=
POST  /cases/{id}/events          the core write (Idempotency-Key required)
GET   /cases/{id}/clocks          -> [{clock_id, basis, consequence, start_date, due_date,
                                       status, elapsed_pct, extendable}]
GET   /cases/{id}/integrity       -> {verified, checked_at, head_hash}
GET   /cases/{id}/risk            -> {score, drivers[]}

Clock evaluation on read. The clock reads (`GET /cases/{id}`, `/clocks`, `/risk`) run
the engine as of the effective date before answering. That is what Docs/Backend.md §9
asks for in demo mode — moving `X-Demo-Date` forward must make the s.19(7) rescission
actually happen, not merely be predicted — and it keeps the page honest when the hourly
sweep has not run yet. In production the same code path is driven by the scheduler.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_effective_today
from app.core.problems import Problem, not_found
from app.domain.dashboards.scope import _as_uuid, require_case, scoped_case_ids
from app.models import Case, CaseState, Event, OrgUnit, Project, User

router = APIRouter()

CREATE_ROLES = {"LAO", "CALA", "COLLECTOR", "ADMIN"}
APPEND_ROLES = {"LAO", "CALA", "COLLECTOR", "STATE_REVENUE", "ADMIN"}
# s.19(7)/s.25 provisos: an extension is the appropriate Government's to grant.
EXTENSION_ROLES = {"COLLECTOR", "STATE_REVENUE", "ADMIN"}
EXTENSION_EVENT = "EXTENSION_GRANTED"
# Docs/APIs.md §3.4: EVENT_REVERSED is "Collector or above". It is the only way to
# correct the ledger (Docs/rules.md C1) — including on a case that has already lapsed —
# so it is not an LAO's to record against their own entries.
REVERSAL_ROLES = {"COLLECTOR", "STATE_REVENUE", "ADMIN"}
REVERSAL_EVENT = "EVENT_REVERSED"
# Event types the append endpoint gates above APPEND_ROLES.
ELEVATED_APPEND_ROLES = {
    EXTENSION_EVENT: EXTENSION_ROLES,
    REVERSAL_EVENT: REVERSAL_ROLES,
}

RECENT_EVENTS = 20
DEFAULT_LIMIT = 50
MAX_LIMIT = 500


class CaseIn(BaseModel):
    project_id: str
    district_id: str | None = None
    case_no: str | None = None


class EventIn(BaseModel):
    type: str
    occurred_at: date
    document_id: str | None = None
    no_document_reason: str | None = None
    payload: dict = Field(default_factory=dict)


# --- serialisation -----------------------------------------------------------------


def _state_dict(state: CaseState | None) -> dict:
    if state is None:
        return {
            "stage": "PROPOSED",
            "as_of_seq": None,
            "area_notified_ha": 0.0,
            "area_acquired_ha": 0.0,
            "comp_assessed_paise": 0,
            "comp_paid_paise": 0,
            "comp_assessed": 0,
            "comp_paid": 0,
            "families_affected": 0,
            "families_displaced": 0,
            "possession_pct": 0.0,
            "risk_score": None,
            "updated_at": None,
        }
    assessed = int(state.comp_assessed_paise or 0)
    paid = int(state.comp_paid_paise or 0)
    return {
        "stage": state.stage,
        "as_of_seq": state.as_of_seq,
        "area_notified_ha": float(state.area_notified_ha or 0),
        "area_acquired_ha": float(state.area_acquired_ha or 0),
        "comp_assessed_paise": assessed,
        "comp_paid_paise": paid,
        # Docs/Backend.md §2 names these without the unit; both spellings come off the
        # one stored figure so they can never disagree.
        "comp_assessed": assessed,
        "comp_paid": paid,
        "families_affected": int(state.families_affected or 0),
        "families_displaced": int(state.families_displaced or 0),
        "possession_pct": float(state.possession_pct or 0),
        "risk_score": float(state.risk_score) if state.risk_score is not None else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


def _event_dict(event: Event, actor_name: str | None = None) -> dict:
    from app.domain.events.hash import to_hex

    return {
        "seq": event.seq,
        "id": str(event.id),
        "case_id": str(event.case_id),
        "type": event.type,
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "recorded_at": event.recorded_at.isoformat() if event.recorded_at else None,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "actor_name": actor_name,
        "actor": actor_name,
        "payload": event.payload or {},
        "document_id": str(event.document_id) if event.document_id else None,
        "prev_hash": to_hex(event.prev_hash),
        "hash": to_hex(event.hash),
    }


def _actor_names(db: Session, events: list[Event]) -> dict[uuid.UUID, str]:
    ids = {e.actor_id for e in events if e.actor_id}
    if not ids:
        return {}
    return {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids))).all()}


def _evaluate(db: Session, case: Case, today: date) -> None:
    """Bring the case's clocks up to `today`, committing anything that moved."""
    from app.domain.alerts.service import evaluate_case_clocks

    try:
        evaluate_case_clocks(db, case, today)
        # Always commit: an evaluation can raise an alert or move the risk score
        # without any clock row changing status, and dropping that would make the
        # alert centre disagree with the case page.
        db.commit()
    except Exception:
        db.rollback()
        raise


# --- endpoints ---------------------------------------------------------------------


@router.post("/cases", status_code=201)
def create_case(
    body: CaseIn,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Open an acquisition proceeding under a project. The case inherits the
    project's statute track and its pinned rule-set version."""
    from app.domain.cases.projections import ensure_case_state
    from app.domain.rules.engine import initial_stage, resolve_ruleset

    if not user.has_role(*CREATE_ROLES):
        raise not_found()

    project_id = _as_uuid(body.project_id)
    project = db.get(Project, project_id) if project_id else None
    if project is None:
        raise Problem("validation_error", "Validation error", 422, "unknown project_id")

    district_id = None
    if body.district_id:
        district_id = _as_uuid(body.district_id)
        if district_id is None or db.get(OrgUnit, district_id) is None:
            raise Problem(
                "validation_error", "Validation error", 422,
                "district_id is not a known org unit",
            )

    case = Case(
        project_id=project.id,
        district_id=district_id,
        case_no=(body.case_no or None),
        statute_track=project.statute_track,
        ruleset_version=project.ruleset_version,
    )
    db.add(case)
    db.flush()
    rs = resolve_ruleset(case)
    ensure_case_state(db, case, initial_stage(rs))
    db.commit()
    db.refresh(case)

    return {
        "id": str(case.id),
        "case_no": case.case_no,
        "project_id": str(case.project_id),
        "district_id": str(case.district_id) if case.district_id else None,
        "statute_track": case.statute_track,
        "ruleset_version": case.ruleset_version,
        "stage": initial_stage(rs),
        "created_at": case.created_at.isoformat() if case.created_at else None,
    }


@router.get("/cases")
def list_cases(
    project_id: str | None = None,
    stage: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """The case register, scoped to the caller's jurisdiction."""
    allowed = scoped_case_ids(db, user)
    q = select(Case)
    if allowed is not None:
        if not allowed:
            return {"items": [], "cases": [], "total": 0}
        q = q.where(Case.id.in_(allowed))
    if project_id:
        pid = _as_uuid(project_id)
        if pid is None:
            raise not_found()
        q = q.where(Case.project_id == pid)

    cases = db.scalars(q.order_by(Case.created_at.asc()).limit(limit)).all()
    states = {
        s.case_id: s
        for s in db.scalars(
            select(CaseState).where(
                CaseState.case_id.in_([c.id for c in cases] or [uuid.UUID(int=0)])
            )
        ).all()
    }
    items = []
    for c in cases:
        state = states.get(c.id)
        if stage and (state.stage if state else "PROPOSED") != stage.upper():
            continue
        items.append(
            {
                "id": str(c.id),
                "case_no": c.case_no,
                "project_id": str(c.project_id),
                "district_id": str(c.district_id) if c.district_id else None,
                "statute_track": c.statute_track,
                "ruleset_version": c.ruleset_version,
                "stage": state.stage if state else "PROPOSED",
                "risk_score": (
                    float(state.risk_score)
                    if state and state.risk_score is not None
                    else None
                ),
            }
        )
    return {"items": items, "cases": items, "total": len(items)}


@router.get("/cases/{case_id}")
def get_case(
    case_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.domain.rules.clocks import clock_rows, clock_view

    case = require_case(db, case_id, user)
    today = get_effective_today(request)
    _evaluate(db, case, today)

    project = db.get(Project, case.project_id)
    district = db.get(OrgUnit, case.district_id) if case.district_id else None
    state = db.get(CaseState, case.id)
    events = db.scalars(
        select(Event)
        .where(Event.case_id == case.id)
        .order_by(Event.seq.desc())
        .limit(RECENT_EVENTS)
    ).all()
    names = _actor_names(db, list(events))
    state_dict = _state_dict(state)

    return {
        "id": str(case.id),
        "case_no": case.case_no,
        "project_id": str(case.project_id),
        "project_name": project.name if project else None,
        "project": (
            {"id": str(project.id), "name": project.name, "sector": project.sector}
            if project
            else None
        ),
        "district_id": str(case.district_id) if case.district_id else None,
        "district_name": district.name if district else None,
        "statute_track": case.statute_track,
        "ruleset_version": case.ruleset_version,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "stage": state_dict["stage"],
        "risk_score": state_dict["risk_score"],
        "case_state": state_dict,
        "clocks": [clock_view(row) for row in clock_rows(db, case.id)],
        "events": [_event_dict(e, names.get(e.actor_id)) for e in events],
        "as_of_date": today.isoformat(),
    }


@router.get("/cases/{case_id}/allowed-events")
def get_allowed_events(
    case_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.domain.rules.engine import allowed_events, current_stage, resolve_ruleset

    case = require_case(db, case_id, user)
    rs = resolve_ruleset(case)
    stage = current_stage(db, case, rs)
    items = allowed_events(db, case, rs, stage)
    return {
        "items": items,
        "allowed_events": items,
        "stage": stage,
        "ruleset": f"{rs.track}@{rs.version}",
    }


@router.get("/cases/{case_id}/events")
def list_events(
    case_id: str,
    type: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Newest first. `cursor` is the `seq` of the oldest row already returned, so
    paging walks backwards through the ledger (Docs/APIs.md §1)."""
    case = require_case(db, case_id, user)

    q = select(Event).where(Event.case_id == case.id)
    if type:
        q = q.where(Event.type == type.strip().upper())
    total = int(db.scalar(select(func.count()).select_from(q.subquery())) or 0)
    if cursor:
        try:
            q = q.where(Event.seq < int(cursor))
        except (TypeError, ValueError):
            raise Problem("validation_error", "Validation error", 422, "malformed cursor")

    rows = db.scalars(q.order_by(Event.seq.desc()).limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = list(rows[:limit])
    names = _actor_names(db, rows)
    items = [_event_dict(e, names.get(e.actor_id)) for e in rows]
    return {
        "items": items,
        "events": items,
        "total": total,
        "next_cursor": str(rows[-1].seq) if has_more and rows else None,
    }


@router.post("/cases/{case_id}/events", status_code=201)
def append_case_event(
    case_id: str,
    body: EventIn,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    if_match: str | None = Header(None, alias="If-Match"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """The core write. Everything statutory about a case enters here and nowhere else."""
    from app.domain.events.service import append_event

    case = require_case(db, case_id, user)
    event_type = (body.type or "").strip().upper()

    # Idempotency-Key is required (Docs/APIs.md §1): without it a retried request
    # would append a second statutory event.
    if not idempotency_key or not idempotency_key.strip():
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            "Idempotency-Key header is required on event append",
            errors=[{"field": "Idempotency-Key", "message": "missing"}],
        )

    required_roles = ELEVATED_APPEND_ROLES.get(event_type, APPEND_ROLES)
    if not user.has_role(*required_roles):
        raise not_found()

    parsed_if_match = None
    if if_match not in (None, "", "*"):
        try:
            parsed_if_match = int(str(if_match).strip().strip('"'))
        except (TypeError, ValueError):
            raise Problem(
                "validation_error", "Validation error", 422,
                "If-Match must be the integer case_state.as_of_seq",
            )

    document_id = None
    if body.document_id:
        document_id = _as_uuid(body.document_id)
        if document_id is None:
            raise Problem(
                "validation_error", "Validation error", 422, "document_id is not a uuid"
            )

    payload = dict(body.payload or {})
    if body.no_document_reason:
        # Recording a statutory event without its document is a Collector-level act
        # (Docs/rules.md C1); an LAO must upload the paper.
        if not user.has_role("COLLECTOR", "STATE_REVENUE", "ADMIN"):
            raise Problem(
                "document_required",
                "Document required",
                422,
                "Only a Collector-level role may record a statutory event without "
                "its document; upload the document instead",
            )
        # Docs/APIs.md §3.4 puts it beside the payload on the wire; the ledger keeps
        # it inside the payload so it is inside the hash chain.
        payload["no_document_reason"] = body.no_document_reason

    today = get_effective_today(request)
    try:
        result = append_event(
            db,
            case,
            event_type,
            body.occurred_at,
            uuid.UUID(user.id),
            payload,
            document_id=document_id,
            idempotency_key=idempotency_key.strip(),
            if_match=parsed_if_match,
            today=today,
        )
    except Problem:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    # The confirm step of the record-event flow: committing the event is what turns a
    # proposed extraction into a confirmed one (Docs/rules.md C4).
    if document_id is not None and not result.duplicate:
        from app.models import Document

        doc = db.get(Document, document_id)
        if doc is not None and doc.extraction_status == "proposed":
            doc.extraction_status = "confirmed"
    db.commit()

    if result.duplicate:
        response.headers["Idempotent-Replay"] = "true"
    return {
        "seq": result.seq,
        "id": str(result.id),
        "hash": result.hash,
        "prev_hash": result.prev_hash,
        "stage": result.stage,
        "clocks_changed": result.clocks_changed,
        "duplicate": result.duplicate,
    }


@router.get("/cases/{case_id}/clocks")
def get_clocks(
    case_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.domain.rules.clocks import clock_rows, clock_view

    case = require_case(db, case_id, user)
    today = get_effective_today(request)
    _evaluate(db, case, today)
    items = [clock_view(row) for row in clock_rows(db, case.id)]
    return {"items": items, "clocks": items, "as_of_date": today.isoformat()}


@router.get("/cases/{case_id}/integrity")
def get_integrity(
    case_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Recompute the whole chain from the stored rows (Docs/rules.md C1). A `false`
    here means a row was changed outside the ledger — say so plainly."""
    from app.domain.events.service import verify_case_chain

    case = require_case(db, case_id, user)
    result = verify_case_chain(db, case.id)
    return {
        "case_id": str(case.id),
        "verified": result["verified"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "head_hash": result["head_hash"],
        "events_checked": result["events_checked"],
        "first_bad_seq": result["first_bad_seq"],
        "detail": result["reason"]
            or f"{result['events_checked']} events verified against the SHA-256 chain",
    }


@router.get("/cases/{case_id}/risk")
def get_risk(
    case_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.domain.cases.projections import risk_drivers

    case = require_case(db, case_id, user)
    today = get_effective_today(request)
    _evaluate(db, case, today)
    state = db.get(CaseState, case.id)
    drivers = risk_drivers(db, case.id, today)
    return {
        "case_id": str(case.id),
        "score": float(state.risk_score) if state and state.risk_score is not None else 0.0,
        "drivers": drivers,
        "as_of_seq": state.as_of_seq if state else None,
        "as_of_date": today.isoformat(),
    }


@router.post("/cases/{case_id}/rebuild")
def rebuild_case_endpoint(
    case_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Throw the projection away and replay the ledger (Docs/Backend.md §8). The
    ledger is untouched; only `case_state` and `clocks` are recomputed."""
    from app.domain.cases.projections import rebuild_case

    if not user.has_role("COLLECTOR", "STATE_REVENUE", "MINISTRY", "ADMIN"):
        raise not_found()
    case = require_case(db, case_id, user)
    today = get_effective_today(request)
    state = rebuild_case(db, case.id, today)
    db.commit()
    return {"case_id": str(case.id), "case_state": _state_dict(state)}
