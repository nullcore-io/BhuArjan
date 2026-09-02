"""Dashboard aggregation (Docs/APIs.md §3.10, Docs/Backend.md §8).

Every figure is computed live from the ledger and its projections — `events`,
`case_state`, `clocks`, `parcels`, `compensation_lines` — and stamped with
`as_of_seq = max(events.seq)` over the cases in scope. Docs/rules.md C7 requires
that any figure can be exploded back to the events that produced it, which is what
`explain()` returns.

Where a projection has not been populated yet (fresh database, replay pending), the
KPI falls back to the ledger itself and says so in `sources`. A dashboard that
silently reads zero is worse than one that tells you where its number came from.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AffectedFamily,
    Case,
    CaseState,
    Clock,
    CompensationLine,
    Event,
    OrgUnit,
    Parcel,
    Project,
)

KPI_KEYS = [
    "area_proposed_ha",
    "area_notified_ha",
    "area_acquired_ha",
    "notifications_issued",
    "awards_declared",
    "comp_assessed_paise",
    "comp_paid_paise",
    "possession_pct",
    "rr_progress_pct",
    "families_affected",
    "families_displaced",
    "timeline_adherence_pct",
    "clocks_by_status",
]

NOTIFICATION_EVENTS = ("NOTIFICATION_3A", "PRELIM_NOTIFICATION_S11")
AWARD_EVENTS = ("AWARD_S23", "AWARD_3G")
POSSESSION_EVENTS = ("POSSESSION_TAKEN_S38", "POSSESSION_3E")
ASSESSED_EVENTS = ("COMPENSATION_ASSESSED",)
PAYMENT_EVENTS = ("PAYMENT_MADE",)

# Clock statuses that count as "on time" for timeline adherence.
ADHERENT_STATUSES = ("closed", "running", "extended", "suspended")

FUNNEL_STAGES = [
    "PROPOSED", "SIA", "APPRAISED", "NOTIFIED", "DECLARED",
    "AWARDED", "POSSESSED", "CLOSED", "LAPSED",
]


# --- helpers -----------------------------------------------------------------------


def _scoped(q, case_ids: list[uuid.UUID] | None, column):
    if case_ids is None:
        return q
    if not case_ids:
        return q.where(column.in_([uuid.UUID(int=0)]))  # empty result, valid SQL
    return q.where(column.in_(case_ids))


def _f(value) -> float:
    return round(float(value or 0), 4)


def _i(value) -> int:
    return int(value or 0)


def as_of_seq(db: Session, case_ids: list[uuid.UUID] | None) -> int:
    q = select(func.max(Event.seq))
    return _i(db.scalar(_scoped(q, case_ids, Event.case_id)))


def _event_count(db: Session, case_ids, types: tuple[str, ...]) -> int:
    q = select(func.count()).select_from(Event).where(Event.type.in_(types))
    return _i(db.scalar(_scoped(q, case_ids, Event.case_id)))


def _payload_numeric_sum(db: Session, case_ids, types: tuple[str, ...], key: str) -> float:
    """Sum a numeric field out of the event payloads. Payload values arrive as JSON
    strings for areas (numeric-as-string per Docs/APIs.md §1), so summing happens in
    Python rather than trusting a jsonb cast."""
    q = select(Event.payload).where(Event.type.in_(types))
    rows = db.scalars(_scoped(q, case_ids, Event.case_id)).all()
    total = 0.0
    for payload in rows:
        raw = (payload or {}).get(key)
        if raw in (None, ""):
            continue
        try:
            total += float(raw)
        except (TypeError, ValueError):
            continue
    return total


# --- KPI block ---------------------------------------------------------------------


def kpis(db: Session, case_ids: list[uuid.UUID] | None, today: date) -> dict:
    sources: dict[str, str] = {}

    states = db.scalars(_scoped(select(CaseState), case_ids, CaseState.case_id)).all()
    case_count = _i(db.scalar(_scoped(select(func.count()).select_from(Case), case_ids, Case.id)))

    # --- area -------------------------------------------------------------------
    parcel_area = _f(db.scalar(
        _scoped(select(func.coalesce(func.sum(Parcel.area_ha), 0)), case_ids, Parcel.case_id)
    ))
    notified_projection = _f(sum(float(s.area_notified_ha or 0) for s in states))
    if notified_projection > 0:
        area_notified = notified_projection
        sources["area_notified_ha"] = "case_state"
    else:
        area_notified = _f(_payload_numeric_sum(db, case_ids, NOTIFICATION_EVENTS, "total_area_ha"))
        sources["area_notified_ha"] = "events" if area_notified else "empty"

    acquired_projection = _f(sum(float(s.area_acquired_ha or 0) for s in states))
    if acquired_projection > 0:
        area_acquired = acquired_projection
        sources["area_acquired_ha"] = "case_state"
    else:
        possessed_cases = [
            s.case_id for s in states if (s.stage or "") in ("POSSESSED", "CLOSED")
        ]
        if possessed_cases:
            area_acquired = _f(db.scalar(
                select(func.coalesce(func.sum(Parcel.area_ha), 0))
                .where(Parcel.case_id.in_(possessed_cases))
            ))
            sources["area_acquired_ha"] = "parcels(stage>=POSSESSED)"
        else:
            area_acquired = _f(db.scalar(
                _scoped(select(func.coalesce(func.sum(Parcel.area_ha), 0)),
                        case_ids, Parcel.case_id)
                .where(Parcel.status == "possessed")
            ))
            sources["area_acquired_ha"] = "parcels(status=possessed)"

    area_proposed = parcel_area if parcel_area > 0 else area_notified
    sources["area_proposed_ha"] = "parcels" if parcel_area > 0 else sources["area_notified_ha"]

    # --- compensation ------------------------------------------------------------
    assessed_projection = _i(sum(int(s.comp_assessed_paise or 0) for s in states))
    paid_projection = _i(sum(int(s.comp_paid_paise or 0) for s in states))
    line_assessed = _i(db.scalar(
        _scoped(select(func.coalesce(func.sum(CompensationLine.total_paise), 0)),
                case_ids, CompensationLine.case_id)
    ))
    line_paid = _i(db.scalar(
        _scoped(select(func.coalesce(func.sum(CompensationLine.paid_paise), 0)),
                case_ids, CompensationLine.case_id)
    ))
    if assessed_projection > 0:
        comp_assessed, sources["comp_assessed_paise"] = assessed_projection, "case_state"
    elif line_assessed > 0:
        comp_assessed, sources["comp_assessed_paise"] = line_assessed, "compensation_lines"
    else:
        comp_assessed = _i(_payload_numeric_sum(
            db, case_ids, ASSESSED_EVENTS, "assessed_total_paise"))
        sources["comp_assessed_paise"] = "events" if comp_assessed else "empty"

    if paid_projection > 0:
        comp_paid, sources["comp_paid_paise"] = paid_projection, "case_state"
    elif line_paid > 0:
        comp_paid, sources["comp_paid_paise"] = line_paid, "compensation_lines"
    else:
        comp_paid = _i(_payload_numeric_sum(db, case_ids, PAYMENT_EVENTS, "amount_paise"))
        sources["comp_paid_paise"] = "events" if comp_paid else "empty"

    # --- families ----------------------------------------------------------------
    families_affected = _i(sum(int(s.families_affected or 0) for s in states))
    families_displaced = _i(sum(int(s.families_displaced or 0) for s in states))
    if families_affected == 0:
        families_affected = _i(db.scalar(
            _scoped(select(func.count()).select_from(AffectedFamily),
                    case_ids, AffectedFamily.case_id)
        ))
        sources["families_affected"] = "affected_families"
    else:
        sources["families_affected"] = "case_state"
    if families_displaced == 0:
        families_displaced = _i(db.scalar(
            _scoped(select(func.count()).select_from(AffectedFamily),
                    case_ids, AffectedFamily.case_id)
            .where(AffectedFamily.displaced.is_(True))
        ))

    # --- clocks ------------------------------------------------------------------
    clock_rows = db.execute(
        _scoped(select(Clock.status, func.count()), case_ids, Clock.case_id)
        .group_by(Clock.status)
    ).all()
    clocks_by_status = {status or "unknown": _i(count) for status, count in clock_rows}
    total_clocks = sum(clocks_by_status.values())
    adherent = sum(clocks_by_status.get(s, 0) for s in ADHERENT_STATUSES)
    # A running clock past the red threshold (>=90% elapsed) is not adherent even
    # though it has not breached yet — otherwise a dashboard full of red clocks
    # reports 100% adherence right up to the day the case lapses.
    red_running = 0
    running_rows = db.execute(
        _scoped(select(Clock.start_date, Clock.due_date), case_ids, Clock.case_id)
        .where(Clock.status.in_(("running", "extended")))
    ).all()
    for start, due in running_rows:
        if start and due and due > start:
            elapsed = (today - start).days / (due - start).days
            if elapsed >= 0.90:
                red_running += 1
    adherent = max(adherent - red_running, 0)
    timeline_adherence = round(100.0 * adherent / total_clocks, 2) if total_clocks else 100.0

    # --- derived percentages -----------------------------------------------------
    possession_pct = round(100.0 * area_acquired / area_notified, 2) if area_notified else 0.0
    # Entitlement-head level, the same arithmetic the case's R&R tab shows: delivered
    # heads over all heads across the families in scope. Counting events per family
    # would read 100% once each family had received any one head.
    fam_rows = db.scalars(
        _scoped(select(AffectedFamily.rr_entitlements), case_ids, AffectedFamily.case_id)
    ).all()
    heads_total = heads_delivered = 0
    for ent in fam_rows:
        for row in (ent or {}).values():
            if isinstance(row, dict):
                heads_total += 1
                if row.get("status") == "delivered":
                    heads_delivered += 1
    rr_progress = round(100.0 * heads_delivered / heads_total, 2) if heads_total else 0.0

    return {
        "area_proposed_ha": area_proposed,
        "area_notified_ha": area_notified,
        "area_acquired_ha": area_acquired,
        "notifications_issued": _event_count(db, case_ids, NOTIFICATION_EVENTS),
        "awards_declared": _event_count(db, case_ids, AWARD_EVENTS),
        "comp_assessed_paise": comp_assessed,
        "comp_paid_paise": comp_paid,
        "possession_pct": min(possession_pct, 100.0),
        "rr_progress_pct": rr_progress,
        "families_affected": families_affected,
        "families_displaced": families_displaced,
        "timeline_adherence_pct": timeline_adherence,
        "clocks_by_status": clocks_by_status,
        "case_count": case_count,
        "sources": sources,
    }


# --- series and funnel -------------------------------------------------------------


def monthly_series(db: Session, case_ids: list[uuid.UUID] | None) -> list[dict]:
    """Assessed vs paid by calendar month, from COMPENSATION_ASSESSED / PAYMENT_MADE."""
    rows = db.execute(
        _scoped(
            select(Event.type, Event.occurred_at, Event.payload)
            .where(Event.type.in_(ASSESSED_EVENTS + PAYMENT_EVENTS)),
            case_ids, Event.case_id,
        ).order_by(Event.occurred_at.asc())
    ).all()
    buckets: dict[str, dict] = defaultdict(lambda: {"assessed_paise": 0, "paid_paise": 0})
    for etype, occurred_at, payload in rows:
        month = occurred_at.strftime("%Y-%m")
        payload = payload or {}
        if etype in ASSESSED_EVENTS:
            key, raw = "assessed_paise", payload.get("assessed_total_paise")
        else:
            key, raw = "paid_paise", payload.get("amount_paise")
        try:
            buckets[month][key] += int(float(raw or 0))
        except (TypeError, ValueError):
            continue
    return [
        {"month": m, **buckets[m]} for m in sorted(buckets)
    ]


def stage_funnel(db: Session, case_ids: list[uuid.UUID] | None) -> list[dict]:
    rows = db.execute(
        _scoped(select(CaseState.stage, func.count()), case_ids, CaseState.case_id)
        .group_by(CaseState.stage)
    ).all()
    counts = Counter({stage or "PROPOSED": _i(n) for stage, n in rows})
    if not counts:  # no projection yet — fall back to the ledger's own milestones
        return [
            {"stage": "NOTIFIED", "count": _event_count(db, case_ids, NOTIFICATION_EVENTS)},
            {"stage": "DECLARED",
             "count": _event_count(db, case_ids, ("DECLARATION_S19", "DECLARATION_3D"))},
            {"stage": "AWARDED", "count": _event_count(db, case_ids, AWARD_EVENTS)},
            {"stage": "POSSESSED", "count": _event_count(db, case_ids, POSSESSION_EVENTS)},
        ]
    ordered = [{"stage": s, "count": counts.get(s, 0)} for s in FUNNEL_STAGES]
    for stage, n in counts.items():
        if stage not in FUNNEL_STAGES:
            ordered.append({"stage": stage, "count": n})
    return [row for row in ordered if row["count"] or row["stage"] in FUNNEL_STAGES[:7]]


def top_risk_cases(
    db: Session, case_ids: list[uuid.UUID] | None, today: date, limit: int = 10
) -> list[dict]:
    """Open clocks nearest their due date — the queue an officer actually works."""
    q = (
        select(Clock, Case, Project, OrgUnit)
        .join(Case, Case.id == Clock.case_id)
        .join(Project, Project.id == Case.project_id)
        .outerjoin(OrgUnit, OrgUnit.id == Case.district_id)
        .where(Clock.status.in_(("running", "extended", "breached")))
        .where(Clock.due_date.isnot(None))
    )
    rows = db.execute(
        _scoped(q, case_ids, Clock.case_id).order_by(Clock.due_date.asc()).limit(limit)
    ).all()
    out = []
    for clock, case, project, district in rows:
        days_left = (clock.due_date - today).days if clock.due_date else None
        elapsed_pct = None
        if clock.start_date and clock.due_date and clock.due_date > clock.start_date:
            elapsed_pct = round(
                100.0 * (today - clock.start_date).days
                / (clock.due_date - clock.start_date).days,
                2,
            )
        # Same thresholds the rule-sets use (rules.md C2) so this badge can never
        # disagree with the case page's clock card.
        if clock.status in ("breached", "lapsed"):
            level = clock.status
        elif elapsed_pct is not None and elapsed_pct >= 90:
            level = "red"
        elif elapsed_pct is not None and elapsed_pct >= 75:
            level = "amber"
        else:
            level = "ok"
        out.append({
            "case_id": str(case.id),
            "case_no": case.case_no,
            "project": project.name,
            "statute_track": case.statute_track,
            "district": district.name if district is not None else None,
            "district_id": str(district.id) if district is not None else None,
            "clock_id": clock.clock_id,
            "basis": clock.basis,
            "consequence": clock.consequence,
            "status": clock.status,
            "level": level,
            "elapsed_pct": elapsed_pct,
            "due_date": clock.due_date.isoformat() if clock.due_date else None,
            "days_left": days_left,
        })
    return out


# --- assembled dashboard -----------------------------------------------------------


def dashboard(
    db: Session,
    case_ids: list[uuid.UUID] | None,
    today: date,
    *,
    level: str = "national",
    scope_id: str | None = None,
    filters: dict | None = None,
) -> dict:
    return {
        "level": level,
        "scope_id": scope_id,
        "as_of_seq": as_of_seq(db, case_ids),
        "as_of_date": today.isoformat(),
        "filters": filters or {},
        "kpis": kpis(db, case_ids, today),
        "series": {"assessed_vs_paid_monthly": monthly_series(db, case_ids)},
        "stage_funnel": stage_funnel(db, case_ids),
        "top_risk_cases": top_risk_cases(db, case_ids, today),
    }


# --- explain (Docs/rules.md C7) ----------------------------------------------------

EXPLAIN_KPIS = {
    "comp_assessed": ASSESSED_EVENTS,
    "comp_assessed_paise": ASSESSED_EVENTS,
    "comp_paid": PAYMENT_EVENTS,
    "comp_paid_paise": PAYMENT_EVENTS,
    "area": NOTIFICATION_EVENTS,
    "area_notified_ha": NOTIFICATION_EVENTS,
    "area_proposed_ha": NOTIFICATION_EVENTS,
    "area_acquired_ha": POSSESSION_EVENTS,
    "notifications_issued": NOTIFICATION_EVENTS,
    "awards_declared": AWARD_EVENTS,
}

_CONTRIBUTION_KEY = {
    "COMPENSATION_ASSESSED": ("assessed_total_paise", "paise"),
    "PAYMENT_MADE": ("amount_paise", "paise"),
    "NOTIFICATION_3A": ("total_area_ha", "ha"),
    "PRELIM_NOTIFICATION_S11": ("total_area_ha", "ha"),
    "DECLARATION_3D": ("total_area_ha", "ha"),
    "DECLARATION_S19": ("total_area_ha", "ha"),
}


def explain(db: Session, case_ids: list[uuid.UUID] | None, kpi: str, today: date) -> dict:
    types = EXPLAIN_KPIS.get(kpi)
    if types is None:
        from app.core.problems import Problem

        raise Problem(
            "validation_error", "Validation error", 422,
            f"kpi '{kpi}' cannot be explained; try one of {', '.join(sorted(EXPLAIN_KPIS))}",
        )
    rows = db.execute(
        _scoped(
            select(Event, Case, Project)
            .join(Case, Case.id == Event.case_id)
            .join(Project, Project.id == Case.project_id)
            .where(Event.type.in_(types)),
            case_ids, Event.case_id,
        ).order_by(Event.seq.asc())
    ).all()

    event_ids: list[str] = []
    per_case: dict[uuid.UUID, dict] = {}
    for event, case, project in rows:
        event_ids.append(str(event.id))
        key, unit = _CONTRIBUTION_KEY.get(event.type, (None, None))
        contribution = 0.0
        if key:
            try:
                contribution = float((event.payload or {}).get(key) or 0)
            except (TypeError, ValueError):
                contribution = 0.0
        entry = per_case.setdefault(case.id, {
            "case_id": str(case.id),
            "case_no": case.case_no,
            "project": project.name,
            "statute_track": case.statute_track,
            "state_code": project.state_code,
            "event_ids": [],
            "contribution": 0.0,
            "unit": unit,
        })
        entry["event_ids"].append(str(event.id))
        entry["contribution"] = round(entry["contribution"] + contribution, 4)

    return {
        "kpi": kpi,
        "as_of_seq": as_of_seq(db, case_ids),
        "as_of_date": today.isoformat(),
        "event_types": list(types),
        "event_ids": event_ids,
        "cases": list(per_case.values()),
    }
