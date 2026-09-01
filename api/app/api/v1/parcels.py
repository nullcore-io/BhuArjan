"""Parcels and GIS — Docs/APIs.md §3.6.

GET   /cases/{id}/parcels           -> GeoJSON FeatureCollection
POST  /cases/{id}/parcels/import    -> multipart GeoJSON upload, or a GeoJSON body
PATCH /parcels/{id}                 -> {ulpin?, land_type?, status?, area_ha_override?}
GET   /parcels/lookup?ulpin=        -> parcel + case + stage (scoped)
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_effective_today
from app.core.problems import Problem, not_found
from app.domain.dashboards.scope import require_case, scoped_case_ids
from app.models import Case, CaseState, Parcel, Project

router = APIRouter()

IMPORT_ROLES = {"LAO", "CALA", "COLLECTOR", "ADMIN"}
GEOJSON_MEDIA = "application/geo+json"


class ParcelPatchIn(BaseModel):
    ulpin: str | None = None
    land_type: str | None = None
    status: str | None = None
    village_lgd: str | None = None
    area_ha_override: float | None = None


@router.get("/cases/{case_id}/parcels")
def case_parcels(
    case_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.domain.parcels.service import feature_collection

    case = require_case(db, case_id, user)
    return feature_collection(db, [case.id])


@router.get("/projects/{project_id}/parcels")
def project_parcels(
    project_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """All parcels across a project's cases (Docs/APIs.md §3.2)."""
    from app.domain.parcels.service import feature_collection

    try:
        pid = uuid.UUID(str(project_id))
    except (ValueError, TypeError):
        raise not_found()
    case_ids = [r[0] for r in db.execute(
        select(Case.id).where(Case.project_id == pid)
    ).all()]
    allowed = scoped_case_ids(db, user)
    if allowed is not None:
        case_ids = [c for c in case_ids if c in allowed]
    if not case_ids:
        raise not_found()
    return feature_collection(db, case_ids)


@router.post("/cases/{case_id}/parcels/import")
async def import_parcels(
    case_id: str,
    request: Request,
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Import a GeoJSON FeatureCollection.

    Accepts either a multipart `file` or a raw GeoJSON body. KML and zipped SHP are
    NOT converted in the MVP — they are rejected explicitly rather than half-parsed.
    """
    from app.domain.parcels.service import import_feature_collection

    if not user.has_role(*IMPORT_ROLES):
        raise not_found()
    case = require_case(db, case_id, user)
    today = get_effective_today(request)

    if file is not None:
        name = (file.filename or "").lower()
        if name.endswith((".kml", ".kmz", ".zip", ".shp")):
            raise Problem(
                "validation_error", "Validation error", 422,
                "KML and shapefile import are not available in this build; "
                "convert to GeoJSON (EPSG:4326) and re-upload",
            )
        raw = await file.read()
    else:
        raw = await request.body()
    if not raw:
        raise Problem("validation_error", "Validation error", 422, "empty upload")

    try:
        fc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Problem("validation_error", "Validation error", 422, f"not valid JSON: {exc}")

    result = import_feature_collection(db, case, fc, uuid.UUID(user.id), today)
    db.commit()
    return result


@router.patch("/parcels/{parcel_id}")
def patch_parcel_endpoint(
    parcel_id: str,
    body: ParcelPatchIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    from app.domain.parcels.service import parcel_dict, patch_parcel

    if not user.has_role(*IMPORT_ROLES):
        raise not_found()
    try:
        pid = uuid.UUID(str(parcel_id))
    except (ValueError, TypeError):
        raise not_found()
    parcel = db.get(Parcel, pid)
    if parcel is None:
        raise not_found()
    allowed = scoped_case_ids(db, user)
    if allowed is not None and parcel.case_id not in allowed:
        raise not_found()

    patch_parcel(db, parcel, body.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(parcel)
    return parcel_dict(db, parcel)


@router.get("/parcels/lookup")
def lookup_parcel(
    ulpin: str | None = None,
    state: str | None = None,
    district: str | None = None,
    village: str | None = None,
    survey_no: str | None = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Authenticated lookup: parcel + case + stage, within the caller's jurisdiction."""
    from app.domain.parcels.service import lookup, parcel_dict

    if not (ulpin or (village and survey_no)):
        raise Problem("validation_error", "Validation error", 422,
                      "provide ulpin, or village and survey_no")
    parcel = lookup(db, ulpin=ulpin, state=state, district=district,
                    village=village, survey_no=survey_no)
    if parcel is None:
        raise not_found()
    allowed = scoped_case_ids(db, user)
    if allowed is not None and parcel.case_id not in allowed:
        raise not_found()

    case = db.get(Case, parcel.case_id)
    project = db.get(Project, case.project_id) if case else None
    state_row = db.get(CaseState, parcel.case_id)
    return {
        "parcel": parcel_dict(db, parcel),
        "case": {
            "id": str(case.id),
            "case_no": case.case_no,
            "statute_track": case.statute_track,
            "ruleset_version": case.ruleset_version,
        } if case else None,
        "project": {
            "id": str(project.id),
            "name": project.name,
            "sector": project.sector,
            "state_code": project.state_code,
        } if project else None,
        "stage": state_row.stage if state_row else None,
        "as_of_seq": state_row.as_of_seq if state_row else None,
    }
