"""The NH Act 1956 track — the same engine, a different rule-set file.

This is the path the live demo walks: a 3A notification whose 3D declaration clock is
nearly out of time, closed on stage by recording the declaration. It exists to prove
that nothing about the statute is in the code — swapping `rulesets/nh_act_1956.yaml`
for `rfctlarr_2013.yaml` changes the stages, the sections and the clocks, and the
engine does not notice.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from tests.conftest import stage_of
from tests.helpers import clocks_on, event_types

NOTIFIED_3A = date(2025, 9, 27)


def _notify(must_record, case) -> None:
    must_record(
        case,
        "NOTIFICATION_3A",
        NOTIFIED_3A,
        {
            "gazette_no": "S.O. 4211(E)",
            "total_area_ha": "18.6400",
            "villages": [{"name": "Adegaon", "survey_nos": ["112/1"], "area_ha": "18.6400"}],
        },
    )


def test_3a_starts_the_3d_clock_and_the_objection_window(db, world, client, auth, must_record):
    case = world.case(db, "NH_ACT_1956", case_no="LAQ/NH/1")
    _notify(must_record, case)
    assert stage_of(db, case) == "NOTIFIED"

    clocks = clocks_on(client, case, auth(world.lao, date(2026, 9, 2)))
    objection = clocks["OBJECTION_3C"]
    assert objection["kind"] == "window"
    assert objection["due_date"] == "2025-10-18"   # 21 days, s.3C
    assert objection["status"] == "closed"          # a window expires, it does not breach

    declaration = clocks["DECLARATION_3D"]
    assert declaration["due_date"] == "2026-09-27"  # 1 year, 3D(3)
    assert declaration["status"] == "running"
    assert declaration["elapsed_pct"] == 93.15      # the demo's red clock


def test_recording_the_declaration_closes_the_clock_and_moves_the_stage(
    db, world, client, auth, must_record, record
):
    """The live demo: the officer uploads the 3D gazette and the red clock goes green."""
    case = world.case(db, "NH_ACT_1956", case_no="LAQ/NH/2")
    _notify(must_record, case)

    status, body = record(
        case, "DECLARATION_3D", date(2026, 9, 2),
        {"gazette_no": "S.O. 3901(E)", "total_area_ha": "18.6400"},
        document_id=str(uuid.uuid4()),
    )
    assert status == 201, body
    assert body["stage"] == "DECLARED"

    changed = {c["clock_id"]: c for c in body["clocks_changed"]}
    assert changed["DECLARATION_3D"]["status"] == "closed"
    assert changed["DECLARATION_3D"]["closed_on"] == "2026-09-02"
    assert changed["AWARD_3G"]["status"] == "running"
    assert changed["AWARD_3G"]["due_date"] == "2027-09-02"


def test_3d_not_issued_within_a_year_rescinds_the_3a_notification(
    db, world, client, auth, must_record
):
    """3D(3): the 3A notification ceases to have effect."""
    case = world.case(db, "NH_ACT_1956", case_no="LAQ/NH/3")
    _notify(must_record, case)

    headers = auth(world.lao, date(2026, 9, 28))
    clocks = clocks_on(client, case, headers)
    assert clocks["DECLARATION_3D"]["status"] == "lapsed"
    assert stage_of(db, case) == "LAPSED"
    assert "NOTIFICATION_RESCINDED" in event_types(client, case, headers)

    # Nothing may be recorded on a lapsed case.
    res = client.post(
        f"/api/v1/cases/{case.id}/events",
        json={"type": "DECLARATION_3D", "occurred_at": "2026-09-29",
              "payload": {}, "no_document_reason": "late"},
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert res.status_code == 422
    assert res.json()["ruleset_ref"] == "NH_ACT_1956@2026.09/transitions/DECLARATION_3D"


def test_a_3a_notification_under_a_live_stay_is_not_rescinded(
    db, world, client, auth, must_record
):
    """3D(3) carries no proviso, but a writ still stops the clock: the 3A notification
    must not be deemed to cease while a court has stayed the declaration."""
    case = world.case(db, "NH_ACT_1956", case_no="LAQ/NH/10")
    _notify(must_record, case)
    must_record(
        case, "COURT_STAY", date(2026, 3, 1),
        {"court": "High Court", "case_no": "WP 5/2026"},
    )

    headers = auth(world.lao, date(2026, 9, 28))  # a day past 3D(3)
    clocks = clocks_on(client, case, headers)
    assert clocks["DECLARATION_3D"]["status"] == "suspended", clocks["DECLARATION_3D"]
    assert stage_of(db, case) == "NOTIFIED"
    assert "NOTIFICATION_RESCINDED" not in event_types(client, case, headers)


def test_possession_3e_uses_the_same_payment_gate(db, world, client, must_record, record):
    case = world.case(db, "NH_ACT_1956", case_no="LAQ/NH/4")
    _notify(must_record, case)
    must_record(case, "DECLARATION_3D", date(2026, 2, 10), {"total_area_ha": "18.6400"})
    must_record(case, "AWARD_3G", date(2026, 3, 5), {"award_no": "CALA/1"})
    must_record(
        case, "COMPENSATION_ASSESSED", date(2026, 3, 5),
        {"assessed_total_paise": 1_000_000, "line_count": 1},
    )

    status, body = record(case, "POSSESSION_3E", date(2026, 3, 20), {})
    assert status == 422
    assert body["type"] == "guard_failed"

    must_record(
        case, "PAYMENT_MADE", date(2026, 3, 10),
        {"pfms_ref": "PFMS/9", "amount_paise": 1_000_000, "mode": "PFMS"},
    )
    status, body = record(case, "POSSESSION_3E", date(2026, 3, 20), {})
    assert status == 201, body
    assert body["stage"] == "POSSESSED"


def test_compensation_paid_full_does_not_open_the_gate_one_paise_short(
    db, world, client, must_record, record
):
    """COMPENSATION_PAID_FULL is a marker, not the authority.

    It used to satisfy the s.38 gate on its own, which made the gate a one-way latch:
    once the marker was in the ledger nothing could close the gate again — not a s.64
    enhancement that raised the award five-fold, not a payment that was a paise short.
    The paise decide. Only the exact remainder opens possession."""
    case = world.case(db, "NH_ACT_1956", case_no="LAQ/NH/5")
    _notify(must_record, case)
    must_record(case, "DECLARATION_3D", date(2026, 2, 10), {"total_area_ha": "18.6400"})
    must_record(case, "AWARD_3G", date(2026, 3, 5), {"award_no": "CALA/2"})
    must_record(
        case, "COMPENSATION_ASSESSED", date(2026, 3, 5),
        {"assessed_total_paise": 1_000_000, "line_count": 1},
    )
    must_record(
        case, "PAYMENT_MADE", date(2026, 3, 10),
        {"pfms_ref": "PFMS/A", "amount_paise": 999_999, "mode": "PFMS"},
    )

    status, body = record(case, "POSSESSION_3E", date(2026, 3, 20), {})
    assert status == 422  # one paise short, and the gate says so
    assert body["type"] == "guard_failed"

    # …and the marker does not change that.
    must_record(case, "COMPENSATION_PAID_FULL", date(2026, 3, 12), {})
    status, body = record(case, "POSSESSION_3E", date(2026, 3, 20), {})
    assert status == 422, body
    assert body["type"] == "guard_failed"

    # The remainder does.
    must_record(
        case, "PAYMENT_MADE", date(2026, 3, 13),
        {"pfms_ref": "PFMS/B", "amount_paise": 1, "mode": "PFMS"},
    )
    status, body = record(case, "POSSESSION_3E", date(2026, 3, 20), {})
    assert status == 201, body
    assert body["stage"] == "POSSESSED"


def test_extending_a_clock_the_ruleset_calls_unextendable_is_refused(
    db, world, client, auth, must_record, record
):
    """3D(3) carries no proviso, so `DECLARATION_3D` has no `extendable:` stanza — yet
    an EXTENSION_GRANTED naming it used to push the deadline to 2035, and the 3D(3)
    rescission then never fired."""
    case = world.case(db, "NH_ACT_1956", case_no="LAQ/NH/9")
    _notify(must_record, case)

    status, body = record(
        case, "EXTENSION_GRANTED", date(2026, 6, 1),
        {
            "clock_id": "DECLARATION_3D",
            "authority": "Central Government",
            "reasons": "alignment under revision",
            "new_due_date": "2035-01-01",
        },
        user=world.collector,
    )
    assert status == 422, body
    assert body["type"] == "transition_not_allowed"
    assert body["ruleset_ref"] == "NH_ACT_1956@2026.09/clocks/DECLARATION_3D"
    assert "not extendable" in body["detail"]

    # The deadline did not move: 3D(3) still bites a year after the 3A notification.
    clocks = clocks_on(client, case, auth(world.lao, date(2026, 6, 1)))
    assert clocks["DECLARATION_3D"]["due_date"] == "2026-09-27"

    # A clock this rule-set does not define at all is refused too.
    status, body = record(
        case, "EXTENSION_GRANTED", date(2026, 6, 2),
        {"clock_id": "AWARD_S23", "reasons": "typo", "new_due_date": "2030-01-01"},
        user=world.collector,
    )
    assert status == 422, body
    assert body["type"] == "transition_not_allowed"


def test_scheduler_sweep_evaluates_every_open_case(db, world, must_record):
    """`evaluate_all_clocks` is what the hourly worker runs (Docs/Backend.md §9)."""
    from app.domain.alerts.service import evaluate_all_clocks
    from app.models import Alert, CaseState

    case = world.case(db, "NH_ACT_1956", case_no="LAQ/NH/6")
    _notify(must_record, case)
    assert stage_of(db, case) == "NOTIFIED"

    evaluate_all_clocks()  # today = the real date, well past 2026-09-27? not necessarily

    db.expire_all()
    state = db.get(CaseState, case.id)
    assert state.stage in ("NOTIFIED", "LAPSED")
    assert state.risk_score is not None and state.risk_score > 0
    raised = db.query(Alert).filter(Alert.case_id == case.id).count()
    assert raised >= 1  # at least the red on the 3D clock


def test_a_lapsed_case_is_skipped_by_the_sweep(db, world, client, auth, must_record):
    from app.domain.alerts.service import TERMINAL_STAGES

    case = world.case(db, "NH_ACT_1956", case_no="LAQ/NH/7")
    _notify(must_record, case)
    clocks_on(client, case, auth(world.lao, NOTIFIED_3A + timedelta(days=400)))
    assert stage_of(db, case) in TERMINAL_STAGES
