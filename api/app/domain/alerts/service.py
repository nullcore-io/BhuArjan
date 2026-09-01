"""Clock evaluation + alert raising. Interface frozen; implementation by build lane B1
(clock evaluation lives with the clock engine; alert dedupe per (case, clock, level))."""

from datetime import date

from sqlalchemy.orm import Session

from app.models import Case


def evaluate_case_clocks(db: Session, case: Case, today: date) -> list[dict]:
    """Evaluate all clocks of one case per Docs/Backend.md §5; raise/dedupe alerts;
    apply on_breach consequences as system actor. Returns changed clocks."""
    raise NotImplementedError("build lane B1")


def evaluate_all_clocks() -> None:
    """Scheduler entrypoint — own session; evaluates every open case with today=date.today()."""
    raise NotImplementedError("build lane B1")
