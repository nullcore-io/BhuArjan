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
    """Scheduler entrypoint — own session; evaluates every open case with today=date.today()."""
    from app.core.db import SessionLocal

    today = date.today()
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
