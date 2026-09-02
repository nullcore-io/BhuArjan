"""PFMS payments adapter (Docs/APIs.md §4).

Live target: the Public Financial Management System payment-status APIs.

The mock answers from the ledger rather than from a timer. APIs.md §4 sketches a
demo that flips a reference to `PAID` two minutes after it is quoted; that would
report money as disbursed on the strength of a stopwatch. Here a reference is `PAID`
only when a `PAYMENT_MADE` event carrying it exists in the case ledger, and
`UNKNOWN` otherwise — the same answer a real PFMS reconciliation would have to
justify, and one that cannot drift away from the s.38 possession gate that reads the
same events.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.integrations.base import BaseAdapter, register
from app.models import Case, Event

PAYMENT_EVENT = "PAYMENT_MADE"

STATUS_PAID = "PAID"
STATUS_UNKNOWN = "UNKNOWN"


def _amount(payload: dict | None) -> int | None:
    raw = (payload or {}).get("amount_paise")
    if raw in (None, ""):
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


class PfmsAdapter(BaseAdapter):
    name = "pfms"
    title = "PFMS payments"
    mode = "mock"
    interface = "payment_status(pfms_ref); list_payments(case_ref)"
    real_target = "PFMS APIs"
    mock_behaviour = (
        "PAID when a PAYMENT_MADE event carries the reference; UNKNOWN otherwise"
    )

    # --- reads --------------------------------------------------------------------

    def payment_status(self, db: Session, pfms_ref: str) -> dict:
        """`{pfms_ref, status, amount_paise, date, ...}` — status from the ledger."""
        ref = (pfms_ref or "").strip()
        if not ref:
            return {
                "pfms_ref": pfms_ref,
                "status": STATUS_UNKNOWN,
                "detail": "no reference supplied",
            }
        row = db.execute(
            select(Event)
            .where(Event.type == PAYMENT_EVENT)
            .where(Event.payload["pfms_ref"].astext == ref)
            .order_by(Event.seq.asc())
            .limit(1)
        ).scalars().first()
        if row is None:
            return {
                "pfms_ref": ref,
                "status": STATUS_UNKNOWN,
                "amount_paise": None,
                "date": None,
                "detail": "no PAYMENT_MADE event in the ledger carries this reference",
                "source": "mock: bhuarjan event ledger",
            }
        payload = row.payload or {}
        return {
            "pfms_ref": ref,
            "status": STATUS_PAID,
            "amount_paise": _amount(payload),
            "date": row.occurred_at.isoformat() if row.occurred_at else None,
            "mode": payload.get("mode"),
            "payee_ref": payload.get("payee_ref"),
            "case_id": str(row.case_id),
            "event_seq": int(row.seq),
            "source": "mock: bhuarjan event ledger",
        }

    def list_payments(self, db: Session, case_ref: str) -> dict:
        """Every payment recorded against a case, addressed by uuid or by case_no."""
        case = self._resolve_case(db, case_ref)
        if case is None:
            return {"case_ref": case_ref, "items": [], "count": 0, "found": False}
        rows = db.scalars(
            select(Event)
            .where(Event.case_id == case.id)
            .where(Event.type == PAYMENT_EVENT)
            .order_by(Event.seq.asc())
        ).all()
        items = [
            {
                "pfms_ref": (r.payload or {}).get("pfms_ref"),
                "status": STATUS_PAID,
                "amount_paise": _amount(r.payload),
                "date": r.occurred_at.isoformat() if r.occurred_at else None,
                "mode": (r.payload or {}).get("mode"),
                "event_seq": int(r.seq),
            }
            for r in rows
        ]
        return {
            "case_ref": case_ref,
            "case_id": str(case.id),
            "case_no": case.case_no,
            "found": True,
            "items": items,
            "count": len(items),
            "total_paise": sum(i["amount_paise"] or 0 for i in items),
        }

    # --- internals ----------------------------------------------------------------

    @staticmethod
    def _resolve_case(db: Session, case_ref: str) -> Case | None:
        ref = (case_ref or "").strip()
        if not ref:
            return None
        try:
            return db.get(Case, uuid.UUID(ref))
        except (ValueError, AttributeError, TypeError):
            pass
        return db.scalars(select(Case).where(Case.case_no == ref).limit(1)).first()

    def _test(self, db: Session | None = None) -> dict:
        if db is None:
            return {"ok": False, "detail": "no database session supplied"}
        count = (
            db.scalar(
                select(func.count()).select_from(Event).where(Event.type == PAYMENT_EVENT)
            )
            or 0
        )
        return {
            "ok": True,
            "detail": (
                f"mock reads the ledger: {count} PAYMENT_MADE event(s) would answer PAID"
            ),
            "payments_in_ledger": int(count),
        }


adapter = register(PfmsAdapter())
