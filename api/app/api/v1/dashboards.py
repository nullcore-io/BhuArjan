"""Dashboards — Docs/APIs.md §3.10, Docs/rules.md C7.

GET /dashboards/national?sector=&statute=&from=&to=
GET /dashboards/national/explain?kpi=
GET /dashboards/states/{state}            (+ /explain)
GET /dashboards/districts/{district}      (+ /explain)

All three levels return the same shape; only the case set differs — `state` filters on
`project.state_code`, `district` on `case.district_id` (by uuid, LGD code or name).
Every response carries `as_of_seq = max(events.seq)` over the cases in scope, and every
explainable KPI can be exploded back to the contributing event ids.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_effective_today
from app.domain.dashboards.scope import case_ids_for_filters, scoped_case_ids
from app.domain.dashboards.service import EXPLAIN_KPIS, dashboard, explain

router = APIRouter()


def _case_ids(
    db: Session,
    user: CurrentUser,
    *,
    state: str | None = None,
    district: str | None = None,
    sector: str | None = None,
    statute: str | None = None,
):
    """Caller jurisdiction narrowed by the dashboard filters. `None` = unrestricted."""
    base = scoped_case_ids(db, user)
    if not (state or district or sector or statute):
        return base
    return case_ids_for_filters(
        db, base, state=state, district=district, sector=sector, statute=statute
    )


def _clip_series(payload: dict, date_from: str | None, date_to: str | None) -> dict:
    """`from`/`to` clip the monthly series only.

    The KPI tiles are cumulative statutory positions (area notified to date, money
    outstanding today) — clipping them to a window would produce a figure that is not
    a fact about anything. The response says which part of it the window touched
    rather than implying the whole page is filtered.
    """
    if not (date_from or date_to):
        return payload
    lo = (date_from or "")[:7]
    hi = (date_to or "")[:7]
    series = payload["series"]["assessed_vs_paid_monthly"]
    payload["series"]["assessed_vs_paid_monthly"] = [
        row for row in series
        if (not lo or row["month"] >= lo) and (not hi or row["month"] <= hi)
    ]
    payload["filters"]["window_applies_to"] = "series"
    return payload


def _dashboard(
    db: Session,
    user: CurrentUser,
    request: Request,
    *,
    level: str,
    scope_id: str | None = None,
    state: str | None = None,
    district: str | None = None,
    sector: str | None = None,
    statute: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    today = get_effective_today(request)
    case_ids = _case_ids(db, user, state=state, district=district,
                         sector=sector, statute=statute)
    filters = {
        k: v for k, v in (
            ("state", state), ("district", district), ("sector", sector),
            ("statute", statute), ("from", date_from), ("to", date_to),
        ) if v
    }
    payload = dashboard(db, case_ids, today, level=level, scope_id=scope_id,
                        filters=filters)
    return _clip_series(payload, date_from, date_to)


def _explain(
    db: Session,
    user: CurrentUser,
    request: Request,
    kpi: str,
    *,
    state: str | None = None,
    district: str | None = None,
    sector: str | None = None,
    statute: str | None = None,
) -> dict:
    today = get_effective_today(request)
    case_ids = _case_ids(db, user, state=state, district=district,
                         sector=sector, statute=statute)
    return explain(db, case_ids, kpi, today)


# --- national ----------------------------------------------------------------------


@router.get("/dashboards/national")
def national_dashboard(
    request: Request,
    sector: str | None = None,
    statute: str | None = None,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return _dashboard(db, user, request, level="national", sector=sector,
                      statute=statute, date_from=date_from, date_to=date_to)


@router.get("/dashboards/national/explain")
def national_explain(
    request: Request,
    kpi: str = "comp_assessed",
    sector: str | None = None,
    statute: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return _explain(db, user, request, kpi, sector=sector, statute=statute)


# --- states ------------------------------------------------------------------------


@router.get("/dashboards/states/{state}")
def state_dashboard(
    state: str,
    request: Request,
    sector: str | None = None,
    statute: str | None = None,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return _dashboard(db, user, request, level="state", scope_id=state, state=state,
                      sector=sector, statute=statute, date_from=date_from,
                      date_to=date_to)


@router.get("/dashboards/states/{state}/explain")
def state_explain(
    state: str,
    request: Request,
    kpi: str = "comp_assessed",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return _explain(db, user, request, kpi, state=state)


# --- districts ---------------------------------------------------------------------


@router.get("/dashboards/districts/{district}")
def district_dashboard(
    district: str,
    request: Request,
    sector: str | None = None,
    statute: str | None = None,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return _dashboard(db, user, request, level="district", scope_id=district,
                      district=district, sector=sector, statute=statute,
                      date_from=date_from, date_to=date_to)


@router.get("/dashboards/districts/{district}/explain")
def district_explain(
    district: str,
    request: Request,
    kpi: str = "comp_assessed",
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return _explain(db, user, request, kpi, district=district)


@router.get("/dashboards/explainable-kpis")
def explainable_kpis():
    """Which KPI keys `/explain` accepts — the UI's Explain link reads this rather
    than hard-coding the list (Docs/Frontend.md §4)."""
    return {"kpis": sorted(EXPLAIN_KPIS)}
