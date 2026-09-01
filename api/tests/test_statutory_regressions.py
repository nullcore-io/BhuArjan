"""Regressions from the adversarial review of the statutory core.

Every test here is one way the engine could be made to say something untrue about the
Act, reproduced before it was fixed. They are grouped by the thing that was wrong:

    s.38 gate        possession on an award nobody assessed
    court stays      stays dropped, double-counted, or read out of order
    late closure     an award recorded after the s.25 deadline erasing the lapse
    consequences     a lapse dragging a case into a stage the rule-set forbids
    extensions       EXTENSION_GRANTED moving deadlines it may not move
    the ledger       a truncated tail verifying clean
    idempotency      one key buying two different statutory events
    pinning          a case re-evaluated under a rule-set it was not filed under
    the calendar     the statutory day being the container's, not India's
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from tests.conftest import stage_of
from tests.helpers import (
    S11_DEFAULT,
    clocks_on,
    event_types,
    satisfy_s19_preconditions,
    walk_to_awarded,
    walk_to_declared,
    walk_to_notified,
)

DAY_366 = S11_DEFAULT + timedelta(days=366)  # 2026-01-02
S19_DUE = date(2026, 1, 1)  # PRELIM_NOTIFICATION_S11 2025-01-01 + 12 months


def _alerts(client, case, headers) -> list[dict]:
    res = client.get(f"/api/v1/alerts?case_id={case.id}", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["items"]


def _integrity(client, case, headers) -> dict:
    res = client.get(f"/api/v1/cases/{case.id}/integrity", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


# --- the s.38 possession gate ------------------------------------------------------


def test_possession_is_refused_when_nothing_has_ever_been_assessed(
    db, world, client, auth, must_record, record
):
    """`paid >= assessed` was `0 >= 0`, so a case that never recorded
    COMPENSATION_ASSESSED walked straight into POSSESSED with nothing paid."""
    case = world.case(db)
    walk_to_declared(must_record, case)
    must_record(case, "AWARD_S23", date(2025, 7, 30), {"award_no": "AWD/9"})
    assert stage_of(db, case) == "AWARDED"

    status, body = record(case, "POSSESSION_TAKEN_S38", date(2025, 8, 10), {})
    assert status == 422, body
    assert body["type"] == "guard_failed"
    assert "assessed" in body["detail"]
    assert stage_of(db, case) == "AWARDED"

    # s.40 urgency does not help either: 0 is not 80% of an award nobody valued.
    must_record(case, "URGENCY_S40_INVOKED", date(2025, 8, 11), {"order_ref": "URG/9"})
    status, body = record(case, "POSSESSION_TAKEN_S38", date(2025, 8, 12), {})
    assert status == 422, body
    assert body["type"] == "guard_failed"

    # The rule-set says the same thing before the officer tries.
    allowed = client.get(
        f"/api/v1/cases/{case.id}/allowed-events", headers=auth(world.lao)
    ).json()["items"]
    possession = next(a for a in allowed if a["type"] == "POSSESSION_TAKEN_S38")
    assert possession["guard_status"]["ok"] is False


def test_an_enhanced_award_closes_the_gate_again(
    db, world, client, auth, must_record, record
):
    """s.64: the Authority enhances the award after it was paid in full. The gate used
    to stay latched open on the COMPENSATION_PAID_FULL marker; it must not."""
    case = world.case(db)
    award_on, assessed = walk_to_awarded(must_record, case)
    must_record(
        case, "PAYMENT_MADE", award_on + timedelta(days=10),
        {"pfms_ref": "PFMS/1", "amount_paise": assessed, "mode": "PFMS"},
    )
    must_record(case, "COMPENSATION_PAID_FULL", award_on + timedelta(days=11), {})

    # Enhanced five-fold on a s.64 reference.
    must_record(case, "REFERENCE_FILED_S64", award_on + timedelta(days=20), {"ref": "LA/7"})
    must_record(
        case, "COMPENSATION_ASSESSED", award_on + timedelta(days=30),
        {"assessed_total_paise": assessed * 5, "line_count": 1},
    )

    status, body = record(case, "POSSESSION_TAKEN_S38", award_on + timedelta(days=40), {})
    assert status == 422, body
    assert body["type"] == "guard_failed"
    assert body["errors"][0]["comp_assessed_paise"] == assessed * 5
    assert body["errors"][0]["comp_paid_paise"] == assessed
    assert stage_of(db, case) == "AWARDED"


# --- court stays -------------------------------------------------------------------


def test_a_stay_that_began_before_the_clock_started_still_credits_from_the_start(
    db, world, client, auth, must_record
):
    """The stay ran from before the s.19 declaration to well after it. Every day of it
    that fell inside the s.25 clock's life is excluded — the days before the clock
    started are not, because there was no clock to stop."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    must_record(
        case, "COURT_STAY", date(2025, 3, 1),
        {"court": "High Court", "case_no": "WP 9/2025"},
    )
    satisfy_s19_preconditions(must_record, case, S11_DEFAULT + timedelta(days=120))
    declared_on = date(2025, 6, 30)
    must_record(case, "DECLARATION_S19", declared_on, {"gazette_no": "S.O. 2(E)"})
    vacated_on = date(2026, 1, 1)
    must_record(case, "STAY_VACATED", vacated_on, {"court": "High Court"})

    credited = (vacated_on - declared_on).days  # 185: from the clock's own start
    clocks = clocks_on(client, case, auth(world.lao, date(2026, 12, 1)))
    award = clocks["AWARD_S23"]
    assert award["suspended_days"] == credited
    assert award["original_due_date"] == "2026-06-30"
    assert award["due_date"] == (date(2026, 6, 30) + timedelta(days=credited)).isoformat()
    assert award["status"] == "running", award
    assert stage_of(db, case) == "DECLARED"
    assert "CASE_LAPSED" not in event_types(client, case, auth(world.lao))


def test_vacating_one_of_two_writs_does_not_resume_the_clock(
    db, world, client, auth, must_record
):
    """A High Court stay and a Supreme Court stay run concurrently; only the first is
    vacated. The second stay used to be dropped on the floor and the clock resumed."""
    case = world.case(db)
    walk_to_declared(must_record, case)  # AWARD_S23 starts 2025-06-30

    must_record(case, "COURT_STAY", date(2025, 8, 1), {"court": "High Court"})
    must_record(case, "COURT_STAY", date(2025, 9, 1), {"court": "Supreme Court"})
    must_record(case, "STAY_VACATED", date(2025, 10, 1), {"court": "High Court"})

    clocks = clocks_on(client, case, auth(world.lao, date(2026, 8, 1)))
    award = clocks["AWARD_S23"]
    assert award["status"] == "suspended", award
    assert award["suspended_days"] == 30  # only the closed interval is paid out yet
    assert stage_of(db, case) == "DECLARED"
    assert "CASE_LAPSED" not in event_types(client, case, auth(world.lao))


def test_a_back_filled_stay_recorded_after_its_vacation_is_still_paired(
    db, world, client, auth, must_record
):
    """The documented back-fill workflow: the vacation order is entered first and the
    stay it vacated afterwards. Read in `seq` order the vacation was ignored and the
    clock stayed suspended for ever; read in `occurred_at` order the pair closes."""
    case = world.case(db)
    declared_on = walk_to_declared(must_record, case)  # 2025-06-30
    assert declared_on == date(2025, 6, 30)

    must_record(case, "STAY_VACATED", date(2025, 9, 1), {"court": "High Court"})
    must_record(case, "COURT_STAY", date(2025, 6, 1), {"court": "High Court"})

    credited = (date(2025, 9, 1) - declared_on).days  # clipped to the clock's start
    clocks = clocks_on(client, case, auth(world.lao, date(2026, 8, 1)))
    award = clocks["AWARD_S23"]
    assert award["status"] == "running", award
    assert award["suspended_days"] == credited
    assert award["due_date"] == (date(2026, 6, 30) + timedelta(days=credited)).isoformat()


def test_a_declaration_under_a_live_stay_is_not_auto_rescinded(
    db, world, client, auth, must_record
):
    """s.19(7)/3D(3) clocks declared no `suspend_on` at all, so the engine rescinded
    the notification of a case that was demonstrably under a High Court stay."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    must_record(case, "COURT_STAY", date(2025, 6, 1), {"court": "High Court"})

    headers = auth(world.lao, DAY_366)
    clocks = clocks_on(client, case, headers)
    assert clocks["DECLARATION_S19"]["status"] == "suspended", clocks["DECLARATION_S19"]
    assert stage_of(db, case) == "NOTIFIED"

    types = event_types(client, case, headers)
    assert "NOTIFICATION_RESCINDED" not in types
    assert "CASE_LAPSED" not in types


def test_a_case_frozen_by_a_court_is_not_ranked_as_being_in_default(
    db, world, client, auth, must_record
):
    """A suspended clock's elapsed fraction keeps climbing (the due date only moves when
    the stay is vacated), so a stayed case used to pin the top of every risk ranking."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    must_record(case, "COURT_STAY", date(2025, 3, 1), {"court": "High Court"})

    headers = auth(world.lao, date(2027, 3, 1))
    clocks = clocks_on(client, case, headers)
    assert clocks["DECLARATION_S19"]["status"] == "suspended"
    assert clocks["DECLARATION_S19"]["elapsed_pct"] == 100.0  # long past, but stayed

    risk = client.get(f"/api/v1/cases/{case.id}/risk", headers=headers).json()
    assert risk["score"] == 0, risk
    assert [a for a in _alerts(client, case, headers) if a["clock_id"] == "DECLARATION_S19"] == []


# --- a terminating event recorded after the deadline -------------------------------


def test_a_declaration_recorded_after_the_deadline_does_not_erase_the_lapse(
    db, world, client, auth, must_record, record
):
    """s.19(7): `if closing:` was tested before `today > due`, so recording the
    declaration four months late closed the clock as if it had been in time."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    satisfy_s19_preconditions(must_record, case, S11_DEFAULT + timedelta(days=120))

    late = S19_DUE + timedelta(days=120)  # 2026-05-01
    status, body = record(case, "DECLARATION_S19", late, {"gazette_no": "S.O. 9(E)"})
    assert status == 201, body

    headers = auth(world.lao, late)
    clocks = clocks_on(client, case, headers)
    s19 = clocks["DECLARATION_S19"]
    assert s19["status"] == "lapsed", s19
    assert s19["closed_on"] is None
    assert s19["due_date"] == S19_DUE.isoformat()

    assert "CASE_LAPSED" in event_types(client, case, headers)
    assert stage_of(db, case) == "LAPSED"


def test_an_award_six_months_late_lapses_the_clock_instead_of_closing_it(
    db, world, client, auth, must_record, record
):
    """s.25: the proceedings lapsed before the award was made. The clock must not read
    'closed', and because CASE_LAPSED is not reachable from AWARDED the refusal has to
    reach a human rather than be forced through or dropped."""
    case = world.case(db)
    walk_to_declared(must_record, case)  # AWARD_S23 due 2026-06-30
    late = date(2026, 12, 30)

    status, body = record(case, "AWARD_S23", late, {"award_no": "AWD/late"})
    assert status == 201, body

    headers = auth(world.lao, late)
    clocks = clocks_on(client, case, headers)
    award = clocks["AWARD_S23"]
    assert award["status"] == "lapsed", award
    assert award["closed_on"] is None
    assert award["due_date"] == "2026-06-30"

    assert stage_of(db, case) == "AWARDED"
    assert "CASE_LAPSED" not in event_types(client, case, headers)
    integrity_alerts = [a for a in _alerts(client, case, headers) if a["clock_id"] == "INTEGRITY"]
    assert len(integrity_alerts) == 1, _alerts(client, case, headers)
    assert integrity_alerts[0]["level"] == "breached"


# --- system-actor consequences -----------------------------------------------------


def test_a_lapse_never_drags_a_case_into_a_stage_the_ruleset_forbids(
    db, world, client, auth, must_record
):
    """The year on the award is mistyped as 2027. The transition itself is legal, so the
    case is AWARDED; the s.25 clock then lapses at the next sweep and used to append
    CASE_LAPSED as SYSTEM from a stage the rule-set never allows it from, leaving a case
    in LAPSED with `allowed_events() == []` and no way back."""
    from app.models import AdminAudit

    case = world.case(db)
    walk_to_declared(must_record, case)  # AWARD_S23 due 2026-06-30
    must_record(
        case, "AWARD_S23", date(2027, 3, 1), {"award_no": "AWD/typo"},
        on=date(2025, 8, 1),
    )
    assert stage_of(db, case) == "AWARDED"

    headers = auth(world.lao, date(2026, 8, 1))  # the sweep, past the s.25 deadline
    clocks = clocks_on(client, case, headers)
    assert clocks["AWARD_S23"]["status"] == "lapsed"

    assert stage_of(db, case) == "AWARDED"
    assert "CASE_LAPSED" not in event_types(client, case, headers)

    integrity = [a for a in _alerts(client, case, headers) if a["clock_id"] == "INTEGRITY"]
    assert len(integrity) == 1
    assert integrity[0]["level"] == "breached"

    db.expire_all()
    audit = (
        db.query(AdminAudit)
        .filter(AdminAudit.action == "consequence_refused", AdminAudit.target == str(case.id))
        .all()
    )
    assert len(audit) == 1
    assert audit[0].meta["event_type"] == "CASE_LAPSED"

    # The case is still workable: the rule-set still offers the officer something.
    allowed = client.get(
        f"/api/v1/cases/{case.id}/allowed-events", headers=headers
    ).json()["items"]
    assert allowed


def test_event_reversed_is_appendable_on_a_lapsed_case(
    db, world, client, auth, must_record, record
):
    """Docs/rules.md C1 makes EVENT_REVERSED the only legal correction path, but it was
    on no stage's `on:` list, so a wrongly lapsed acquisition could only be fixed with
    raw SQL — which breaks the hash chain."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    headers = auth(world.lao, DAY_366)
    clocks_on(client, case, headers)  # the s.19(7) sweep lapses the case
    assert stage_of(db, case) == "LAPSED"

    wrong = client.get(f"/api/v1/cases/{case.id}/events", headers=headers).json()["items"][0]
    status, body = record(
        case, "EVENT_REVERSED", DAY_366,
        {"reversed_event_id": wrong["id"], "reason": "recorded against the wrong case"},
        user=world.collector, on=DAY_366,
    )
    assert status == 201, body
    assert body["stage"] == "LAPSED"  # a correction moves no stage
    assert "EVENT_REVERSED" in event_types(client, case, headers)
    assert _integrity(client, case, headers)["verified"] is True


# --- EXTENSION_GRANTED -------------------------------------------------------------


def test_an_extension_may_not_move_a_deadline_backwards(
    db, world, client, auth, must_record, record
):
    """A Collector typing 2025 for 2026 pushed the due date into the past, lapsed the
    case in the same request, and left `allowed_events()` empty."""
    case = world.case(db)
    walk_to_notified(must_record, case)

    status, body = record(
        case, "EXTENSION_GRANTED", date(2025, 12, 1),
        {
            "clock_id": "DECLARATION_S19",
            "authority": "State Government (Revenue Department)",
            "reasons": "objections under s.15 still under disposal",
            "new_due_date": "2025-05-15",
        },
        user=world.collector,
    )
    assert status == 422, body
    assert body["type"] == "validation_error"
    assert body["errors"][0]["current_due_date"] == S19_DUE.isoformat()
    assert body["errors"][0]["new_due_date"] == "2025-05-15"
    assert stage_of(db, case) == "NOTIFIED"

    clocks = clocks_on(client, case, auth(world.lao, date(2025, 12, 1)))
    assert clocks["DECLARATION_S19"]["due_date"] == S19_DUE.isoformat()
    assert clocks["DECLARATION_S19"]["status"] == "running"


def test_an_extension_without_reasons_or_paper_is_refused(
    db, world, client, auth, must_record, record
):
    """`extendable: {reasons_required: true}` was parsed, stored and never enforced, and
    EXTENSION_GRANTED needed no document at all (Docs/APIs.md §3.4)."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    payload = {
        "clock_id": "DECLARATION_S19",
        "authority": "State Government (Revenue Department)",
        "new_due_date": "2026-06-30",
    }

    status, body = record(case, "EXTENSION_GRANTED", date(2025, 12, 1), payload,
                          user=world.collector)
    assert status == 422, body
    assert body["type"] == "validation_error"
    assert body["errors"][0]["field"] == "payload.reasons"

    with_reasons = {**payload, "reasons": "objections under s.15 still under disposal"}
    status, body = record(case, "EXTENSION_GRANTED", date(2025, 12, 1), with_reasons,
                          user=world.collector, no_document_reason=None)
    assert status == 422, body
    assert body["type"] == "document_required"

    # With reasons and paper it still works, and still moves the deadline.
    status, body = record(case, "EXTENSION_GRANTED", date(2025, 12, 1), with_reasons,
                          user=world.collector)
    assert status == 201, body
    clocks = clocks_on(client, case, auth(world.lao, date(2026, 1, 2)))
    assert clocks["DECLARATION_S19"]["status"] == "extended"
    assert clocks["DECLARATION_S19"]["due_date"] == "2026-06-30"


# --- the ledger --------------------------------------------------------------------


def test_deleting_the_tail_of_the_chain_is_detected(
    db, world, client, auth, must_record
):
    """Head and middle deletions were caught; deleting the *last* event — the only kind
    that erases a lapse or a possession — verified clean."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    headers = auth(world.lao)

    clean = _integrity(client, case, headers)
    assert clean["verified"] is True
    assert clean["events_checked"] == 3

    head_seq = db.execute(
        text("SELECT max(seq) FROM events WHERE case_id = :cid"), {"cid": str(case.id)}
    ).scalar()
    db.execute(text("DELETE FROM events WHERE seq = :seq"), {"seq": head_seq})
    db.commit()

    truncated = _integrity(client, case, headers)
    assert truncated["verified"] is False, truncated
    assert truncated["first_bad_seq"] == head_seq
    assert "tail" in truncated["detail"]


def test_the_nightly_sweep_files_an_integrity_alert_for_a_broken_chain(
    db, world, client, auth, must_record
):
    """Docs/rules.md C1 promises a tamper-*evident* ledger, which is only true if
    something looks. The 02:00 IST job looks."""
    from app.domain.alerts.service import verify_all_chains
    from app.models import AdminAudit, Alert

    case = world.case(db)
    walk_to_notified(must_record, case)
    headers = auth(world.lao)
    assert _integrity(client, case, headers)["verified"] is True

    db.execute(
        text(
            "UPDATE events SET payload = jsonb_set(payload, '{gazette_no}', '\"FAKE\"') "
            "WHERE case_id = :cid AND type = 'PRELIM_NOTIFICATION_S11'"
        ),
        {"cid": str(case.id)},
    )
    db.commit()

    summary = verify_all_chains()
    assert str(case.id) in summary["failed"], summary

    db.expire_all()
    raised = (
        db.query(Alert)
        .filter(Alert.case_id == case.id, Alert.clock_id == "INTEGRITY")
        .all()
    )
    assert len(raised) == 1
    assert raised[0].level == "breached"
    audit = (
        db.query(AdminAudit)
        .filter(
            AdminAudit.action == "chain_verification_failed",
            AdminAudit.target == str(case.id),
        )
        .all()
    )
    assert len(audit) == 1

    # Deduped: a second night raises neither a second alert nor a second audit line.
    verify_all_chains()
    db.expire_all()
    assert (
        db.query(Alert)
        .filter(Alert.case_id == case.id, Alert.clock_id == "INTEGRITY")
        .count()
        == 1
    )
    assert (
        db.query(AdminAudit)
        .filter(
            AdminAudit.action == "chain_verification_failed",
            AdminAudit.target == str(case.id),
        )
        .count()
        == 1
    )


# --- idempotency -------------------------------------------------------------------


def test_one_key_may_not_buy_two_different_events(db, world, client, auth, record):
    """A re-used key answered 201 with the *first* event's seq and silently discarded
    the second statutory append. The officer's screen showed a success."""
    case = world.case(db)
    key = "regression-idempotency-0001"

    status, first = record(
        case, "SIA_NOTIFIED", date(2025, 1, 5), {"agency": "SIA Unit"},
        idempotency_key=key,
    )
    assert status == 201, first

    status, body = record(
        case, "SIA_EXEMPTED_S40", date(2025, 1, 6), {"order_ref": "URG/1"},
        idempotency_key=key,
    )
    assert status == 422, body
    assert body["type"] == "validation_error"
    assert body["errors"][0]["field"] == "Idempotency-Key"
    assert body["errors"][0]["recorded_type"] == "SIA_NOTIFIED"

    # Same type, different legal date, is just as much a different event.
    status, body = record(
        case, "SIA_NOTIFIED", date(2025, 1, 9), {"agency": "SIA Unit"},
        idempotency_key=key,
    )
    assert status == 422, body
    assert "occurred_at" in body["detail"]

    # The identical request still replays.
    status, body = record(
        case, "SIA_NOTIFIED", date(2025, 1, 5), {"agency": "SIA Unit"},
        idempotency_key=key,
    )
    assert status == 201, body
    assert body["duplicate"] is True
    assert body["seq"] == first["seq"]
    assert event_types(client, case, auth(world.lao)) == ["SIA_NOTIFIED"]


def test_losing_the_idempotency_key_race_replays_instead_of_a_500(db, world, monkeypatch):
    """Two retries of the same request raced past the lookup; the loser died on the
    unique index and the router turned that into an unhandled 500. The insert now
    catches the violation and answers with the event the winner wrote.

    The race is made deterministic by committing the conflicting row from a second
    session between this append's key lookup and its insert.
    """
    import app.domain.rules.engine as engine_mod
    from app.core.db import SessionLocal
    from app.domain.events.hash import compute_hash, event_fields
    from app.domain.events.service import append_event
    from app.models import Event

    case = world.case(db)
    key = "regression-idempotency-race-0001"
    occurred = date(2025, 1, 5)
    payload = {"agency": "SIA Unit", "no_document_reason": "race regression"}

    real_validate = engine_mod.validate_append
    raced = {"done": False}

    def racing_validate(*args, **kwargs):
        if not raced["done"]:
            raced["done"] = True
            with SessionLocal() as other:
                winner = Event(
                    id=uuid.uuid4(),
                    case_id=case.id,
                    type="SIA_NOTIFIED",
                    occurred_at=occurred,
                    actor_id=world.lao.id,
                    payload=dict(payload),
                    idempotency_key=key,
                    prev_hash=None,
                )
                winner.hash = compute_hash(None, event_fields(winner))
                other.add(winner)
                other.commit()
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(engine_mod, "validate_append", racing_validate)

    result = append_event(
        db, case, "SIA_NOTIFIED", occurred, world.lao.id, dict(payload),
        idempotency_key=key,
    )
    assert raced["done"] is True
    assert result.duplicate is True
    assert result.seq > 0

    # The session survived the violation, and exactly one event carries the key.
    db.commit()
    assert (
        db.execute(
            text("SELECT count(*) FROM events WHERE idempotency_key = :k"), {"k": key}
        ).scalar()
        == 1
    )


# --- rule-set pinning, the evaluation guard, and the calendar ----------------------


def test_an_unloaded_ruleset_pin_is_never_silently_upgraded(db, world):
    """`get_ruleset` fell back to the newest version of the track, so a case filed under
    2019.01 was evaluated under 2026.09 — the exact thing pinning exists to prevent."""
    from app.core.problems import Problem
    from app.domain.rules.engine import resolve_ruleset
    from app.domain.rules.loader import get_ruleset

    assert get_ruleset("RFCTLARR_2013", "2026.09") is not None
    assert get_ruleset("RFCTLARR_2013", "2019.01") is None
    assert get_ruleset("RFCTLARR_2013", "9999.99") is None
    assert get_ruleset("MADE_UP_ACT_1900", "2026.09") is None
    # No pin still means "whatever is current" — project creation relies on it.
    assert get_ruleset("RFCTLARR_2013").version == "2026.09"

    case = world.case(db)
    case.ruleset_version = "2019.01"
    with pytest.raises(Problem) as raised:
        resolve_ruleset(case)
    assert raised.value.type == "ruleset_unavailable"
    assert raised.value.status == 503
    db.rollback()


def test_the_evaluation_guard_is_per_thread(db, world, client, auth, must_record):
    """A module-level set let the hourly sweep, running in the scheduler's own thread,
    suppress clock evaluation inside an officer's append — so the case page showed a
    running clock on a case that had legally lapsed until the next sweep."""
    from app.domain.rules import clocks as clock_engine

    case = world.case(db)
    walk_to_notified(must_record, case)

    holding = threading.Event()
    release = threading.Event()

    def sweeper():
        clock_engine._evaluating().add(case.id)
        holding.set()
        release.wait(20)
        clock_engine._evaluating().discard(case.id)

    thread = threading.Thread(target=sweeper, daemon=True)
    thread.start()
    assert holding.wait(20)
    try:
        assert clock_engine.is_evaluating(case.id) is False  # not in *this* thread
        body = must_record(
            case, "OBJECTION_RECEIVED", DAY_366, {"count": 2}, on=DAY_366
        )
        changed = {c["clock_id"]: c for c in body["clocks_changed"]}
        assert changed["DECLARATION_S19"]["status"] == "lapsed", body["clocks_changed"]
    finally:
        release.set()
        thread.join(20)


def test_the_statutory_today_is_the_indian_calendar_day(
    db, world, client, auth, must_record, monkeypatch
):
    """The containers run UTC, so `date.today()` there is still yesterday until 05:30
    IST — long enough for the 01:00 IST sweep to call a breached clock 'running'.
    Every default `today` that decides statutory state asks `ist_today()` instead, which
    is proved here by making that function answer something the process clock never
    would and watching the answers move."""
    import app.core.deps as deps_mod
    import app.domain.alerts.service as alerts_mod
    import app.domain.cases.projections as projections_mod
    import app.domain.events.service as events_mod
    from app.core.time import IST, ist_today

    now_utc = datetime.now(timezone.utc)
    assert ist_today() == now_utc.astimezone(IST).date()
    assert ist_today() == (now_utc + timedelta(hours=5, minutes=30)).date()

    for module in (deps_mod, alerts_mod, projections_mod, events_mod):
        assert module.ist_today is ist_today, module.__name__

    case = world.case(db)
    walk_to_notified(must_record, case)  # DECLARATION_S19 due 2026-01-01

    # (a) the read path: no X-Demo-Date, so the effective date is the IST day.
    sentinel = date(2025, 6, 1)
    monkeypatch.setattr(deps_mod, "ist_today", lambda: sentinel)
    body = client.get(f"/api/v1/cases/{case.id}/clocks", headers=auth(world.lao)).json()
    assert body["as_of_date"] == sentinel.isoformat()

    # (b) the write path: `append_event` with no `today` evaluates as of the IST day,
    # which here is inside the s.19 window even though the real one is long past it.
    from sqlalchemy import select

    from app.models import Clock

    monkeypatch.setattr(events_mod, "ist_today", lambda: sentinel)
    events_mod.append_event(
        db, case, "OBJECTION_RECEIVED", date(2030, 1, 1), world.lao.id,
        {"count": 1, "no_document_reason": "regression"},
        idempotency_key=f"ist-{uuid.uuid4()}",
    )
    row = db.scalar(
        select(Clock).where(
            Clock.case_id == case.id, Clock.clock_id == "DECLARATION_S19"
        )
    )
    assert row.status == "running", row.status  # the real today would have lapsed it
    assert stage_of(db, case) == "NOTIFIED"
    db.rollback()
