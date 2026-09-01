"""Documents and extraction — Docs/APIs.md §3.5.

POST /documents             multipart: file, case_id, kind  -> {id, sha256, duplicate_of?, ...}
GET  /documents/{id}                                        -> metadata + extraction
GET  /documents/{id}/file                                   -> short-lived presigned URL
POST /documents/{id}/extract                                -> 202 {job_id}
GET  /documents/{id}/extraction                             -> proposal
POST /documents/{id}/extraction/reject  {reason}

Extraction runs synchronously: the regex path costs milliseconds and the demo laptop
runs no worker. The response is still 202 with a `job_id` so the contract does not
change when a real queue is put behind it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.problems import Problem, not_found
from app.domain.dashboards.scope import require_case, scoped_case_ids
from app.models import Document

router = APIRouter()

MAX_UPLOAD_BYTES = 32 * 1024 * 1024
ALLOWED_MIME_PREFIXES = ("application/pdf", "image/")
UPLOAD_ROLES = {"RB", "LAO", "CALA", "COLLECTOR", "ADMIN_RR", "STATE_REVENUE", "ADMIN"}


class RejectIn(BaseModel):
    reason: str = ""


def _doc_dict(doc: Document, *, include_extraction: bool = True) -> dict:
    out = {
        "id": str(doc.id),
        "case_id": str(doc.case_id) if doc.case_id else None,
        "kind": doc.kind,
        "sha256": doc.sha256.hex() if doc.sha256 else None,
        "storage_key": doc.storage_key,
        "mime": doc.mime,
        "pages": doc.pages,
        "uploaded_by": str(doc.uploaded_by) if doc.uploaded_by else None,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "supersedes_id": str(doc.supersedes_id) if doc.supersedes_id else None,
        "extraction_status": doc.extraction_status,
    }
    if include_extraction:
        out["extraction"] = doc.extraction
    return out


def _load_document(db: Session, doc_id: str, user: CurrentUser) -> Document:
    try:
        did = uuid.UUID(str(doc_id))
    except (ValueError, TypeError):
        raise not_found()
    doc = db.get(Document, did)
    if doc is None:
        raise not_found()
    if doc.case_id is not None:
        allowed = scoped_case_ids(db, user)
        if allowed is not None and doc.case_id not in allowed:
            raise not_found()
    return doc


@router.post("/documents", status_code=201)
def upload_document(
    response: Response,
    file: UploadFile = File(...),
    case_id: str | None = Form(None),
    kind: str = Form(...),
    supersedes_id: str | None = Form(None),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Store an uploaded document under its SHA-256. Identical bytes on the same case
    return the original row and `duplicate_of` (Docs/rules.md C4)."""
    from app.domain.documents.storage import store_file

    if not user.has_role(*UPLOAD_ROLES):
        raise not_found()
    if not kind:
        raise Problem("validation_error", "Validation error", 422, "kind is required")

    data = file.file.read()
    if not data:
        raise Problem("validation_error", "Validation error", 422, "empty upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise Problem("validation_error", "Validation error", 422,
                      f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    mime = file.content_type or "application/pdf"
    if not mime.startswith(ALLOWED_MIME_PREFIXES):
        raise Problem("validation_error", "Validation error", 422,
                      f"unsupported content type {mime}; upload a PDF or an image")

    case = require_case(db, case_id, user) if case_id else None
    supersedes = None
    if supersedes_id:
        supersedes = _load_document(db, supersedes_id, user).id

    try:
        doc = store_file(
            db, data,
            filename=file.filename or "",
            case_id=case.id if case else None,
            kind=kind,
            mime=mime,
            uploaded_by=uuid.UUID(user.id),
            supersedes_id=supersedes,
        )
    except Exception as exc:  # MinIO unreachable etc. — say so rather than 500 blindly
        raise Problem("storage_unavailable", "Storage unavailable", 503,
                      f"document store rejected the upload: {exc}")

    duplicate_of = getattr(doc, "duplicate_of", None)
    db.commit()
    db.refresh(doc)
    if duplicate_of:
        response.status_code = 200

    body = _doc_dict(doc)
    body["duplicate_of"] = str(duplicate_of) if duplicate_of else None
    body["filename"] = file.filename
    return body


@router.get("/documents/{doc_id}")
def get_document(
    doc_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    return _doc_dict(_load_document(db, doc_id, user))


@router.get("/documents/{doc_id}/file")
def get_document_file(
    doc_id: str,
    expires_in: int = 300,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Short-lived presigned GET URL. The API never proxies document bytes."""
    from app.domain.documents.storage import DEFAULT_URL_TTL_SECONDS, presigned_url

    doc = _load_document(db, doc_id, user)
    ttl = max(30, min(int(expires_in or DEFAULT_URL_TTL_SECONDS), 3600))
    try:
        url = presigned_url(doc.storage_key, ttl, filename=f"{doc.kind}-{str(doc.id)[:8]}.pdf")
    except Exception as exc:
        raise Problem("storage_unavailable", "Storage unavailable", 503, str(exc))
    return {"url": url, "expires_in": ttl, "mime": doc.mime, "sha256": doc.sha256.hex()}


@router.post("/documents/{doc_id}/extract", status_code=202)
def extract_document_endpoint(
    doc_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Run extraction now. `job_id` is the document id — the job and the document are
    one and the same while extraction is synchronous."""
    from app.domain.documents.extraction import extract_document

    doc = _load_document(db, doc_id, user)
    try:
        extraction = extract_document(db, doc)
    except Exception as exc:
        db.rollback()
        raise Problem("extraction_failed", "Extraction failed", 503, str(exc))
    db.commit()
    return {
        "job_id": str(doc.id),
        "document_id": str(doc.id),
        "status": doc.extraction_status,
        "engine": extraction.get("engine"),
        "warnings": extraction.get("warnings", []),
    }


@router.get("/documents/{doc_id}/extraction")
def get_extraction(
    doc_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    doc = _load_document(db, doc_id, user)
    extraction = doc.extraction or {}
    return {
        "document_id": str(doc.id),
        "status": doc.extraction_status,
        "fields": extraction.get("fields", {}),
        "confidence": extraction.get("confidence", {}),
        "source_spans": extraction.get("source_spans", {}),
        "proposed_event": extraction.get("proposed_event"),
        "engine": extraction.get("engine"),
        "pages": extraction.get("pages", doc.pages),
        "ocr": extraction.get("ocr", False),
        "warnings": extraction.get("warnings", []),
    }


@router.post("/documents/{doc_id}/extraction/reject")
def reject_extraction(
    doc_id: str,
    body: RejectIn,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Officer rejects the proposal. The document stays; the proposal is marked
    rejected with who rejected it and why — nothing is deleted."""
    from app.models import AdminAudit

    doc = _load_document(db, doc_id, user)
    doc.extraction_status = "rejected"
    extraction = dict(doc.extraction or {})
    extraction["rejection"] = {"reason": body.reason, "by": user.id, "by_name": user.name}
    extraction["proposed_event"] = None
    doc.extraction = extraction
    db.add(doc)
    db.add(AdminAudit(
        user_id=uuid.UUID(user.id),
        action="EXTRACTION_REJECTED",
        target=str(doc.id),
        meta={"reason": body.reason},
    ))
    db.commit()
    return {"document_id": str(doc.id), "status": doc.extraction_status, "reason": body.reason}


@router.get("/cases/{case_id}/documents")
def list_case_documents(
    case_id: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    case = require_case(db, case_id, user)
    docs = db.scalars(
        select(Document)
        .where(Document.case_id == case.id)
        .order_by(Document.uploaded_at.desc())
    ).all()
    return {"items": [_doc_dict(d, include_extraction=False) for d in docs]}
