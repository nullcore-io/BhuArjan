"""Public status lookup — Docs/APIs.md §3.11, Docs/rules.md C5.

GET /public/status?ulpin=
GET /public/status?state=&district=&village=&survey_no=

No authentication. What comes back is the statutory position of one plot: project,
statute, stage and its date, the next milestone with its due month, area, compensation
assessed vs paid in aggregate, and possession. Never a name, never an owner reference,
never a document, and never an internal id that could be walked — the response carries
no case_id or parcel_id for exactly that reason.

Responses are cached for 5 minutes (Docs/APIs.md §3.11).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_effective_today
from app.core.problems import Problem, not_found
from app.models import Case, CaseState, Clock, Event, Project

router = APIRouter()

CACHE_SECONDS = 300
OPEN_CLOCK_STATUSES = ("running", "extended", "suspended", "breached")


def _stage_date(db: Session, case: Case, stage: str | None) -> str | None:
    """The legal date the case entered its current stage: the `occurred_at` of the
    latest event whose rule-set transition lands on that stage. Falls back to the
    latest event on the case when the rule-set cannot be resolved."""
    types: list[str] = []
    if stage:
        from app.domain.rules.loader import get_ruleset

        rs = get_ruleset(case.statute_track, case.ruleset_version)
        if rs:
            types = [t.event_type for t in rs.transitions.values() if t.to_stage == stage]

    q = select(Event.occurred_at).where(Event.case_id == case.id)
    if types:
        q = q.where(Event.type.in_(types))
    occurred = db.scalar(q.order_by(Event.seq.desc()).limit(1))
    if occurred is None and types:
        occurred = db.scalar(
            select(Event.occurred_at)
            .where(Event.case_id == case.id)
            .order_by(Event.seq.desc())
            .limit(1)
        )
    return occurred.isoformat() if occurred else None


def _next_milestone(db: Session, case: Case, today: date) -> dict:
    """The open clock nearest its due date — what the citizen is actually waiting on."""
    clock = db.scalars(
        select(Clock)
        .where(Clock.case_id == case.id, Clock.status.in_(OPEN_CLOCK_STATUSES))
        .where(Clock.due_date.isnot(None))
        .order_by(Clock.due_date.asc())
        .limit(1)
    ).first()
    if clock is None:
        return {"next_milestone": None, "next_due_month": None,
                "next_milestone_basis": None, "next_milestone_consequence": None}
    return {
        "next_milestone": clock.clock_id,
        "next_due_month": clock.due_date.strftime("%Y-%m") if clock.due_date else None,
        "next_milestone_basis": clock.basis,
        "next_milestone_consequence": clock.consequence,
    }


@router.get("/public/status")
def public_status(
    request: Request,
    response: Response,
    ulpin: str | None = None,
    state: str | None = None,
    district: str | None = None,
    village: str | None = None,
    survey_no: str | None = None,
    db: Session = Depends(get_db),
):
    from app.domain.dashboards.service import kpis
    from app.domain.parcels.service import lookup

    if not (ulpin or (village and survey_no)):
        raise Problem(
            "validation_error", "Validation error", 422,
            "provide ulpin, or village and survey_no (state and district optional)",
        )

    parcel = lookup(db, ulpin=ulpin, state=state, district=district,
                    village=village, survey_no=survey_no)
    if parcel is None:
        raise not_found()

    case = db.get(Case, parcel.case_id)
    if case is None:
        raise not_found()
    project = db.get(Project, case.project_id)
    case_state = db.get(CaseState, case.id)
    today = get_effective_today(request)

    stage = case_state.stage if case_state else None
    figures = kpis(db, [case.id], today)

    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return {
        "project": project.name if project else None,
        "sector": project.sector if project else None,
        "statute": case.statute_track,
        "ruleset_version": case.ruleset_version,
        "stage": stage,
        "stage_date": _stage_date(db, case, stage),
        **_next_milestone(db, case, today),
        "area_ha": float(parcel.area_ha) if parcel.area_ha is not None else None,
        "case_area_ha": figures["area_notified_ha"],
        "comp_assessed_paise": figures["comp_assessed_paise"],
        "comp_paid_paise": figures["comp_paid_paise"],
        "possession": {
            "taken": stage in ("POSSESSED", "CLOSED"),
            "pct": figures["possession_pct"],
            "parcel_status": parcel.status,
        },
        "village": parcel.village_name,
        "survey_no": parcel.survey_no,
        "as_of_seq": case_state.as_of_seq if case_state else None,
        "as_of_date": today.isoformat(),
        "disclaimer": (
            "Statutory position from the acquisition ledger. No personal information "
            "is published here."
        ),
    }
