"""Projects — Docs/APIs.md §3.2.

GET  /projects?state=&sector=&statute=&cursor=
POST /projects              {name, sector, requiring_body_id, statute_track, state_code}
GET  /projects/{id}         -> project + KPIs + cases[]

The rule-set version is pinned at creation and inherited by every case under the
project, so a later overlay never rewrites the rules a live acquisition was filed
under (Docs/Backend.md §5).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_effective_today
from app.core.problems import Problem, not_found
from app.domain.dashboards.scope import _as_uuid, expand_org_units, is_national
from app.models import Case, CaseState, Clock, OrgUnit, Project

router = APIRouter()

CREATE_ROLES = {"RB", "MINISTRY", "ADMIN"}
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class ProjectIn(BaseModel):
    name: str
    sector: str | None = None
    requiring_body_id: str | None = None
    statute_track: str = "RFCTLARR_2013"
    state_code: str | None = None
    ruleset_version: str | None = None


# --- scoping -----------------------------------------------------------------------


def visible_project_ids(db: Session, user: CurrentUser) -> list[uuid.UUID] | None:
    """Project ids the caller may read; `None` means unrestricted (national).

    A project is visible when the caller's jurisdiction covers its requiring body or
    any district it has a case in — the same rule the case list uses.
    """
    if is_national(db, user):
        return None
    units = expand_org_units(db, [u for u in (_as_uuid(s) for s in user.scopes) if u])
    if not units:
        return []
    by_body = db.scalars(
        select(Project.id).where(Project.requiring_body_id.in_(units))
    ).all()
    by_case = db.scalars(
        select(Case.project_id).where(Case.district_id.in_(units)).distinct()
    ).all()
    return list({*by_body, *by_case})


def _org_names(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {
        row.id: row.name
        for row in db.scalars(select(OrgUnit).where(OrgUnit.id.in_(ids))).all()
    }


def _project_dict(project: Project, *, body_name: str | None, case_count: int | None) -> dict:
    return {
        "id": str(project.id),
        "name": project.name,
        "sector": project.sector,
        "statute_track": project.statute_track,
        "ruleset_version": project.ruleset_version,
        "state_code": project.state_code,
        "requiring_body_id": (
            str(project.requiring_body_id) if project.requiring_body_id else None
        ),
        "requiring_body_name": body_name,
        "case_count": case_count,
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


# --- endpoints ---------------------------------------------------------------------


@router.get("/projects")
def list_projects(
    state: str | None = None,
    sector: str | None = None,
    statute: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    allowed = visible_project_ids(db, user)
    q = select(Project)
    if allowed is not None:
        if not allowed:
            return {"items": [], "projects": [], "next_cursor": None, "total": 0}
        q = q.where(Project.id.in_(allowed))
    if state:
        q = q.where(func.upper(Project.state_code) == state.strip().upper())
    if sector:
        q = q.where(func.lower(Project.sector) == sector.strip().lower())
    if statute:
        q = q.where(func.upper(Project.statute_track) == statute.strip().upper())

    total = int(db.scalar(select(func.count()).select_from(q.subquery())) or 0)
    offset = _decode_cursor(cursor)
    rows = db.scalars(
        q.order_by(Project.created_at.asc(), Project.id.asc()).offset(offset).limit(limit)
    ).all()

    counts = dict(
        db.execute(
            select(Case.project_id, func.count())
            .where(Case.project_id.in_([p.id for p in rows] or [uuid.UUID(int=0)]))
            .group_by(Case.project_id)
        ).all()
    )
    names = _org_names(db, [p.requiring_body_id for p in rows])
    items = [
        _project_dict(
            p,
            body_name=names.get(p.requiring_body_id),
            case_count=int(counts.get(p.id, 0)),
        )
        for p in rows
    ]
    return {
        "items": items,
        "projects": items,  # the web client accepts either key
        "total": total,
        "next_cursor": str(offset + limit) if offset + limit < total else None,
        "filters": {"state": state, "sector": sector, "statute": statute},
    }


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(cursor))
    except (TypeError, ValueError):
        raise Problem("validation_error", "Validation error", 422, "malformed cursor")


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Register a project. The requiring body raises the proposal; the Ministry
    administers the register (Docs/APIs.md §2)."""
    from app.domain.rules.loader import get_ruleset

    if not user.has_role(*CREATE_ROLES):
        raise not_found()
    name = (body.name or "").strip()
    if not name:
        raise Problem("validation_error", "Validation error", 422, "name is required")

    track = (body.statute_track or "").strip().upper()
    # No version means "whatever is current"; an explicit version is a pin, and an
    # unloaded pin is refused rather than quietly served the newest file.
    ruleset = get_ruleset(track, body.ruleset_version)
    if ruleset is None and body.ruleset_version:
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            f"rule-set {track}@{body.ruleset_version} is not loaded",
            errors=[{"field": "ruleset_version", "message": "unknown rule-set version"}],
        )
    if ruleset is None:
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            f"no rule-set is loaded for statute track '{track}'",
            errors=[{"field": "statute_track", "message": "unknown statute track"}],
        )

    requiring_body_id = None
    if body.requiring_body_id:
        requiring_body_id = _as_uuid(body.requiring_body_id)
        if requiring_body_id is None or db.get(OrgUnit, requiring_body_id) is None:
            raise Problem(
                "validation_error", "Validation error", 422,
                "requiring_body_id is not a known org unit",
            )

    project = Project(
        name=name,
        sector=(body.sector or None),
        requiring_body_id=requiring_body_id,
        statute_track=ruleset.track,
        ruleset_version=ruleset.version,  # pinned at creation
        state_code=(body.state_code or None),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    names = _org_names(db, [project.requiring_body_id])
    return _project_dict(
        project, body_name=names.get(project.requiring_body_id), case_count=0
    )


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Project header, its KPI block summed over its cases, and the case register."""
    from app.domain.dashboards.service import as_of_seq, kpis

    pid = _as_uuid(project_id)
    if pid is None:
        raise not_found()
    project = db.get(Project, pid)
    if project is None:
        raise not_found()
    allowed = visible_project_ids(db, user)
    if allowed is not None and project.id not in allowed:
        raise not_found()

    today: date = get_effective_today(request)
    cases = db.scalars(
        select(Case).where(Case.project_id == pid).order_by(Case.created_at.asc())
    ).all()
    case_ids = [c.id for c in cases]

    states = {
        s.case_id: s
        for s in db.scalars(
            select(CaseState).where(CaseState.case_id.in_(case_ids or [uuid.UUID(int=0)]))
        ).all()
    }
    districts = _org_names(db, [c.district_id for c in cases])
    next_clocks: dict[uuid.UUID, Clock] = {}
    for clock in db.scalars(
        select(Clock)
        .where(
            Clock.case_id.in_(case_ids or [uuid.UUID(int=0)]),
            Clock.status.in_(("running", "extended", "suspended", "breached")),
            Clock.due_date.isnot(None),
        )
        .order_by(Clock.due_date.asc())
    ).all():
        next_clocks.setdefault(clock.case_id, clock)

    case_rows = []
    for c in cases:
        state = states.get(c.id)
        clock = next_clocks.get(c.id)
        case_rows.append(
            {
                "id": str(c.id),
                "case_no": c.case_no,
                "district_id": str(c.district_id) if c.district_id else None,
                "district_name": districts.get(c.district_id),
                "district": districts.get(c.district_id),
                "statute_track": c.statute_track,
                "ruleset_version": c.ruleset_version,
                "stage": state.stage if state else "PROPOSED",
                "risk_score": float(state.risk_score) if state and state.risk_score is not None else None,
                "as_of_seq": state.as_of_seq if state else None,
                "next_clock_id": clock.clock_id if clock else None,
                "next_due_date": clock.due_date.isoformat() if clock and clock.due_date else None,
                "days_left": (clock.due_date - today).days if clock and clock.due_date else None,
            }
        )

    body = _project_dict(
        project,
        body_name=_org_names(db, [project.requiring_body_id]).get(project.requiring_body_id),
        case_count=len(cases),
    )
    body.update(
        {
            "kpis": kpis(db, case_ids, today) if case_ids else kpis(db, [], today),
            "cases": case_rows,
            "as_of_seq": as_of_seq(db, case_ids) if case_ids else 0,
            "as_of_date": today.isoformat(),
        }
    )
    return body
