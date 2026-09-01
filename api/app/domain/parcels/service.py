"""Parcels and GIS (Docs/APIs.md §3.6).

Parcels are read and written as GeoJSON in EPSG:4326. Area is authoritative from the
geometry: `ST_Area(geom::geography) / 10000` gives hectares on the spheroid, which is
what a revenue record means by "area" — a planar ST_Area on degrees would be nonsense.
An explicitly supplied `area_ha` (from the gazette schedule) wins over the computed
value and is flagged as such, because the gazette is the legal figure.

Every imported parcel emits `PARCEL_ADDED` through
`app.domain.events.service.append_event`, actored by the importing user.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.models import Case, Parcel

log = logging.getLogger(__name__)

SRID = 4326
PARCEL_STATUSES = ("notified", "awarded", "paid", "possessed", "disputed")


# --- geometry ----------------------------------------------------------------------


def geometry_to_wkt(geometry: dict) -> str:
    """GeoJSON geometry -> MultiPolygon WKT. Polygons are promoted; anything that is
    not an area is rejected — a parcel is a piece of land, not a point or a line."""
    from shapely.geometry import shape
    from shapely.geometry.multipolygon import MultiPolygon
    from shapely.geometry.polygon import Polygon

    geom = shape(geometry)
    if isinstance(geom, Polygon):
        geom = MultiPolygon([geom])
    elif not isinstance(geom, MultiPolygon):
        raise ValueError(f"geometry type {geom.geom_type} is not a polygon")
    if geom.is_empty:
        raise ValueError("empty geometry")
    return geom.wkt


def area_ha_from_wkt(db: Session, wkt: str) -> float:
    """Geodesic area in hectares via PostGIS."""
    value = db.execute(
        text("SELECT ST_Area(ST_GeomFromText(:wkt, :srid)::geography) / 10000.0"),
        {"wkt": wkt, "srid": SRID},
    ).scalar()
    return round(float(value or 0.0), 4)


# --- read --------------------------------------------------------------------------


def _feature(row) -> dict:
    import json

    parcel, geojson = row
    return {
        "type": "Feature",
        "id": str(parcel.id),
        "geometry": json.loads(geojson) if geojson else None,
        "properties": {
            "parcel_id": str(parcel.id),
            "case_id": str(parcel.case_id),
            "survey_no": parcel.survey_no,
            "ulpin": parcel.ulpin,
            "area_ha": float(parcel.area_ha) if parcel.area_ha is not None else None,
            "status": parcel.status,
            "village": parcel.village_name,
            "village_lgd": parcel.village_lgd,
            "land_type": parcel.land_type,
        },
    }


def feature_collection(db: Session, case_ids: list[uuid.UUID]) -> dict:
    if not case_ids:
        return {"type": "FeatureCollection", "features": [], "area_total_ha": 0.0}
    rows = db.execute(
        select(Parcel, func.ST_AsGeoJSON(Parcel.geom))
        .where(Parcel.case_id.in_(case_ids))
        .order_by(Parcel.village_name.asc(), Parcel.survey_no.asc())
    ).all()
    features = [_feature(r) for r in rows]
    total = sum(f["properties"]["area_ha"] or 0.0 for f in features)
    return {
        "type": "FeatureCollection",
        "features": features,
        "area_total_ha": round(total, 4),
    }


def parcel_dict(db: Session, parcel: Parcel) -> dict:
    geojson = db.scalar(select(func.ST_AsGeoJSON(Parcel.geom)).where(Parcel.id == parcel.id))
    return _feature((parcel, geojson))


# --- import ------------------------------------------------------------------------


def _props(feature: dict) -> dict:
    return feature.get("properties") or {}


def _first(props: dict, *names, default=None):
    for n in names:
        if props.get(n) not in (None, ""):
            return props[n]
    return default


def import_feature_collection(
    db: Session,
    case: Case,
    fc: dict,
    actor_id: uuid.UUID,
    today: date,
) -> dict:
    """Import a GeoJSON FeatureCollection into a case.

    Returns `{imported, skipped[], area_total_ha, events_emitted, events_skipped[]}`.
    Every input feature lands in exactly one of imported/skipped — the counts sum to
    the number of features supplied.
    """
    from app.domain.events.service import append_event

    if not isinstance(fc, dict):
        raise Problem("validation_error", "Validation error", 422, "body is not GeoJSON")
    if fc.get("type") == "Feature":
        fc = {"type": "FeatureCollection", "features": [fc]}
    features = fc.get("features")
    if fc.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise Problem("validation_error", "Validation error", 422,
                      "expected a GeoJSON FeatureCollection")

    crs_name = ((fc.get("crs") or {}).get("properties") or {}).get("name", "")
    if crs_name and "4326" not in str(crs_name) and "CRS84" not in str(crs_name).upper():
        raise Problem("validation_error", "Validation error", 422,
                      f"unsupported CRS {crs_name}; reproject to EPSG:4326 before import")

    imported: list[dict] = []
    skipped: list[dict] = []
    events_skipped: list[dict] = []
    events_emitted = 0

    for i, feature in enumerate(features):
        props = _props(feature)
        survey_no = _first(props, "survey_no", "survey", "khasra", "khasra_no")
        try:
            geometry = feature.get("geometry")
            if not geometry:
                raise ValueError("feature has no geometry")
            wkt = geometry_to_wkt(geometry)
        except Exception as exc:
            skipped.append({"index": i, "survey_no": survey_no, "reason": str(exc)})
            continue

        supplied = _first(props, "area_ha", "area", "area_hectare")
        computed = area_ha_from_wkt(db, wkt)
        if supplied not in (None, ""):
            try:
                area_ha = round(float(supplied), 4)
                area_source = "supplied"
            except (TypeError, ValueError):
                area_ha, area_source = computed, "computed"
        else:
            area_ha, area_source = computed, "computed"

        status = str(_first(props, "status", default="notified")).lower()
        if status not in PARCEL_STATUSES:
            status = "notified"

        parcel = Parcel(
            case_id=case.id,
            village_name=_first(props, "village", "village_name"),
            village_lgd=_first(props, "village_lgd", "lgd", "lgd_code"),
            survey_no=survey_no,
            ulpin=_first(props, "ulpin"),
            area_ha=area_ha,
            land_type=_first(props, "land_type", default="rural"),
            status=status,
            geom=WKTElement(wkt, srid=SRID),
        )
        db.add(parcel)
        db.flush()

        payload = {
            "parcel_id": str(parcel.id),
            "survey_no": parcel.survey_no,
            "village": parcel.village_name,
            "village_lgd": parcel.village_lgd,
            "ulpin": parcel.ulpin,
            "area_ha": f"{area_ha:.4f}",
            "area_source": area_source,
            "area_computed_ha": f"{computed:.4f}",
            "source": "geojson_import",
        }
        try:
            append_event(db, case, "PARCEL_ADDED", today, actor_id, payload, today=today)
            events_emitted += 1
        except Problem as exc:
            # The rule-set may not permit PARCEL_ADDED from the current stage. The
            # parcel row still stands; the rejection is reported, never swallowed.
            events_skipped.append({
                "parcel_id": str(parcel.id),
                "reason": exc.type,
                "detail": exc.detail,
                "ruleset_ref": exc.ruleset_ref,
            })
        except NotImplementedError:
            events_skipped.append({
                "parcel_id": str(parcel.id),
                "reason": "ledger_unavailable",
                "detail": "append_event not implemented in this build",
            })

        imported.append({
            "parcel_id": str(parcel.id),
            "survey_no": parcel.survey_no,
            "village": parcel.village_name,
            "area_ha": area_ha,
            "area_source": area_source,
        })

    return {
        "imported": len(imported),
        "parcels": imported,
        "skipped": skipped,
        "area_total_ha": round(sum(p["area_ha"] for p in imported), 4),
        "events_emitted": events_emitted,
        "events_skipped": events_skipped,
        "features_received": len(features),
    }


# --- update / lookup ---------------------------------------------------------------


def patch_parcel(db: Session, parcel: Parcel, changes: dict) -> Parcel:
    """Reference-data correction on a parcel. Deliberately NOT a ledger event: the
    statutory record is the notification, and `PARCEL_UPDATED` is not an allowed
    transition in either shipped rule-set (see open issues)."""
    if "ulpin" in changes and changes["ulpin"] is not None:
        parcel.ulpin = changes["ulpin"]
    if "land_type" in changes and changes["land_type"] is not None:
        if changes["land_type"] not in ("rural", "urban"):
            raise Problem("validation_error", "Validation error", 422,
                          "land_type must be rural or urban")
        parcel.land_type = changes["land_type"]
    if "status" in changes and changes["status"] is not None:
        if changes["status"] not in PARCEL_STATUSES:
            raise Problem("validation_error", "Validation error", 422,
                          f"status must be one of {', '.join(PARCEL_STATUSES)}")
        parcel.status = changes["status"]
    if "village_lgd" in changes and changes["village_lgd"] is not None:
        parcel.village_lgd = changes["village_lgd"]
    if changes.get("area_ha_override") is not None:
        try:
            parcel.area_ha = round(float(changes["area_ha_override"]), 4)
        except (TypeError, ValueError):
            raise Problem("validation_error", "Validation error", 422,
                          "area_ha_override must be numeric")
    db.add(parcel)
    db.flush()
    return parcel


def lookup(
    db: Session,
    *,
    ulpin: str | None = None,
    state: str | None = None,
    district: str | None = None,
    village: str | None = None,
    survey_no: str | None = None,
) -> Parcel | None:
    """Find one parcel by ULPIN, or by the village/survey-number address a citizen
    would read off their record."""
    q = select(Parcel)
    if ulpin:
        q = q.where(func.upper(Parcel.ulpin) == ulpin.strip().upper())
    else:
        if not (village and survey_no):
            return None
        q = q.where(
            func.lower(Parcel.village_name) == village.strip().lower(),
            func.replace(Parcel.survey_no, " ", "") == survey_no.strip().replace(" ", ""),
        )
        if district or state:
            from app.models import Case as CaseModel
            from app.models import OrgUnit, Project

            q = q.join(CaseModel, CaseModel.id == Parcel.case_id)
            q = q.join(Project, Project.id == CaseModel.project_id)
            if state:
                q = q.where(func.upper(Project.state_code) == state.strip().upper())
            if district:
                q = q.join(OrgUnit, OrgUnit.id == CaseModel.district_id).where(
                    func.lower(OrgUnit.name) == district.strip().lower()
                )
    return db.scalars(q.limit(1)).first()
