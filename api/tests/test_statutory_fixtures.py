"""The statutory fixtures from Docs/Backend.md §12.

Each test is one scenario a land acquisition officer would recognise, walked through
the real API against the real database. If one of these goes red, the software is
saying something untrue about the Act.

    1. s19_on_day_366_no_extension   -> NOTIFICATION_RESCINDED, case LAPSED
    2. s19_on_day_366_with_extension -> DECLARATION_S19 accepted on day 400, DECLARED
    3. award_day_400_with_stay_60    -> due shifted 60 days, still running
    4. possession_before_payment     -> guard_failed
    5. possession_urgency_80pct      -> allowed
    6. hash chain                    -> tamper detected, clean chain verifies
    7. idempotent replay             -> same seq, 201
    8. declaration without s.18/s.19(2) -> precondition_failed naming both
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from tests.conftest import stage_of
from tests.helpers import (
    S11_DEFAULT,
    clocks_on,
    event_types,
    pay,
    satisfy_s19_preconditions,
    walk_to_awarded,
    walk_to_declared,
    walk_to_notified,
)

DAY_366 = S11_DEFAULT + timedelta(days=366)  # 2026-01-02
DAY_400 = S11_DEFAULT + timedelta(days=400)  # 2026-02-05


# --- 1 -----------------------------------------------------------------------------


def test_s19_not_recorded_by_day_366_rescinds_the_notification(
    db, world, client, auth, must_record
):
    """s.19(7): the preliminary notification is deemed rescinded and the case lapses."""
    case = world.case(db)
    walk_to_notified(must_record, case)

    headers = auth(world.lao, DAY_366)
    clocks = clocks_on(client, case, headers)

    s19 = clocks["DECLARATION_S19"]
    assert s19["due_date"] == "2026-01-01"
    assert s19["status"] == "lapsed", s19
    assert s19["basis"] == "s.19(7)"

    types = event_types(client, case, headers)
    assert "NOTIFICATION_RESCINDED" in types
    assert "CASE_LAPSED" in types
    assert stage_of(db, case) == "LAPSED"

    # The consequence is in the chain, as the system actor, dated the due date.
    events = client.get(f"/api/v1/cases/{case.id}/events", headers=headers).json()["items"]
    rescinded = next(e for e in events if e["type"] == "NOTIFICATION_RESCINDED")
    assert rescinded["occurred_at"] == "2026-01-01"
    assert rescinded["payload"]["auto"] is True
    assert rescinded["payload"]["reason"] == "s.19(7)"
    assert rescinded["actor_name"] == "BhuArjan clock engine"

    integrity = client.get(f"/api/v1/cases/{case.id}/integrity", headers=headers).json()
    assert integrity["verified"] is True


# --- 2 -----------------------------------------------------------------------------


def test_extension_before_due_lets_the_declaration_land_on_day_400(
    db, world, client, auth, must_record, record
):
    """s.19(7) proviso: the appropriate Government may extend, with reasons."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    satisfy_s19_preconditions(must_record, case, S11_DEFAULT + timedelta(days=120))

    must_record(
        case,
        "EXTENSION_GRANTED",
        date(2025, 12, 1),
        {
            "clock_id": "DECLARATION_S19",
            "authority": "State Government (Revenue Department)",
            "order_ref": "F-12/2025/Rev",
            "reasons": "objections under s.15 still under disposal",
            "new_due_date": "2026-06-30",
        },
        user=world.collector,
    )

    clocks = clocks_on(client, case, auth(world.lao, date(2026, 1, 2)))
    assert clocks["DECLARATION_S19"]["status"] == "extended"
    assert clocks["DECLARATION_S19"]["due_date"] == "2026-06-30"
    assert clocks["DECLARATION_S19"]["original_due_date"] == "2026-01-01"
    assert stage_of(db, case) == "NOTIFIED"

    status, body = record(
        case,
        "DECLARATION_S19",
        DAY_400,
        {"gazette_no": "S.O. 9(E)", "total_area_ha": "12.5000"},
    )
    assert status == 201, body
    assert body["stage"] == "DECLARED"
    assert stage_of(db, case) == "DECLARED"

    closed = {c["clock_id"]: c for c in body["clocks_changed"]}
    assert closed["DECLARATION_S19"]["status"] == "closed"
    assert closed["DECLARATION_S19"]["closed_on"] == DAY_400.isoformat()
    assert closed["AWARD_S23"]["status"] == "running"
    assert closed["AWARD_S23"]["basis"] == "s.25"


# --- 3 -----------------------------------------------------------------------------


def test_court_stay_of_60_days_shifts_the_award_clock(
    db, world, client, auth, must_record
):
    """s.25 clock suspended by a court stay; the suspended days are added back on
    vacation, so the clock is still running at day 400."""
    case = world.case(db)
    declared_on = walk_to_declared(must_record, case)
    assert declared_on == date(2025, 6, 30)
    assert stage_of(db, case) == "DECLARED"

    stay_from = date(2025, 8, 1)
    stay_to = date(2025, 9, 30)  # 60 calendar days
    assert (stay_to - stay_from).days == 60

    must_record(
        case, "COURT_STAY", stay_from,
        {"court": "High Court", "case_no": "WP 1234/2025", "order_date": stay_from.isoformat()},
    )
    must_record(
        case, "STAY_VACATED", stay_to,
        {"court": "High Court", "case_no": "WP 1234/2025", "order_date": stay_to.isoformat()},
    )

    day_400 = declared_on + timedelta(days=400)  # 2026-08-04
    clocks = clocks_on(client, case, auth(world.lao, day_400))
    award = clocks["AWARD_S23"]

    assert award["original_due_date"] == "2026-06-30"
    assert award["suspended_days"] == 60
    assert award["due_date"] == "2026-08-29"  # 2026-06-30 + 60 days
    assert award["status"] == "running", award
    assert stage_of(db, case) == "DECLARED"


def test_an_unvacated_stay_suspends_the_clock(db, world, client, auth, must_record):
    case = world.case(db)
    declared_on = walk_to_declared(must_record, case)
    must_record(case, "COURT_STAY", declared_on + timedelta(days=30), {"court": "High Court"})

    clocks = clocks_on(client, case, auth(world.lao, declared_on + timedelta(days=400)))
    # Past its due date, but a live stay outranks a breach: nobody is in default
    # while a court has stopped the proceeding.
    assert clocks["AWARD_S23"]["status"] == "suspended"
    assert clocks["AWARD_S23"]["suspended_days"] == 0
    assert stage_of(db, case) == "DECLARED"


# --- 4 and 5 -----------------------------------------------------------------------


def test_possession_before_full_payment_is_refused(db, world, client, auth, must_record, record):
    """s.38(1): possession cannot be taken until compensation is paid."""
    case = world.case(db)
    award_on, assessed = walk_to_awarded(must_record, case)
    pay(must_record, case, award_on + timedelta(days=10), assessed // 2)

    status, body = record(case, "POSSESSION_TAKEN_S38", award_on + timedelta(days=20), {})
    assert status == 422, body
    assert body["type"] == "guard_failed"
    assert "s.38" in body["detail"] or "urgency" in body["detail"].lower()
    assert body["errors"][0]["comp_assessed_paise"] == assessed
    assert body["errors"][0]["comp_paid_paise"] == assessed // 2
    assert stage_of(db, case) == "AWARDED"

    # The rule-set says the same thing before the officer even tries.
    allowed = client.get(
        f"/api/v1/cases/{case.id}/allowed-events", headers=auth(world.lao)
    ).json()["items"]
    possession = next(a for a in allowed if a["type"] == "POSSESSION_TAKEN_S38")
    assert possession["guard_status"]["ok"] is False
    assert possession["guard_status"]["guard"] == "possession_payment_gate"


def test_urgency_s40_with_80_percent_paid_allows_possession(
    db, world, client, auth, must_record, record
):
    """s.40: urgency compresses the procedure but still demands 80% of compensation."""
    case = world.case(db)
    award_on, assessed = walk_to_awarded(must_record, case)
    pay(must_record, case, award_on + timedelta(days=10), assessed // 2)

    must_record(case, "URGENCY_S40_INVOKED", award_on + timedelta(days=12),
                {"order_ref": "URG/2025/3"})
    pay(must_record, case, award_on + timedelta(days=14), int(assessed * 0.3), ref="PFMS/2")

    status, body = record(case, "POSSESSION_TAKEN_S38", award_on + timedelta(days=20), {})
    assert status == 201, body
    assert body["stage"] == "POSSESSED"
    assert stage_of(db, case) == "POSSESSED"

    clocks = {c["clock_id"]: c for c in body["clocks_changed"]}
    assert clocks["UTILISATION_5Y"]["status"] == "running"
    assert clocks["UTILISATION_5Y"]["basis"] == "s.101"


def test_full_payment_alone_opens_the_possession_gate(
    db, world, client, auth, must_record, record
):
    case = world.case(db)
    award_on, assessed = walk_to_awarded(must_record, case)
    pay(must_record, case, award_on + timedelta(days=10), assessed)

    status, body = record(case, "POSSESSION_TAKEN_S38", award_on + timedelta(days=20), {})
    assert status == 201, body
    assert body["stage"] == "POSSESSED"


# --- 6 -----------------------------------------------------------------------------


def test_hash_chain_detects_a_payload_edited_behind_the_api(
    db, world, client, auth, must_record
):
    """Docs/rules.md C1: the ledger is tamper-evident, not tamper-proof — an edit made
    straight in SQL must be visible."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    headers = auth(world.lao)

    clean = client.get(f"/api/v1/cases/{case.id}/integrity", headers=headers).json()
    assert clean["verified"] is True
    assert clean["events_checked"] == 3
    assert len(clean["head_hash"]) == 64  # sha256 hex

    target = db.execute(
        text(
            "SELECT seq FROM events WHERE case_id = :cid AND type = "
            "'PRELIM_NOTIFICATION_S11'"
        ),
        {"cid": str(case.id)},
    ).scalar()
    db.execute(
        text(
            "UPDATE events SET payload = jsonb_set(payload, '{total_area_ha}', "
            "'\"99.0000\"') WHERE seq = :seq"
        ),
        {"seq": target},
    )
    db.commit()

    tampered = client.get(f"/api/v1/cases/{case.id}/integrity", headers=headers).json()
    assert tampered["verified"] is False
    assert tampered["first_bad_seq"] == target
    assert "hash" in tampered["detail"]


# --- 7 -----------------------------------------------------------------------------


def test_replaying_an_idempotency_key_returns_the_original_event(
    db, world, client, auth, record
):
    """Docs/APIs.md §1: a replayed key returns the original 201, never a second event."""
    case = world.case(db)
    key = "fixture-idempotency-key-0001"

    first_status, first = record(
        case, "SIA_NOTIFIED", date(2025, 1, 5), {"agency": "SIA Unit"},
        idempotency_key=key,
    )
    second_status, second = record(
        case, "SIA_NOTIFIED", date(2025, 1, 5), {"agency": "SIA Unit"},
        idempotency_key=key,
    )

    assert first_status == 201
    assert second_status == 201
    assert second["seq"] == first["seq"]
    assert second["id"] == first["id"]
    assert second["hash"] == first["hash"]
    assert second["duplicate"] is True
    assert first["duplicate"] is False

    types = event_types(client, case, auth(world.lao))
    assert types.count("SIA_NOTIFIED") == 1


def test_idempotency_key_is_required(db, world, client, auth):
    case = world.case(db)
    res = client.post(
        f"/api/v1/cases/{case.id}/events",
        json={"type": "SIA_NOTIFIED", "occurred_at": "2025-01-05", "payload": {}},
        headers=auth(world.lao),
    )
    assert res.status_code == 422
    assert res.json()["type"] == "validation_error"
    assert res.json()["errors"][0]["field"] == "Idempotency-Key"


# --- 8 -----------------------------------------------------------------------------


def test_declaration_without_rr_scheme_and_cost_deposit_is_refused(
    db, world, client, auth, must_record, record
):
    """s.19 cannot issue without the s.18 R&R scheme summary and the s.19(2) deposit."""
    case = world.case(db)
    walk_to_notified(must_record, case)

    status, body = record(
        case, "DECLARATION_S19", S11_DEFAULT + timedelta(days=60),
        {"gazette_no": "S.O. 3(E)"},
    )
    assert status == 422, body
    assert body["type"] == "precondition_failed"
    missing = {e["missing"]: e["section"] for e in body["errors"]}
    assert missing == {
        "RR_SCHEME_PUBLISHED_S18": "s.18",
        "COST_DEPOSITED_S19_2": "s.19(2)",
    }
    assert stage_of(db, case) == "NOTIFIED"

    # Recording only one of the two still fails, naming the one still missing.
    must_record(case, "RR_SCHEME_PUBLISHED_S18", S11_DEFAULT + timedelta(days=61), {})
    status, body = record(
        case, "DECLARATION_S19", S11_DEFAULT + timedelta(days=62), {"gazette_no": "S.O. 3(E)"}
    )
    assert status == 422
    assert [e["missing"] for e in body["errors"]] == ["COST_DEPOSITED_S19_2"]
