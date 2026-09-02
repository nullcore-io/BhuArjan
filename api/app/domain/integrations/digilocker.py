"""DigiLocker issuance adapter (Docs/APIs.md §4).

Live target: DigiLocker's issuer API — a citizen pulls the award or the possession
memo into their own locker, addressed by a URI the issuer mints.

**What this mock does and does not do.** It mints the issuance envelope — the URI,
the issuer, the document's SHA-256, the timestamp — from the real `documents` row,
so the shape is the live one. It does **not** stamp the PDF: `watermarked: true`
describes the envelope DigiLocker would receive, not bytes this build rewrote. The
`detail` on every reply says so, and `deferred` lists `esign`, which is not
simulated at all. APIs.md §4 says the demo must be honest about the seam; putting a
watermark claim in a field without saying what produced it is exactly the kind of
thing that gets caught on stage.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.integrations.base import BaseAdapter, register, utc_now_iso
from app.models import Document

ISSUER = "BHUARJAN"
URI_TEMPLATE = "digilocker://{issuer}/documents/{sha256}"
STUB_DETAIL = (
    "envelope only — the mock mints the issuance metadata from the stored document "
    "and does not rewrite the PDF; no watermark is drawn on the bytes"
)


class DigilockerAdapter(BaseAdapter):
    name = "digilocker"
    title = "DigiLocker / eSign"
    mode = "mock"
    interface = "issue(document_id)"
    real_target = "DigiLocker / eSign (CDAC)"
    mock_behaviour = "mints the issuance envelope; does not stamp or sign the PDF"
    deferred = ("esign(document_id, signer)",)

    def issue(self, db: Session, document_id) -> dict:
        """`{uri, watermarked: true, ...}` for a document this system holds."""
        try:
            doc_id = document_id if isinstance(document_id, uuid.UUID) else uuid.UUID(
                str(document_id)
            )
        except (ValueError, AttributeError, TypeError):
            return {
                "found": False,
                "document_id": str(document_id),
                "detail": "not a document id",
            }
        doc = db.get(Document, doc_id)
        if doc is None:
            return {
                "found": False,
                "document_id": str(doc_id),
                "detail": "no such document",
            }
        sha_hex = doc.sha256.hex() if doc.sha256 else ""
        return {
            "found": True,
            "document_id": str(doc.id),
            "uri": URI_TEMPLATE.format(issuer=ISSUER.lower(), sha256=sha_hex),
            "watermarked": True,
            "issuer": ISSUER,
            "doc_type": doc.kind,
            "sha256": sha_hex,
            "mime": doc.mime,
            "pages": doc.pages,
            "issued_at": utc_now_iso(),
            "mode": self.mode,
            "detail": STUB_DETAIL,
        }

    def _test(self, db: Session | None = None) -> dict:
        if db is None:
            return {"ok": False, "detail": "no database session supplied"}
        count = db.scalar(select(func.count()).select_from(Document)) or 0
        return {
            "ok": True,
            "detail": (
                f"mock issuer ready over {count} stored document(s); {STUB_DETAIL}"
            ),
            "documents": int(count),
            "deferred": list(self.deferred),
        }


adapter = register(DigilockerAdapter())
