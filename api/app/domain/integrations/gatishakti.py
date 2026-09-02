"""PM Gati Shakti NMP adapter (Docs/APIs.md §4).

Live target: the National Master Plan, which consumes a project's acquisition
footprint as a layer.

The mock does the real work of the export: it reads the project's parcels out of
PostGIS through `app.domain.parcels.service.feature_collection` — the same
FeatureCollection `/projects/{id}/parcels` serves — writes it to MinIO
content-addressed, and returns a presigned URL. What is mocked is only the
handshake: nothing is published to the NMP, and the URL is short-lived and signed
rather than public.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.integrations.base import BaseAdapter, register, utc_now_iso
from app.models import Case, Project

GEOJSON_MIME = "application/geo+json"
URL_TTL_SECONDS = 900  # 15 minutes: long enough to hand the link to a GIS operator


class GatiShaktiAdapter(BaseAdapter):
    name = "gatishakti"
    title = "PM Gati Shakti NMP"
    mode = "mock"
    interface = "export(project_id)"
    real_target = "PM Gati Shakti National Master Plan"
    mock_behaviour = "writes the project's parcels GeoJSON to MinIO; presigned URL"

    def export(self, db: Session, project_id) -> dict:
        """Write the project footprint to MinIO. `{url, features, sha256, ...}`."""
        from app.domain.documents import storage
        from app.domain.parcels.service import feature_collection

        try:
            pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(
                str(project_id)
            )
        except (ValueError, AttributeError, TypeError):
            return {
                "found": False,
                "project_id": str(project_id),
                "detail": "not a project id",
            }
        project = db.get(Project, pid)
        if project is None:
            return {"found": False, "project_id": str(pid), "detail": "no such project"}

        case_ids = list(
            db.scalars(select(Case.id).where(Case.project_id == project.id)).all()
        )
        fc = feature_collection(db, case_ids)
        fc["properties"] = {
            "project_id": str(project.id),
            "project_name": project.name,
            "statute_track": project.statute_track,
            "state_code": project.state_code,
            "cases": len(case_ids),
            "exported_at": utc_now_iso(),
            "exported_by": "BhuArjan (mock Gati Shakti adapter)",
        }
        body = json.dumps(fc, ensure_ascii=False).encode("utf-8")
        sha_hex, key = storage.put_bytes(body, GEOJSON_MIME)
        filename = f"gatishakti_{project.id}.geojson"
        url = storage.presigned_url(key, expires_seconds=URL_TTL_SECONDS, filename=filename)
        return {
            "found": True,
            "project_id": str(project.id),
            "project_name": project.name,
            "cases": len(case_ids),
            "features": len(fc["features"]),
            "area_total_ha": fc.get("area_total_ha"),
            "storage_key": key,
            "sha256": sha_hex,
            "size_bytes": len(body),
            "mime": GEOJSON_MIME,
            "filename": filename,
            "url": url,
            "url_expires_in": URL_TTL_SECONDS,
            "mode": self.mode,
            "detail": "written to MinIO; nothing was published to the NMP",
        }

    def _test(self, db: Session | None = None) -> dict:
        from app.domain.documents import storage

        bucket = storage.ensure_bucket()  # raises if MinIO is unreachable -> ok:false
        projects = (
            db.scalar(select(func.count()).select_from(Project)) if db is not None else None
        )
        return {
            "ok": True,
            "detail": (
                f"MinIO reachable, bucket '{bucket}' ready"
                + (f"; {int(projects)} project(s) exportable" if projects is not None else "")
            ),
            "bucket": bucket,
        }


adapter = register(GatiShaktiAdapter())
