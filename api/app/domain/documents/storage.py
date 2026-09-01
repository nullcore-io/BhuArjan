"""Content-addressed document storage on MinIO (S3 API).

Docs/Backend.md §6 / Docs/rules.md C4: documents are stored once, addressed by the
SHA-256 of their bytes; a re-upload of identical bytes never writes a second object
and never creates a second `documents` row for the same (case, kind) — it reports
`duplicate_of`. New versions supersede via `documents.supersedes_id`, never overwrite.

The bucket is created on first use. Presigned GET URLs are signed against
`MINIO_PUBLIC_ENDPOINT` (the host the browser will actually call) because the S3
V4 signature covers the Host header — signing against the internal endpoint would
produce a URL that 403s from outside the compose network.
"""

from __future__ import annotations

import hashlib
import io
import logging
import mimetypes
import uuid
from datetime import timedelta

from minio import Minio
from minio.error import S3Error
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Document

log = logging.getLogger(__name__)

KEY_PREFIX = "sha256"
DEFAULT_URL_TTL_SECONDS = 300  # short-lived, per Docs/APIs.md §3.5

_client: Minio | None = None
_public_client: Minio | None = None
_bucket_ready = False


# --- clients ----------------------------------------------------------------------


def client() -> Minio:
    """Client bound to the internal endpoint (used for put/get)."""
    global _client
    if _client is None:
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
    return _client


def public_client() -> Minio:
    """Client bound to MINIO_PUBLIC_ENDPOINT — only used to sign browser-facing URLs."""
    global _public_client
    if settings.MINIO_PUBLIC_ENDPOINT == settings.MINIO_ENDPOINT:
        return client()
    if _public_client is None:
        _public_client = Minio(
            settings.MINIO_PUBLIC_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
    return _public_client


def ensure_bucket() -> str:
    """Create the bucket if it does not exist. Returns the bucket name."""
    global _bucket_ready
    bucket = settings.MINIO_BUCKET
    if _bucket_ready:
        return bucket
    c = client()
    if not c.bucket_exists(bucket):
        c.make_bucket(bucket)
        log.info("storage: created bucket %s", bucket)
    _bucket_ready = True
    return bucket


# --- content addressing -----------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_key(sha_hex: str) -> str:
    """Content-addressed key: sha256/<first two hex chars>/<full hex>."""
    return f"{KEY_PREFIX}/{sha_hex[:2]}/{sha_hex}"


def guess_mime(filename: str, fallback: str = "application/octet-stream") -> str:
    if not filename:
        return fallback
    return mimetypes.guess_type(filename)[0] or fallback


def count_pdf_pages(data: bytes) -> int | None:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return len(pdf.pages)
    except Exception:
        return None


# --- object operations ------------------------------------------------------------


def put_bytes(data: bytes, mime: str = "application/octet-stream") -> tuple[str, str]:
    """Upload bytes under their content address. Returns (sha256_hex, storage_key).

    Idempotent: an object already present at the key is left untouched (identical
    bytes by construction).
    """
    bucket = ensure_bucket()
    sha_hex = sha256_hex(data)
    key = object_key(sha_hex)
    c = client()
    try:
        c.stat_object(bucket, key)
        return sha_hex, key  # already stored
    except S3Error as exc:
        if exc.code not in ("NoSuchKey", "NoSuchObject", "NotFound"):
            raise
    c.put_object(bucket, key, io.BytesIO(data), length=len(data), content_type=mime)
    return sha_hex, key


def get_bytes(storage_key: str) -> bytes:
    """Fetch an object's bytes (used by the extraction pipeline)."""
    ensure_bucket()
    resp = client().get_object(settings.MINIO_BUCKET, storage_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def presigned_url(
    storage_key: str,
    expires_seconds: int = DEFAULT_URL_TTL_SECONDS,
    filename: str | None = None,
) -> str:
    """Short-lived presigned GET URL, signed for MINIO_PUBLIC_ENDPOINT."""
    ensure_bucket()
    params = None
    if filename:
        safe = filename.replace('"', "")
        params = {"response-content-disposition": f'inline; filename="{safe}"'}
    return public_client().presigned_get_object(
        settings.MINIO_BUCKET,
        storage_key,
        expires=timedelta(seconds=expires_seconds),
        response_headers=params,
    )


# --- document rows ----------------------------------------------------------------


def find_by_sha(db: Session, sha: bytes, case_id: uuid.UUID | None = None) -> Document | None:
    q = db.query(Document).filter(Document.sha256 == sha)
    if case_id is not None:
        q = q.filter(Document.case_id == case_id)
    return q.order_by(Document.uploaded_at.asc()).first()


def store_file(
    db: Session,
    data: bytes,
    *,
    filename: str = "",
    case_id: uuid.UUID | None = None,
    kind: str = "",
    mime: str | None = None,
    uploaded_by: uuid.UUID | None = None,
    supersedes_id: uuid.UUID | None = None,
) -> Document:
    """Store bytes and return the `documents` row.

    Dedupe: identical bytes already recorded against the same case return the
    EXISTING row. Callers read the transient attribute `document.duplicate_of`
    (a uuid when this upload was a duplicate, otherwise None) — it is not a mapped
    column, it only describes what this call did.

    Does not commit; the caller owns the transaction.
    """
    mime = mime or guess_mime(filename, "application/pdf")
    sha_hex, key = put_bytes(data, mime)
    sha = bytes.fromhex(sha_hex)

    existing = find_by_sha(db, sha, case_id)
    if existing is not None:
        existing.duplicate_of = existing.id  # transient marker, see docstring
        return existing

    doc = Document(
        case_id=case_id,
        kind=kind,
        storage_key=key,
        sha256=sha,
        mime=mime,
        pages=count_pdf_pages(data) if mime == "application/pdf" else None,
        uploaded_by=uploaded_by,
        supersedes_id=supersedes_id,
        extraction=None,
        extraction_status="pending",
    )
    db.add(doc)
    db.flush()
    doc.duplicate_of = None
    return doc


def document_bytes(doc: Document) -> bytes:
    return get_bytes(doc.storage_key)
