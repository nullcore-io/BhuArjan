"""MIS reports — Docs/APIs.md §3.10, Docs/rules.md C7.

POST /reports            {template, filters{state?,district?,statute?}, format}
                         -> 202 {job_id, ...}
GET  /reports/{job_id}   -> {status, url, report_hash, as_of_seq, generated_at, ...}
GET  /reports/templates  -> what this build can produce (the UI reads it)

Transport only: the body is built by `app.domain.reports.service`, the scope by the
dashboards' own `scope` helpers, so a report and the dashboard it was exported from
cannot disagree about which cases the caller may see.

`202` matches the contract's asynchronous shape even though generation is
synchronous here — see the module docstring of `app.domain.reports.service` for why,
and for the two integrity properties (`as_of_seq`, `report_hash`) every export
carries.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_effective_today
from app.core.problems import not_found
from app.domain.dashboards.scope import (
    NATIONAL_ROLES,
    case_ids_for_filters,
    scoped_case_ids,
)
from app.domain.reports.models import ReportJob, ensure_tables
from app.domain.reports.service import (
    FORMATS,
    GEOJSON_TEMPLATES,
    TEMPLATES,
    generate_report,
    job_payload,
    validate_request,
)

router = APIRouter()

URL_TTL_SECONDS = 900  # 15 minutes — long enough to click through from the job reply

# Docs/APIs.md §2. The two registers are case-level extracts — `cases_register` carries
# case numbers and areas, `compensation_register` carries award lines with their
# free-text `owner_ref` — so they go to the roles the matrix gives case-level reads.
# RB is `—` there and `own` on dashboards, so a requiring body may run the aggregate
# KPI export over its own projects and nothing else; without this gate it exported the
# whole compensation register, owner references included.
REGISTER_TEMPLATES = ("cases_register", "compensation_register")
REGISTER_ROLES = {
    "LAO", "CALA", "COLLECTOR", "ADMIN_RR", "STATE_REVENUE", "MINISTRY", "AUDITOR",
}
KPI_ROLES = REGISTER_ROLES | {"RB"}


class ReportFilters(BaseModel):
    state: str | None = None
    district: str | None = None
    statute: str | None = None


class ReportIn(BaseModel):
    template: str
    filters: ReportFilters = Field(default_factory=ReportFilters)
    format: str = "csv"


@router.get("/reports/templates")
def report_templates():
    """What this build can actually produce — the report builder reads this rather
    than hard-coding a list that would outlive the templates (Docs/Frontend.md §4)."""
    return {
        "templates": list(TEMPLATES),
        "formats": list(FORMATS),
        "geojson_templates": list(GEOJSON_TEMPLATES),
        "filters": ["state", "district", "statute"],
        "note": "pdf is in APIs.md §3.10 but is not built in this MVP",
    }


@router.post("/reports", status_code=202)
def create_report(
    body: ReportIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Generate a report over the caller's jurisdiction and return its job.

    Jurisdiction alone was the only gate here, so any authenticated role could export
    the register its RBAC row denies it on screen. A role the §2 matrix does not give
    this template to is a 404, like every other resource it may not see.
    """
    template, fmt, filters = validate_request(
        body.template, body.format, body.filters.model_dump()
    )
    allowed_roles = REGISTER_ROLES if template in REGISTER_TEMPLATES else KPI_ROLES
    if not user.has_role(*allowed_roles):
        raise not_found()
    today = get_effective_today(request)
    base = scoped_case_ids(db, user)
    case_ids = case_ids_for_filters(
        db,
        base,
        state=filters.get("state"),
        district=filters.get("district"),
        statute=filters.get("statute"),
    )
    job = generate_report(
        db,
        template=template,
        fmt=fmt,
        filters=filters,
        case_ids=case_ids,
        today=today,
        requested_by=_caller_uuid(user),
    )
    response.headers["Location"] = f"/api/v1/reports/{job.id}"
    return {
        "job_id": str(job.id),
        "status": job.status,
        "template": job.template,
        "format": job.format,
        "as_of_seq": int(job.as_of_seq or 0),
        "row_count": int(job.row_count or 0),
    }


@router.get("/reports/{job_id}")
def get_report(
    job_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """The finished job and a short-lived presigned URL for its bytes."""
    from app.domain.documents import storage

    ensure_tables()
    try:
        jid = uuid.UUID(str(job_id))
    except (ValueError, TypeError):
        raise not_found()
    job = db.get(ReportJob, jid)
    if job is None or not _may_read(user, job):
        raise not_found()

    url = None
    if job.storage_key:
        url = storage.presigned_url(
            job.storage_key, expires_seconds=URL_TTL_SECONDS, filename=job.filename
        )
    payload = job_payload(job, url=url)
    payload["url_expires_in"] = URL_TTL_SECONDS if url else None
    return payload


# --- helpers ------------------------------------------------------------------------


def _caller_uuid(user: CurrentUser) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(user.id))
    except (ValueError, TypeError):
        return None


def _may_read(user: CurrentUser, job: ReportJob) -> bool:
    """A finished report is a frozen extract of one caller's jurisdiction, so its
    scope cannot be re-checked at read time — the case list it was built from is
    already inside the bytes. Only the requester (or a national role, who could have
    asked for the same rows anyway) may fetch it; anyone else gets a 404, never a
    403 (Docs/APIs.md §1)."""
    if any(r.upper() in NATIONAL_ROLES for r in user.roles):
        return True
    return job.requested_by is not None and str(job.requested_by) == str(user.id)
