"""Report generation (Docs/APIs.md §3.10, Docs/rules.md C7).

Synchronous by design. APIs.md answers `202 {job_id}` because the contract has to
allow a queue at national scale, and the client polls `GET /reports/{job_id}` — but
on a demo laptop the whole estate is a few hundred rows, and a worker that exists
only to make the demo look distributed would be one more thing to explain when it
falls over. So the bytes are produced inside the request, stored, and the job row is
written already `done`. The status field is real, not decorative: a queue can be
slid in behind it without moving the contract.

Two integrity properties every export carries (rules.md C7):

* **`as_of_seq`** — `max(events.seq)` over the cases in scope, on the first line of
  the CSV as `# as_of_seq=N` and as a top-level member of the GeoJSON. A figure
  without it is a number with no time attached to it.
* **`report_hash`** — the SHA-256 of the exact bytes served. It is the object's own
  content address, so a file someone mailed onwards can be checked against the job
  it came from.

Scope is the caller's jurisdiction, resolved through the same
`app.domain.dashboards.scope` helpers the dashboards use, then narrowed by the
request filters. A report can therefore never contain a case its requester could not
open (Docs/rules.md C6).
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.problems import Problem
from app.domain.dashboards import service as dash
from app.domain.reports.models import ReportJob, ensure_tables
from app.models import Case, CaseState, CompensationLine, OrgUnit, Parcel, Project

TEMPLATES = ("national_kpis", "cases_register", "compensation_register")
FORMATS = ("csv", "geojson")
# GeoJSON is a map of parcels; only the cases register has parcels to draw.
GEOJSON_TEMPLATES = ("cases_register",)

CSV_MIME = "text/csv; charset=utf-8"
GEOJSON_MIME = "application/geo+json"

FILTER_KEYS = ("state", "district", "statute")


# --- validation ---------------------------------------------------------------------


def validate_request(template: str, fmt: str, filters: dict | None) -> tuple[str, str, dict]:
    """Normalise the request or raise `validation_error` naming what is supported."""
    template = (template or "").strip().lower()
    fmt = (fmt or "csv").strip().lower()
    errors = []
    if template not in TEMPLATES:
        errors.append({"field": "template", "expected": list(TEMPLATES), "got": template})
    if fmt not in FORMATS:
        errors.append({
            "field": "format",
            "expected": list(FORMATS),
            "got": fmt,
            "note": "pdf is documented in APIs.md §3.10 but is not built in this MVP",
        })
    if not errors and fmt == "geojson" and template not in GEOJSON_TEMPLATES:
        errors.append({
            "field": "format",
            "detail": f"geojson is only available for {', '.join(GEOJSON_TEMPLATES)}",
        })
    if errors:
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            "the report request names a template or format this build does not produce",
            errors=errors,
        )
    clean = {
        k: str(v).strip()
        for k, v in (filters or {}).items()
        if k in FILTER_KEYS and v not in (None, "")
    }
    return template, fmt, clean


# --- body builders ------------------------------------------------------------------


def _paise(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _area(value) -> str:
    """Areas are hectares as a numeric string (APIs.md §1), four decimals."""
    try:
        return f"{float(value or 0):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _pct(value) -> str:
    try:
        return f"{float(value or 0):.2f}"
    except (TypeError, ValueError):
        return "0.00"


FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value):
    """Neutralise spreadsheet formula injection in a text cell.

    A `case_no` and a `project.name` are operator-supplied strings, and these
    exports exist to be opened in Excel. A value beginning `=`, `+`, `-`, `@`
    (or a tab/CR) is evaluated as a formula on open — `=HYPERLINK(...)` in a case
    number would run in the reviewer's spreadsheet, from a file signed with our own
    report hash. Prefixing with an apostrophe is the standard mitigation: the cell
    still reads correctly in a spreadsheet, and the prefix is visible in the raw CSV
    rather than being a silent edit.
    """
    if isinstance(value, str) and value[:1] in FORMULA_LEADERS:
        return "'" + value
    return value


def _csv_bytes(header: list[str], rows: list[list], meta: dict) -> bytes:
    """CSV with the provenance comment block on top; `# as_of_seq=N` comes first."""
    rows = [[_safe_cell(cell) for cell in row] for row in rows]
    buf = io.StringIO(newline="")
    buf.write(f"# as_of_seq={meta['as_of_seq']}\n")
    buf.write(f"# template={meta['template']}\n")
    buf.write(f"# generated_at={meta['generated_at']}\n")
    buf.write(f"# cases={meta['case_count']}\n")
    buf.write(
        "# filters="
        + json.dumps(meta["filters"], sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _national_kpis_rows(db: Session, case_ids: list[uuid.UUID], today: date) -> tuple[list, list]:
    """`kpi,value,source` — the dashboard tiles, with where each number came from."""
    block = dash.kpis(db, case_ids, today)
    sources = block.get("sources") or {}
    rows: list[list] = []
    for key in dash.KPI_KEYS:
        value = block.get(key)
        if isinstance(value, dict):  # clocks_by_status
            for status, count in sorted(value.items()):
                rows.append([f"{key}.{status}", count, "clocks"])
            if not value:
                rows.append([key, 0, "clocks"])
            continue
        rows.append([key, value, sources.get(key, "")])
    rows.append(["case_count", block.get("case_count", 0), "cases"])
    return ["kpi", "value", "source"], rows


def _cases_register_rows(db: Session, case_ids: list[uuid.UUID]) -> tuple[list, list]:
    """One row per case (APIs.md §3.10 / Docs/Frontend.md §4 report builder)."""
    header = [
        "case_no", "project", "statute", "stage", "district",
        "area_notified_ha", "area_acquired_ha",
        "comp_assessed_paise", "comp_paid_paise",
        "possession_pct", "risk_score", "case_id",
    ]
    if not case_ids:
        return header, []
    records = db.execute(
        select(Case, Project, OrgUnit, CaseState)
        .join(Project, Project.id == Case.project_id)
        .outerjoin(OrgUnit, OrgUnit.id == Case.district_id)
        .outerjoin(CaseState, CaseState.case_id == Case.id)
        .where(Case.id.in_(case_ids))
        .order_by(Case.case_no.asc())
    ).all()
    rows = []
    for case, project, district, state in records:
        rows.append([
            case.case_no or "",
            project.name if project else "",
            case.statute_track,
            (state.stage if state else "PROPOSED"),
            district.name if district else "",
            _area(state.area_notified_ha if state else 0),
            _area(state.area_acquired_ha if state else 0),
            _paise(state.comp_assessed_paise if state else 0),
            _paise(state.comp_paid_paise if state else 0),
            _pct(state.possession_pct if state else 0),
            _pct(state.risk_score if state else 0),
            str(case.id),
        ])
    return header, rows


def _compensation_register_rows(db: Session, case_ids: list[uuid.UUID]) -> tuple[list, list]:
    """One row per `compensation_lines` row — the First Schedule working (Backend §7)."""
    header = [
        "case_no", "village", "survey_no", "owner_ref",
        "market_value_paise", "mv_method", "factor", "assets_paise",
        "base_paise", "solatium_paise", "interest_paise",
        "total_paise", "paid_paise", "outstanding_paise",
    ]
    if not case_ids:
        return header, []
    records = db.execute(
        select(CompensationLine, Case, Parcel)
        .join(Case, Case.id == CompensationLine.case_id)
        .outerjoin(Parcel, Parcel.id == CompensationLine.parcel_id)
        .where(CompensationLine.case_id.in_(case_ids))
        .order_by(Case.case_no.asc(), CompensationLine.created_at.asc())
    ).all()
    rows = []
    for line, case, parcel in records:
        total, paid = _paise(line.total_paise), _paise(line.paid_paise)
        rows.append([
            case.case_no or "",
            parcel.village_name if parcel else "",
            parcel.survey_no if parcel else "",
            line.owner_ref or "",
            _paise(line.market_value_paise),
            line.mv_method or "",
            f"{float(line.factor or 0):.2f}",
            _paise(line.assets_paise),
            _paise(line.base_paise),
            _paise(line.solatium_paise),
            _paise(line.interest_paise),
            total,
            paid,
            max(total - paid, 0),
        ])
    return header, rows


def _cases_geojson(db: Session, case_ids: list[uuid.UUID], meta: dict) -> tuple[bytes, int]:
    """The register's parcels as a FeatureCollection, stamped with `as_of_seq`."""
    from app.domain.parcels.service import feature_collection

    fc = feature_collection(db, case_ids)
    case_nos = {}
    if case_ids:
        case_nos = {
            str(cid): no
            for cid, no in db.execute(
                select(Case.id, Case.case_no).where(Case.id.in_(case_ids))
            ).all()
        }
    for feature in fc["features"]:
        feature["properties"]["case_no"] = case_nos.get(feature["properties"]["case_id"])
    # Foreign members are legal GeoJSON (RFC 7946 §6.1) and are how the export
    # carries the same provenance the CSV comment block does.
    fc["as_of_seq"] = meta["as_of_seq"]
    fc["report"] = {
        "template": meta["template"],
        "generated_at": meta["generated_at"],
        "filters": meta["filters"],
        "cases": meta["case_count"],
    }
    return json.dumps(fc, ensure_ascii=False).encode("utf-8"), len(fc["features"])


# --- generation ---------------------------------------------------------------------


def generate_report(
    db: Session,
    *,
    template: str,
    fmt: str,
    filters: dict,
    case_ids: list[uuid.UUID],
    today: date,
    requested_by: uuid.UUID | None = None,
) -> ReportJob:
    """Build the body, store it, and persist the job row. Commits."""
    from app.domain.documents import storage

    ensure_tables()
    generated_at = datetime.now(timezone.utc)
    meta = {
        "template": template,
        "as_of_seq": dash.as_of_seq(db, case_ids),
        "generated_at": generated_at.isoformat(),
        "filters": filters,
        "case_count": len(case_ids),
    }

    if fmt == "geojson":
        body, row_count = _cases_geojson(db, case_ids, meta)
        mime, ext = GEOJSON_MIME, "geojson"
    else:
        if template == "national_kpis":
            header, rows = _national_kpis_rows(db, case_ids, today)
        elif template == "cases_register":
            header, rows = _cases_register_rows(db, case_ids)
        else:
            header, rows = _compensation_register_rows(db, case_ids)
        body = _csv_bytes(header, rows, meta)
        row_count = len(rows)
        mime, ext = CSV_MIME, "csv"

    sha_hex, key = storage.put_bytes(body, mime)
    filename = f"{template}_asof{meta['as_of_seq']}_{sha_hex[:8]}.{ext}"

    job = ReportJob(
        template=template,
        format=fmt,
        filters=filters,
        status="done",
        as_of_seq=meta["as_of_seq"],
        row_count=row_count,
        case_count=len(case_ids),
        storage_key=key,
        report_hash=sha_hex,
        size_bytes=len(body),
        mime=mime,
        filename=filename,
        detail="generated synchronously; see app/domain/reports/service.py",
        requested_by=requested_by,
        generated_at=generated_at,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def job_payload(job: ReportJob, *, url: str | None = None) -> dict:
    """The `GET /reports/{job_id}` body (APIs.md §3.10)."""
    return {
        "job_id": str(job.id),
        "status": job.status,
        "template": job.template,
        "format": job.format,
        "filters": job.filters or {},
        "url": url,
        "report_hash": job.report_hash,
        "as_of_seq": int(job.as_of_seq or 0),
        "row_count": int(job.row_count or 0),
        "case_count": int(job.case_count or 0),
        "size_bytes": int(job.size_bytes or 0),
        "mime": job.mime,
        "filename": job.filename,
        "generated_at": job.generated_at.isoformat() if job.generated_at else None,
        "detail": job.detail,
    }
