"""Clock closers that are a *state of the case*, not a single event.

`ends_on: X` closes a clock when any one event of type X is in the ledger. That is the
right reading for most statutory deadlines — one s.19 declaration closes the s.19(7)
clock — but it is the wrong reading for the two s.38(1) R&R clocks, whose obligation is
per family and per Second/Third Schedule head. Wiring `RR_MONETARY_6M` to
`ends_on: RR_ENTITLEMENT_DELIVERED` meant delivering one allowance to one family
reported statutory compliance for every family on the case, next to a 3% delivery rate.
The mirror image was `RR_INFRA_18M`, which had no `ends_on` at all and so could never
close: delivering every head to every family still left a permanent `breached` alert
that no action could clear.

So a `ClockSpec` may name a predicate instead: `ends_when: rr_monetary_complete`. A
predicate answers `(satisfied, satisfied_on)`; `satisfied_on` is the date the obligation
was actually discharged — the latest delivery — so the in-time rule in
`app.domain.rules.clocks` still applies and a delivery made after the six months is
still a breach.

**Applicability.** `SECOND_SCHEDULE[...]["applies_to"]` is advisory metadata for the
screen (see `app.domain.rr.schedules`) — every head starts `due` on every family, and
an officer's determination that a head does not apply belongs in the ledger. Here it is
read for one narrow purpose: deciding what "complete" means for a *clock*. A head the
Schedule confines to displaced families is not owed to a family that is not being
displaced, and `land_for_land` is confined to irrigation projects, so requiring them
would leave the clock breached for ever on cases that owe nothing.

**No families enumerated is not completion.** A case with no census has an
*undetermined* obligation, not a discharged one, so the clock keeps running. Closing it
would report compliance on the one case that has not started.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.rr.schedules import SECOND_SCHEDULE, normalise_entitlements
from app.models import AffectedFamily, Case, Project

log = logging.getLogger(__name__)

# s.38(1): the money, the land allotment and the employment/annuity choice run to six
# months from the award. The Third Schedule amenities have their own 18-month proviso.
MONETARY_KINDS = ("monetary", "land", "employment")
INFRA_KINDS = ("infra",)


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _sector(db: Session, case: Case) -> str:
    return str(
        db.scalar(select(Project.sector).where(Project.id == case.project_id)) or ""
    ).lower()


def _applies(head: dict, *, displaced: bool, irrigation: bool) -> bool:
    applies_to = str(head.get("applies_to") or "all").lower()
    if applies_to == "displaced":
        return displaced
    if applies_to == "irrigation":
        return irrigation
    # "all", and anything the Schedule grows later: an unrecognised marker is not a
    # licence to drop a head out of the obligation.
    return True


def live_families(db: Session, case: Case) -> list[AffectedFamily]:
    """The case's affected families, minus the enumerations that were reversed."""
    return list(
        db.scalars(
            select(AffectedFamily).where(
                AffectedFamily.case_id == case.id,
                AffectedFamily.withdrawn_at.is_(None),
            )
        ).all()
    )


def _complete(
    db: Session,
    case: Case,
    today: date,
    kinds: tuple[str, ...],
    *,
    by_applicability: bool,
) -> tuple[bool, date | None]:
    families = live_families(db, case)
    if not families:
        return False, None

    irrigation = "irrigation" in _sector(db, case)
    latest: date | None = None
    for family in families:
        displaced = bool(family.displaced)
        entitlements = normalise_entitlements(family.rr_entitlements)
        for head in SECOND_SCHEDULE:
            if head["kind"] not in kinds:
                continue
            if by_applicability and not _applies(
                head, displaced=displaced, irrigation=irrigation
            ):
                continue
            row = entitlements.get(head["head"]) or {}
            when = _as_date(row.get("delivered_on"))
            # A delivery dated after the evaluation date has not happened yet as far as
            # this evaluation is concerned — the demo clock must be able to look back.
            if row.get("status") != "delivered" or when is None or when > today:
                return False, None
            if latest is None or when > latest:
                latest = when
    return (latest is not None), latest


def rr_monetary_complete(db: Session, case: Case, today: date) -> tuple[bool, date | None]:
    """s.38(1): every applicable monetary / land / employment head, every live family."""
    return _complete(db, case, today, MONETARY_KINDS, by_applicability=True)


def rr_infra_complete(db: Session, case: Case, today: date) -> tuple[bool, date | None]:
    """s.38(1) proviso: the Third Schedule amenities, for every live family.

    Applicability is not consulted here: the amenities are delivered to a resettlement
    *site*, so the obligation is discharged for the case only once every enumerated
    family has been recorded as served by it.
    """
    return _complete(db, case, today, INFRA_KINDS, by_applicability=False)


PREDICATES = {
    "rr_monetary_complete": rr_monetary_complete,
    "rr_infra_complete": rr_infra_complete,
}


def evaluate_predicate(
    name: str, db: Session, case: Case, today: date
) -> tuple[bool, date | None]:
    """Run one named predicate. An unknown name fails closed and says so — a rule-set
    typo must never silently close a statutory clock."""
    fn = PREDICATES.get(name)
    if fn is None:
        log.error(
            "clock predicate %r is not implemented (known: %s); the clock stays open",
            name, ", ".join(sorted(PREDICATES)),
        )
        return False, None
    return fn(db, case, today)
