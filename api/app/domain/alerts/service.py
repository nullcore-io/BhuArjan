"""Clock evaluation + alert raising (Docs/Backend.md §5 and §9).

The arithmetic lives in `app.domain.rules.clocks`; this module is the seam the rest of
the system calls through — the scheduler, the seed, and the case read endpoints.
Alerts are deduped per `(case, clock_id, level)` by the engine itself.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import ist_today
from app.models import Case, CaseState

log = logging.getLogger(__name__)

# A case in one of these stages has nothing left to run.
TERMINAL_STAGES = ("LAPSED", "CLOSED")


def evaluate_case_clocks(db: Session, case: Case, today: date) -> list[dict]:
    """Evaluate all clocks of one case per Docs/Backend.md §5; raise/dedupe alerts;
    apply on_breach consequences as system actor. Returns changed clocks."""
    from app.domain.rules.clocks import evaluate

    return evaluate(db, case, today)


def evaluate_all_clocks() -> None:
    """Scheduler entrypoint — own session; evaluates every open case as of today in IST."""
    from app.core.db import SessionLocal

    today = ist_today()
    evaluated = 0
    skipped = 0
    failed = 0
    with SessionLocal() as db:
        cases = db.scalars(
            select(Case)
            .outerjoin(CaseState, CaseState.case_id == Case.id)
            .where(
                (CaseState.stage.is_(None)) | (CaseState.stage.notin_(TERMINAL_STAGES))
            )
        ).all()
        for case in cases:
            try:
                evaluate_case_clocks(db, case, today)
                db.commit()
                evaluated += 1
            except Exception:
                db.rollback()
                failed += 1
                log.exception("clock evaluation failed for case %s", case.id)
    log.info(
        "clock sweep %s: evaluated=%s skipped=%s failed=%s",
        today.isoformat(), evaluated, skipped, failed,
    )


# --- nightly chain re-verification (Docs/rules.md C1, Docs/Backend.md §4) -----------


def verify_all_chains() -> dict:
    """Re-verify every case's hash chain and raise an integrity alert on any mismatch.

    Docs/rules.md C1 promises the ledger is *tamper-evident*, which is only true if
    something looks. An officer never opens `GET /cases/{id}/integrity` for a case
    somebody quietly edited, so this runs nightly on every case and files what it finds
    where the alert centre shows it. Returns a small summary for the log and for tests.
    """
    from app.core.db import SessionLocal
    from app.domain.events.service import verify_case_chain
    from app.domain.rules.clocks import raise_integrity_alert

    checked = 0
    failed: list[str] = []
    with SessionLocal() as db:
        case_ids = list(db.scalars(select(Case.id)).all())
        for case_id in case_ids:
            try:
                result = verify_case_chain(db, case_id)
                checked += 1
                if result["verified"]:
                    continue
                failed.append(str(case_id))
                log.error(
                    "chain integrity: case %s failed verification at seq %s — %s",
                    case_id, result["first_bad_seq"], result["reason"],
                )
                raise_integrity_alert(
                    db,
                    case_id,
                    result["reason"] or "hash chain verification failed",
                    action="chain_verification_failed",
                    meta={
                        "first_bad_seq": result["first_bad_seq"],
                        "events_checked": result["events_checked"],
                    },
                )
                db.commit()
            except Exception:
                db.rollback()
                log.exception("chain verification failed for case %s", case_id)
    log.info("chain integrity sweep: checked=%s failed=%s", checked, len(failed))
    return {"checked": checked, "failed": failed}
