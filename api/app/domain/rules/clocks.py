"""Statutory clock engine (Docs/Backend.md §5, Docs/rules.md C2).

For every `ClockSpec` in the case's pinned rule-set:

    start = occurred_at of the first `starts_on` event
    due   = start + duration            (calendar months per General Clauses Act s.3(35))
            overridden by the latest EXTENSION_GRANTED `new_due_date`
            + suspended_days accumulated from vacated court stays

    closed     the `ends_on` event exists with occurred_at <= min(today, due), or the
               `ends_when` predicate (app.domain.rules.predicates) is satisfied by then
    suspended  a COURT_STAY affecting this clock has no matching STAY_VACATED
    breached   today > due, and `on_breach` only marks
    lapsed     today > due, and `on_breach` emits consequence events
    extended   an extension is in force and the clock is otherwise running
    running    everything else

Closure is conditioned on the terminating event being *in time*: an award recorded six
months after the s.25 deadline does not un-lapse proceedings that have already lapsed,
and treating it as a closure would make late recording the way to erase a statutory
consequence.

`kind: window` clocks (the s.15 objection window, 3C) are public windows, not
deadlines on an officer: they close silently at their due date and never alert.

Consequence events (`on_breach: {emit: X, then: Y}`) are appended through the ordinary
`append_event` path as the SYSTEM actor with `occurred_at = due_date`, so a lapse is in
the hash chain like everything else and can be audited. Re-entry is blocked per case and
per thread, and the evaluation then re-runs so the newly-lapsed stage is visible in one
call. A consequence the rule-set does not allow from the case's current stage is refused
and raised as an `INTEGRITY` alert rather than forced through.
"""

from __future__ import annotations

import calendar
import logging
import threading
import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.rules.loader import ClockSpec, Ruleset
from app.models import AdminAudit, Alert, Case, Clock, Event, User

log = logging.getLogger(__name__)

SYSTEM_EMAIL = "system@bhuarjan.gov.in"
SYSTEM_NAME = "BhuArjan clock engine"

DEFAULT_THRESHOLDS = {"amber": 0.75, "red": 0.90}
OPEN_STATUSES = ("running", "extended", "suspended")
MAX_PASSES = 4  # one pass per cascade step; {emit, then} needs two

# The pseudo-clock integrity failures are filed under, so a chain mismatch or a refused
# consequence reaches a human through the same alert centre as a statutory breach.
INTEGRITY_CLOCK_ID = "INTEGRITY"

# Cases whose clocks are being evaluated right now, per thread. `append_event` consults
# this so a consequence event cannot recurse back into the engine mid-flight. It is
# thread-local on purpose: a module-level set would let the hourly sweep, running in the
# scheduler's own thread, suppress clock evaluation inside an officer's append and hand
# them a case page showing a running clock that has legally lapsed.
_EVALUATING = threading.local()


def _evaluating() -> set[uuid.UUID]:
    cases = getattr(_EVALUATING, "cases", None)
    if cases is None:
        cases = set()
        _EVALUATING.cases = cases
    return cases


def is_evaluating(case_id: uuid.UUID) -> bool:
    return case_id in _evaluating()


# --- date arithmetic ---------------------------------------------------------------


def add_months(start: date, months: int) -> date:
    """Same day of the target month; the last day of that month when it does not
    exist (General Clauses Act 1897 s.3(35) — a British calendar month)."""
    if not months:
        return start
    total = (start.year * 12 + (start.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_duration(start: date, duration: dict | None) -> date:
    duration = duration or {}
    months = int(duration.get("months") or 0) + 12 * int(duration.get("years") or 0)
    out = add_months(start, months)
    days = int(duration.get("days") or 0) + 7 * int(duration.get("weeks") or 0)
    return out + timedelta(days=days) if days else out


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


# --- system actor ------------------------------------------------------------------


def system_user(db: Session) -> User:
    """The actor consequence events are recorded under. Created on first use so a
    lapse is never attributed to whichever officer happened to be logged in."""
    user = db.scalar(select(User).where(User.email == SYSTEM_EMAIL))
    if user is None:
        user = User(email=SYSTEM_EMAIL, name=SYSTEM_NAME, password_hash="", active=False)
        db.add(user)
        db.flush()
    return user


# --- ledger view -------------------------------------------------------------------


def _load_events(db: Session, case_id: uuid.UUID) -> list[Event]:
    return list(
        db.scalars(
            select(Event).where(Event.case_id == case_id).order_by(Event.seq.asc())
        ).all()
    )


def _affects(event: Event, clock_id: str) -> bool:
    """A COURT_STAY / STAY_VACATED may name the clocks it touches; when it does not,
    it touches every clock that declares the event in `suspend_on` — which is how the
    caller already selected it."""
    affected = (event.payload or {}).get("affected_clocks")
    if isinstance(affected, list) and affected:
        return clock_id in affected
    return True


def _suspension(
    spec: ClockSpec, events: list[Event], start: date, today: date
) -> tuple[int, date | None]:
    """(suspended_days from closed stays, start date of the earliest open stay).

    Court orders are read in `occurred_at` order, not `seq` order, because a stay and
    the order vacating it are routinely back-filled out of sequence — recording the
    vacation first and the stay it vacated afterwards used to leave a clock suspended
    for ever. Stays pair as a stack: a vacation closes the most recent open stay, so a
    second writ still holds the clock after the first is lifted.

    Each closed interval is clipped to the clock's own life `[start, today]`, so a stay
    that began before the clock started still credits from the clock's start date; the
    clipped intervals are then unioned, so two concurrent writs over the same weeks are
    counted once. An interval that is still open credits nothing yet — it suspends the
    clock instead, and is paid out when the court vacates it.
    """
    if not spec.suspend_on:
        return 0, None
    resume_on = list(spec.resume_on or [])

    orders = [
        ev
        for ev in events
        if (ev.type in spec.suspend_on or ev.type in resume_on)
        and ev.occurred_at <= today
        and _affects(ev, spec.id)
    ]
    orders.sort(key=lambda e: (e.occurred_at, e.seq))

    open_stack: list[date] = []
    intervals: list[tuple[date, date]] = []
    for ev in orders:
        if ev.type in spec.suspend_on:
            open_stack.append(ev.occurred_at)
        elif open_stack:
            intervals.append((open_stack.pop(), ev.occurred_at))

    clipped = sorted(
        (max(a, start), min(b, today))
        for a, b in intervals
        if min(b, today) > max(a, start)
    )
    days = 0
    span_from: date | None = None
    span_to: date | None = None
    for a, b in clipped:
        if span_to is None or a > span_to:
            if span_to is not None:
                days += (span_to - span_from).days
            span_from, span_to = a, b
        elif b > span_to:
            span_to = b
    if span_to is not None:
        days += (span_to - span_from).days

    return days, (min(open_stack) if open_stack else None)


def _extension(spec: ClockSpec, events: list[Event], today: date) -> date | None:
    """The `new_due_date` of the most recent EXTENSION_GRANTED naming this clock."""
    latest: date | None = None
    for ev in events:
        if ev.type != "EXTENSION_GRANTED" or ev.occurred_at > today:
            continue
        payload = ev.payload or {}
        if str(payload.get("clock_id") or "") != spec.id:
            continue
        new_due = _as_date(payload.get("new_due_date"))
        if new_due is not None:
            latest = new_due
    return latest


# --- alerts ------------------------------------------------------------------------


def _thresholds(rs: Ruleset) -> dict:
    raw = (rs.alerts or {}).get("thresholds") or {}
    return {
        "amber": float(raw.get("amber", DEFAULT_THRESHOLDS["amber"])),
        "red": float(raw.get("red", DEFAULT_THRESHOLDS["red"])),
    }


def _raise_alert(db: Session, rs: Ruleset, case_id: uuid.UUID, clock_id: str, level: str) -> bool:
    """Dedupe per (case, clock, level) — Docs/Backend.md §9."""
    existing = db.scalar(
        select(Alert.id)
        .where(Alert.case_id == case_id, Alert.clock_id == clock_id, Alert.level == level)
        .limit(1)
    )
    if existing is not None:
        return False
    role = ((rs.alerts or {}).get("escalation") or {}).get(level)
    db.add(Alert(case_id=case_id, clock_id=clock_id, level=level, escalated_to_role=role))
    db.flush()
    return True


def raise_integrity_alert(
    db: Session,
    case_id: uuid.UUID,
    detail: str,
    *,
    action: str = "integrity_mismatch",
    meta: dict | None = None,
    role: str = "STATE_REVENUE",
) -> bool:
    """File an integrity failure where a human will see it: an alert row under the
    `INTEGRITY` pseudo-clock, deduped per case exactly like a clock alert, and an
    admin-audit line deduped per (action, case) — separately, so a chain mismatch still
    leaves its own audit trail on a case that already carries an alert for some other
    integrity failure. Returns True when anything was written."""
    written = False

    alert_exists = db.scalar(
        select(Alert.id)
        .where(
            Alert.case_id == case_id,
            Alert.clock_id == INTEGRITY_CLOCK_ID,
            Alert.level == "breached",
        )
        .limit(1)
    )
    if alert_exists is None:
        db.add(
            Alert(
                case_id=case_id,
                clock_id=INTEGRITY_CLOCK_ID,
                level="breached",
                escalated_to_role=role,
            )
        )
        written = True

    audit_exists = db.scalar(
        select(AdminAudit.seq)
        .where(AdminAudit.action == action, AdminAudit.target == str(case_id))
        .limit(1)
    )
    if audit_exists is None:
        db.add(
            AdminAudit(
                action=action,
                target=str(case_id),
                meta={"detail": detail, **(meta or {})},
            )
        )
        written = True

    if written:
        db.flush()
    return written


# --- the engine --------------------------------------------------------------------


def _clock_dict(row: Clock, spec: ClockSpec | None = None) -> dict:
    return {
        "clock_id": row.clock_id,
        "status": row.status,
        "basis": row.basis,
        "consequence": row.consequence,
        "kind": row.kind,
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "original_due_date": (
            row.original_due_date.isoformat() if row.original_due_date else None
        ),
        "closed_on": row.closed_on.isoformat() if row.closed_on else None,
        "suspended_days": int(row.suspended_days or 0),
        "elapsed_pct": float(row.elapsed_pct) if row.elapsed_pct is not None else None,
        "extendable": row.extendable if row.extendable is not None else (
            spec.extendable if spec else None
        ),
    }


def _evaluate_once(db: Session, case: Case, rs: Ruleset, today: date) -> tuple[list[dict], bool]:
    from app.domain.cases.projections import reversed_event_ids
    from app.domain.rules.predicates import evaluate_predicate

    events = _load_events(db, case.id)
    by_type: dict[str, list[Event]] = defaultdict(list)
    for ev in events:
        by_type[ev.type].append(ev)
    # An event an EVENT_REVERSED has withdrawn is not a fact any more, so it cannot
    # close a clock: a COMPENSATION_PAID_FULL left standing after its payment was
    # reversed kept the s.38(1) COMPENSATION_3M clock reading `closed` on a case with
    # nothing paid.
    withdrawn = reversed_event_ids(db, case.id)

    rows = {
        row.clock_id: row
        for row in db.scalars(select(Clock).where(Clock.case_id == case.id)).all()
    }
    thresholds = _thresholds(rs)
    changed: list[dict] = []
    emitted = False

    for spec in rs.clocks:
        starters = [e for e in by_type.get(spec.starts_on, []) if e.occurred_at <= today]
        if not starters:
            continue  # the clock has not started; there is nothing to project yet
        start_ev = starters[0]
        start = start_ev.occurred_at

        base_due = add_duration(start, spec.duration)
        extension_due = _extension(spec, events, today)
        suspended_days, open_stay = _suspension(spec, events, start, today)
        due = (extension_due or base_due) + timedelta(days=suspended_days)

        closing = (
            [
                e
                for e in by_type.get(spec.ends_on, [])
                if e.occurred_at <= today and e.id not in withdrawn
            ]
            if spec.ends_on
            else []
        )

        # Only an `ends_on` event recorded *by* the due date closes the clock. An award
        # made six months after the s.25 deadline does not un-lapse the proceedings, and
        # accepting it as a closure would make late recording the way to erase a
        # statutory consequence.
        in_time = [e for e in closing if e.occurred_at <= due]

        # `ends_when` closes on a state of the case rather than on one event — the R&R
        # obligation is per family per head, so no single event discharges it. The
        # in-time rule is the same: the date the obligation was actually completed must
        # fall on or before the due date.
        satisfied_on = None
        if spec.ends_when:
            satisfied, when = evaluate_predicate(spec.ends_when, db, case, today)
            if satisfied and when is not None and when <= due:
                satisfied_on = when

        status = "running"
        closed_on = None
        closed_seq = None
        if in_time:
            status = "closed"
            closed_on = in_time[0].occurred_at
            closed_seq = in_time[0].seq
        elif satisfied_on is not None:
            status = "closed"
            closed_on = satisfied_on
        elif spec.kind == "window" and today > due:
            # A public window simply expires. Nobody is in default; no alert.
            status = "closed"
            closed_on = due
        elif open_stay is not None:
            status = "suspended"
        elif today > due:
            status = "lapsed" if (spec.on_breach or {}).get("emit") else "breached"
        elif extension_due is not None:
            status = "extended"

        span = max(1, (due - start).days)
        elapsed_pct = round(min(100.0, max(0.0, 100.0 * (today - start).days / span)), 2)
        if status == "closed" and closed_on:
            elapsed_pct = round(
                min(100.0, max(0.0, 100.0 * (closed_on - start).days / span)), 2
            )

        row = rows.get(spec.id)
        created = row is None
        if created:
            row = Clock(case_id=case.id, clock_id=spec.id)
            db.add(row)
            rows[spec.id] = row
        before = (row.status, row.start_date, row.due_date, row.closed_on)

        row.basis = spec.basis
        row.consequence = spec.consequence
        row.kind = spec.kind
        row.extendable = spec.extendable
        row.started_seq = start_ev.seq
        row.start_date = start
        row.original_due_date = base_due
        row.extended_due_date = extension_due
        row.due_date = due
        row.suspended_days = suspended_days
        row.stay_started_on = open_stay
        row.status = status
        row.closed_on = closed_on
        row.closed_seq = closed_seq
        row.elapsed_pct = elapsed_pct
        db.flush()

        after = (row.status, row.start_date, row.due_date, row.closed_on)
        if created or before != after:
            changed.append(_clock_dict(row, spec))

        # --- alerts ---------------------------------------------------------
        if spec.kind != "window":
            if status in ("breached", "lapsed"):
                _raise_alert(db, rs, case.id, spec.id, status)
            elif status in ("running", "extended"):
                fraction = elapsed_pct / 100.0
                if fraction >= thresholds["red"]:
                    _raise_alert(db, rs, case.id, spec.id, "red")
                elif fraction >= thresholds["amber"]:
                    _raise_alert(db, rs, case.id, spec.id, "amber")

        # --- on_breach consequences -----------------------------------------
        if status == "lapsed":
            on_breach = spec.on_breach or {}
            sequence = [on_breach.get("emit"), on_breach.get("then")]
            for consequence in [c for c in sequence if c]:
                if by_type.get(consequence):
                    continue  # already in the ledger; a lapse happens once
                if _emit_consequence(db, case, spec, consequence, due, today):
                    emitted = True

    return changed, emitted


def _emit_consequence(
    db: Session, case: Case, spec: ClockSpec, event_type: str, due: date, today: date
) -> bool:
    """Append one `on_breach` consequence as the SYSTEM actor. Returns True when it
    actually entered the ledger.

    A consequence the rule-set does not allow from the case's current stage is refused
    rather than forced: forcing it produced cases sitting in LAPSED with no legal way
    back. The refusal is logged at error level and raised as an integrity alert, because
    a clock that has lapsed with no consequence recorded needs a human, not silence.
    """
    from app.core.problems import Problem
    from app.domain.events.service import append_event

    actor = system_user(db)
    try:
        append_event(
            db,
            case,
            event_type,
            due,
            actor.id,
            {
                "auto": True,
                "reason": spec.basis or spec.id,
                "clock_id": spec.id,
                "consequence": spec.consequence,
                "breached_on": due.isoformat(),
            },
            idempotency_key=f"clock:{case.id}:{spec.id}:{event_type}:{due.isoformat()}",
            today=today,
            system=True,
        )
    except Problem as exc:
        if exc.type != "transition_not_allowed":
            log.exception(
                "clock %s on case %s: could not emit consequence %s",
                spec.id, case.id, event_type,
            )
            raise
        log.error(
            "clock %s on case %s lapsed on %s, but the consequence %s is not available "
            "from the case's current stage — refusing to apply it (%s)",
            spec.id, case.id, due, event_type, exc.detail,
        )
        raise_integrity_alert(
            db,
            case.id,
            f"clock {spec.id} lapsed on {due.isoformat()} but its consequence "
            f"{event_type} is not available from the case's current stage: {exc.detail}",
            action="consequence_refused",
            meta={
                "clock_id": spec.id,
                "event_type": event_type,
                "breached_on": due.isoformat(),
                "ruleset_ref": exc.ruleset_ref,
            },
        )
        return False
    except Exception:
        log.exception(
            "clock %s on case %s: could not emit consequence %s", spec.id, case.id, event_type
        )
        raise
    log.info(
        "clock %s on case %s breached on %s -> emitted %s",
        spec.id, case.id, due, event_type,
    )
    return True


def evaluate(db: Session, case: Case, today: date, ruleset: Ruleset | None = None) -> list[dict]:
    """Evaluate every clock of one case as of `today`. Returns the clocks that moved."""
    from app.domain.cases.projections import update_risk_score
    from app.domain.rules.engine import resolve_ruleset

    running = _evaluating()
    if case.id in running:
        return []
    rs = ruleset or resolve_ruleset(case)

    running.add(case.id)
    try:
        merged: dict[str, dict] = {}
        for _ in range(MAX_PASSES):
            changed, emitted = _evaluate_once(db, case, rs, today)
            for row in changed:
                merged[row["clock_id"]] = row
            if not emitted:
                break
        else:
            log.warning("clock cascade on case %s did not settle in %s passes", case.id, MAX_PASSES)
    finally:
        running.discard(case.id)

    update_risk_score(db, case.id)
    return list(merged.values())


def clock_rows(db: Session, case_id: uuid.UUID) -> list[Clock]:
    return list(
        db.scalars(
            select(Clock).where(Clock.case_id == case_id).order_by(Clock.due_date.asc())
        ).all()
    )


def clock_view(row: Clock) -> dict:
    """Docs/APIs.md §3.3 shape for `GET /cases/{id}/clocks`."""
    return _clock_dict(row)
