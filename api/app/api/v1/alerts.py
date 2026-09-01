"""Alert centre — Docs/APIs.md §3.9, Docs/rules.md C2.

GET  /alerts?level=&scope=&state=&district=&case_id=&acknowledged=&limit=&cursor=
POST /alerts/{id}/ack
GET  /alerts/summary   -> {counts: {amber, red, breached, lapsed}, ...}

Alerts are raised by the clock engine (lane B1); this router only reads them, joins
in the case/project names an officer needs to act, and records acknowledgements.
Jurisdiction is resolved server-side — an alert outside the caller's scope is 404,
never 403 (Docs/APIs.md §1).
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_effective_today
from app.core.problems import Problem, not_found
from app.domain.dashboards.scope import case_ids_for_filters, scoped_case_ids
from app.models import Alert, Case, Clock, Project

router = APIRouter()

# The ladder in Docs/rules.md C2 / the rule-set `alerts.escalation` block. Always
# reported in full so a zero is visibly a zero rather than a missing key.
LEVELS = ("amber", "red", "breached", "lapsed")
ACK_DENIED_ROLES = {"AUDITOR", "RB"}
DEFAULT_LIMIT = 50
MAX_LIMIT = 500


# --- scoping -----------------------------------------------------------------------


def _restrict(q, case_ids: list[uuid.UUID] | None, column):
    """`None` means unrestricted; an empty list means 'nothing in scope'."""
    if case_ids is None:
        return q
    if not case_ids:
        return q.where(column.in_([uuid.UUID(int=0)]))
    return q.where(column.in_(case_ids))


def _resolve_scope(
    db: Session,
    user: CurrentUser,
    *,
    scope: str | None,
    state: str | None,
    district: str | None,
    case_id: str | None,
) -> tuple[list[uuid.UUID] | None, dict]:
    """Caller jurisdiction narrowed by the query filters.

    `scope` is the loose parameter from Docs/APIs.md §3.9: it is tried as a district
    first, then as a state code, and the response reports which reading matched so the
    caller is never guessing what they filtered by.
    """
    base = scoped_case_ids(db, user)
    applied: dict = {}

    if case_id:
        try:
            cid = uuid.UUID(str(case_id))
        except (ValueError, TypeError):
            raise not_found()
        if base is not None and cid not in base:
            raise not_found()
        return [cid], {"case_id": str(cid)}

    if scope and not (state or district):
        ids = case_ids_for_filters(db, base, district=scope)
        if ids:
            return ids, {"scope": scope, "scope_matched": "district"}
        ids = case_ids_for_filters(db, base, state=scope)
        return ids, {"scope": scope, "scope_matched": "state" if ids else "none"}

    if state or district:
        applied = {k: v for k, v in (("state", state), ("district", district)) if v}
        return case_ids_for_filters(db, base, state=state, district=district), applied

    return base, applied


# --- serialisation -----------------------------------------------------------------


def _cursor_encode(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode()


def _cursor_decode(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        return max(0, int(raw.split(":", 1)[1]))
    except Exception:
        raise Problem("validation_error", "Validation error", 422, "malformed cursor")


def _alert_dict(alert: Alert, case: Case, project: Project, clock: Clock | None,
                today) -> dict:
    due = clock.due_date if clock else None
    raised = alert.raised_at
    return {
        "id": str(alert.id),
        "case_id": str(alert.case_id),
        "case_no": case.case_no,
        "project_id": str(project.id),
        "project": project.name,
        "project_name": project.name,
        "state_code": project.state_code,
        "statute_track": case.statute_track,
        "clock_id": alert.clock_id,
        "level": alert.level,
        "basis": clock.basis if clock else None,
        "consequence": clock.consequence if clock else None,
        "clock_status": clock.status if clock else None,
        "start_date": clock.start_date.isoformat() if clock and clock.start_date else None,
        "due_date": due.isoformat() if due else None,
        "days_left": (due - today).days if due else None,
        "raised_at": raised.isoformat() if raised else None,
        "age_days": (datetime.now(timezone.utc) - raised).days if raised else None,
        "escalated_to_role": alert.escalated_to_role,
        "acknowledged_by": str(alert.acknowledged_by) if alert.acknowledged_by else None,
        "acknowledged_at": (
            alert.acknowledged_at.isoformat() if alert.acknowledged_at else None
        ),
        "acknowledged": alert.acknowledged_at is not None,
    }


# --- endpoints ---------------------------------------------------------------------


@router.get("/alerts")
def list_alerts(
    request: Request,
    level: str | None = None,
    scope: str | None = None,
    state: str | None = None,
    district: str | None = None,
    case_id: str | None = None,
    acknowledged: bool | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Scoped alert list, joined with the case and project an officer would open.

    Sorted by days-to-due ascending (Docs/Frontend.md §5): the clock closest to its
    statutory deadline is the one that needs work first; alerts with no clock row fall
    to the end, newest first.
    """
    today = get_effective_today(request)
    case_ids, applied = _resolve_scope(
        db, user, scope=scope, state=state, district=district, case_id=case_id
    )
    offset = _cursor_decode(cursor)

    q = (
        select(Alert, Case, Project, Clock)
        .join(Case, Case.id == Alert.case_id)
        .join(Project, Project.id == Case.project_id)
        .outerjoin(
            Clock,
            (Clock.case_id == Alert.case_id) & (Clock.clock_id == Alert.clock_id),
        )
    )
    q = _restrict(q, case_ids, Alert.case_id)
    if level:
        q = q.where(func.lower(Alert.level) == level.strip().lower())
    if acknowledged is True:
        q = q.where(Alert.acknowledged_at.isnot(None))
    elif acknowledged is False:
        q = q.where(Alert.acknowledged_at.is_(None))

    total = db.scalar(
        select(func.count()).select_from(q.subquery())
    ) or 0

    rows = db.execute(
        q.order_by(
            Clock.due_date.asc().nulls_last(),
            Alert.raised_at.desc(),
        ).offset(offset).limit(limit)
    ).all()

    items = [_alert_dict(a, c, p, k, today) for a, c, p, k in rows]
    next_cursor = _cursor_encode(offset + limit) if offset + limit < total else None
    return {
        "items": items,
        "alerts": items,  # web client accepts either key (components/case/caseApi.ts)
        "total": total,
        "next_cursor": next_cursor,
        "filters": {"level": level, **applied},
        "as_of_date": today.isoformat(),
    }


@router.get("/alerts/summary")
def alerts_summary(
    request: Request,
    scope: str | None = None,
    state: str | None = None,
    district: str | None = None,
    case_id: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Counts by level for the caller's scope. All four ladder levels are always
    present; any other level the engine has raised is reported alongside rather than
    dropped."""
    today = get_effective_today(request)
    case_ids, applied = _resolve_scope(
        db, user, scope=scope, state=state, district=district, case_id=case_id
    )

    rows = db.execute(
        _restrict(
            select(func.lower(Alert.level), func.count()), case_ids, Alert.case_id
        ).group_by(func.lower(Alert.level))
    ).all()

    counts = {level: 0 for level in LEVELS}
    for lvl, n in rows:
        counts[lvl or "unknown"] = counts.get(lvl or "unknown", 0) + int(n or 0)

    unacknowledged = int(db.scalar(
        _restrict(select(func.count()).select_from(Alert), case_ids, Alert.case_id)
        .where(Alert.acknowledged_at.is_(None))
    ) or 0)

    return {
        "counts": counts,
        "total": sum(counts.values()),
        "unacknowledged": unacknowledged,
        "filters": applied,
        "as_of_date": today.isoformat(),
    }


@router.post("/alerts/{alert_id}/ack")
def acknowledge_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Acknowledge an alert. Acknowledgement is an operational act, not a statutory
    one: it is recorded on the alert row and in `admin_audit`, never in the ledger."""
    from app.models import AdminAudit

    if user.has_role(*ACK_DENIED_ROLES):
        raise not_found()
    try:
        aid = uuid.UUID(str(alert_id))
    except (ValueError, TypeError):
        raise not_found()
    alert = db.get(Alert, aid)
    if alert is None:
        raise not_found()
    allowed = scoped_case_ids(db, user)
    if allowed is not None and alert.case_id not in allowed:
        raise not_found()

    if alert.acknowledged_at is None:
        alert.acknowledged_by = uuid.UUID(user.id)
        alert.acknowledged_at = datetime.now(timezone.utc)
        db.add(alert)
        db.add(AdminAudit(
            user_id=uuid.UUID(user.id),
            action="ALERT_ACKNOWLEDGED",
            target=str(alert.id),
            meta={"case_id": str(alert.case_id), "clock_id": alert.clock_id,
                  "level": alert.level},
        ))
        db.commit()
        db.refresh(alert)

    return {
        "id": str(alert.id),
        "case_id": str(alert.case_id),
        "clock_id": alert.clock_id,
        "level": alert.level,
        "acknowledged_by": str(alert.acknowledged_by) if alert.acknowledged_by else None,
        "acknowledged_at": (
            alert.acknowledged_at.isoformat() if alert.acknowledged_at else None
        ),
    }
