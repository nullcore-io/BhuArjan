"""The statutory fixes deferred out of the first adversarial-review pass.

Four things the review reproduced and Docs/mvp-status.md then listed as deferred:

    back-dated rewind   a payment recorded late re-evaluating a live case as of its own
                        past legal date, flipping breached clocks back to 'running'
    version sort        '2026.9' outranking '2026.10' in the no-pin fallback
    EVENT_REVERSED      appendable by anyone, naming any event, and projected nowhere
    risk drivers        a suspended clock reporting weight 100 beside a score of 0

Each test states the untrue thing the system used to say, then the true one.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from app.models import CaseState, Clock
from tests.conftest import stage_of
from tests.helpers import (
    clocks_on,
    event_types,
    walk_to_awarded,
    walk_to_declared,
    walk_to_notified,
)


def _clock_rows(db, case) -> dict[str, Clock]:
    """The *persisted* clock rows. Read straight from the table on purpose: every clock
    endpoint re-evaluates before answering, which would repair a rewind before a test
    could see it."""
    db.expire_all()
    return {
        row.clock_id: row
        for row in db.scalars(select(Clock).where(Clock.case_id == case.id)).all()
    }


def _state(db, case) -> CaseState:
    db.expire_all()
    return db.get(CaseState, case.id)


def _figures(state: CaseState) -> dict:
    return {
        "stage": state.stage,
        "as_of_seq": int(state.as_of_seq or 0),
        "area_notified_ha": float(state.area_notified_ha or 0),
        "area_acquired_ha": float(state.area_acquired_ha or 0),
        "comp_assessed_paise": int(state.comp_assessed_paise or 0),
        "comp_paid_paise": int(state.comp_paid_paise or 0),
        "families_affected": int(state.families_affected or 0),
        "families_displaced": int(state.families_displaced or 0),
        "possession_pct": float(state.possession_pct or 0),
        "risk_score": float(state.risk_score or 0),
    }


# --- back-dated events must not rewind the projection ------------------------------


def test_a_late_recorded_payment_does_not_un_breach_a_live_case(
    db, world, client, auth, must_record
):
    """The deferral in Docs/mvp-status.md: clocks were evaluated at
    `min(today, occurred_at)`, so recording today a payment that legally happened a year
    ago overwrote every clock row as of that past date. Breached clocks read 'running'
    again and the case vanished from the breach list and the escalation ladder until the
    next hourly sweep."""
    case = world.case(db)
    award_on, assessed = walk_to_awarded(must_record, case)  # 2025-07-30
    assert award_on == date(2025, 7, 30)

    # The case is worked up to date: the R&R award is recorded on the day it is made.
    worked_to = date(2026, 8, 15)
    must_record(case, "RR_AWARD_S31", worked_to, {"award_no": "RR/1"}, on=worked_to)

    breached_before = _clock_rows(db, case)
    assert breached_before["COMPENSATION_3M"].status == "breached"  # due 2025-10-30
    assert breached_before["RR_MONETARY_6M"].status == "breached"  # due 2026-01-30
    assert float(_state(db, case).risk_score) == 100.0

    # Recorded today; it legally happened a year ago, inside the s.38(1) window.
    must_record(
        case,
        "PAYMENT_MADE",
        date(2025, 8, 10),
        {"pfms_ref": "PFMS/late", "amount_paise": assessed, "mode": "PFMS"},
        on=date(2026, 9, 1),
    )

    after = _clock_rows(db, case)
    assert after["COMPENSATION_3M"].status == "breached", after["COMPENSATION_3M"].status
    assert after["RR_MONETARY_6M"].status == "breached"
    assert after["RR_INFRA_18M"].elapsed_pct == breached_before["RR_INFRA_18M"].elapsed_pct
    state = _state(db, case)
    assert float(state.risk_score) == 100.0
    # The payment itself is still recorded — only the clock rewind is refused.
    assert int(state.comp_paid_paise) == assessed


def test_a_breach_a_read_discovered_is_not_rewound_either(
    db, world, client, auth, must_record
):
    """The review's own scenario: a case nobody has touched since the award, whose
    breach was discovered by the dashboard (a *read*), not by an event. Its ledger
    carries nothing recent, so the clamp also has to stand on what the clock rows
    themselves already prove — a row reading 'breached' can only have been written by an
    evaluation past its due date."""
    case = world.case(db)
    award_on, assessed = walk_to_awarded(must_record, case)

    # The dashboard reads the case a year later; that is what finds the breach.
    now = date(2026, 9, 1)
    clocks = clocks_on(client, case, auth(world.lao, now))
    assert clocks["COMPENSATION_3M"]["status"] == "breached"
    assert clocks["RR_MONETARY_6M"]["status"] == "breached"

    must_record(
        case,
        "PAYMENT_MADE",
        date(2025, 8, 10),
        {"pfms_ref": "PFMS/late", "amount_paise": assessed // 2, "mode": "PFMS"},
        on=now,
    )

    after = _clock_rows(db, case)
    assert after["COMPENSATION_3M"].status == "breached", after["COMPENSATION_3M"].status
    assert after["RR_MONETARY_6M"].status == "breached"
    assert float(_state(db, case).risk_score) == 100.0


def test_back_filling_a_case_still_evaluates_at_each_events_own_date(
    db, world, client, auth, must_record
):
    """The other direction. The seed, and an officer entering a case whose paper trail
    is two years old, record the whole history *today* in ascending legal order. Each
    event must still be evaluated as of the date it carries, or entering a case's past
    would trip the s.19(7) rescission that the very next back-filled event closes."""
    case = world.case(db)
    recorded_on = date(2026, 9, 1)  # everything below is typed in on one afternoon
    history = [
        ("SIA_NOTIFIED", date(2024, 11, 1), {"agency": "SIA Unit"}),
        ("EXPERT_GROUP_APPRAISAL", date(2024, 12, 1), {}),
        (
            "PRELIM_NOTIFICATION_S11",
            date(2025, 1, 1),
            {"gazette_no": "S.O. 1(E)", "total_area_ha": "12.5000"},
        ),
        ("RR_SCHEME_DRAFTED_S16", date(2025, 3, 2), {}),
        ("RR_SCHEME_APPROVED_S17", date(2025, 4, 1), {}),
        ("RR_SCHEME_PUBLISHED_S18", date(2025, 5, 1), {"scheme_ref": "RR/2025/1"}),
        (
            "COST_DEPOSITED_S19_2",
            date(2025, 5, 2),
            {"amount_paise": 9_00_00_000_00, "challan": "TR-6/1"},
        ),
        ("DECLARATION_S19", date(2025, 6, 30), {"gazette_no": "S.O. 2(E)"}),
    ]
    for event_type, when, payload in history:
        must_record(case, event_type, when, payload, on=recorded_on)

    rows = _clock_rows(db, case)
    # s.14: the notification came within 12 months of the appraisal — closed, in time.
    assert rows["S11_AFTER_APPRAISAL"].status == "closed"
    assert rows["S11_AFTER_APPRAISAL"].closed_on == date(2025, 1, 1)
    # s.19(7): the declaration was made inside the 12 months, so nothing is rescinded —
    # even though the whole history was typed in eight months after the deadline.
    assert rows["DECLARATION_S19"].status == "closed", rows["DECLARATION_S19"].status
    assert rows["DECLARATION_S19"].closed_on == date(2025, 6, 30)
    assert stage_of(db, case) == "DECLARED"

    recorded = event_types(client, case, auth(world.lao, recorded_on))
    assert "NOTIFICATION_RESCINDED" not in recorded
    assert "CASE_LAPSED" not in recorded


# --- rule-set version ordering ------------------------------------------------------


def test_the_no_pin_fallback_orders_versions_numerically(monkeypatch):
    """`sorted(candidates, key=lambda r: r.version)` is a string sort, so '2026.9'
    outranked '2026.10': a tenth revision of a track would sit in `rulesets/` fully
    loaded while every new project was still filed under the ninth.

    The rule-sets that ship are left alone — the orderings are built in memory.
    """
    from app.domain.rules import loader
    from app.domain.rules.loader import Ruleset, get_ruleset, version_sort_key

    assert version_sort_key("2026.9") < version_sort_key("2026.10")
    assert version_sort_key("2026.09") < version_sort_key("2026.10")
    assert version_sort_key("2026.10") < version_sort_key("2027.1")
    assert get_ruleset("RFCTLARR_2013").version == "2026.09"  # the shipped registry

    def ruleset(version: str, base: str | None = None) -> Ruleset:
        return Ruleset(
            track="SORT_TEST",
            version=version,
            stages={},
            transitions={},
            clocks=[],
            alerts={},
            raw={},
            base_version=base,
        )

    # Registry order must not decide the answer, so both insertion orders are tried.
    for order in (["2026.9", "2026.10"], ["2026.10", "2026.9"]):
        registry = {("SORT_TEST", v): ruleset(v) for v in order}
        # An overlay with the highest version of all: opt-in per case, never the
        # default a new project lands on.
        registry[("SORT_TEST", "2026.11")] = ruleset("2026.11", base="2026.10")
        monkeypatch.setattr(loader, "_REGISTRY", registry)

        assert get_ruleset("SORT_TEST").version == "2026.10", order
        assert get_ruleset("SORT_TEST", "2026.9").version == "2026.9"
        assert get_ruleset("SORT_TEST", "2026.11").base_version == "2026.10"


# --- EVENT_REVERSED -----------------------------------------------------------------


def test_reversing_a_payment_closes_the_s38_gate_again(
    db, world, client, auth, must_record, record
):
    """EVENT_REVERSED was appendable but projected nowhere: the reversed payment kept
    counting towards `comp_paid_paise`, so the s.38 possession gate stayed open on money
    the bank had sent back."""
    case = world.case(db)
    award_on, assessed = walk_to_awarded(must_record, case)
    payment = must_record(
        case,
        "PAYMENT_MADE",
        award_on + timedelta(days=10),
        {"pfms_ref": "PFMS/1", "amount_paise": assessed, "mode": "PFMS"},
    )

    def gate() -> dict:
        items = client.get(
            f"/api/v1/cases/{case.id}/allowed-events", headers=auth(world.lao)
        ).json()["items"]
        return next(i for i in items if i["type"] == "POSSESSION_TAKEN_S38")

    assert gate()["guard_status"]["ok"] is True  # paid in full

    status, body = record(
        case,
        "EVENT_REVERSED",
        award_on + timedelta(days=12),
        {
            "reversed_event_id": payment["id"],
            "reason": "PFMS returned the transfer; the payee account was closed",
        },
        user=world.collector,
    )
    assert status == 201, body
    assert body["stage"] == "AWARDED"  # a correction moves no stage

    state = _state(db, case)
    assert int(state.comp_paid_paise) == 0
    assert int(state.comp_assessed_paise) == assessed
    assert gate()["guard_status"]["ok"] is False

    status, body = record(
        case, "POSSESSION_TAKEN_S38", award_on + timedelta(days=13), {}
    )
    assert status == 422, body
    assert body["type"] == "guard_failed"
    assert body["errors"][0]["comp_paid_paise"] == 0
    assert body["errors"][0]["comp_assessed_paise"] == assessed
    assert stage_of(db, case) == "AWARDED"


def test_reversing_the_latest_assessment_falls_back_to_the_one_before_it(
    db, world, client, auth, must_record, record
):
    """s.64 enhancements replace the assessed figure, so withdrawing one has to restore
    the assessment it superseded — not zero, and not the enhanced figure."""
    case = world.case(db)
    award_on, assessed = walk_to_awarded(must_record, case)
    enhanced = must_record(
        case,
        "COMPENSATION_ASSESSED",
        award_on + timedelta(days=20),
        {"assessed_total_paise": assessed * 5, "line_count": 1},
    )
    assert int(_state(db, case).comp_assessed_paise) == assessed * 5

    must_record(
        case,
        "EVENT_REVERSED",
        award_on + timedelta(days=21),
        {"reversed_event_id": enhanced["id"], "reason": "keyed against the wrong award"},
    )
    assert int(_state(db, case).comp_assessed_paise) == assessed

    # Withdraw the original too and nothing stands assessed, which closes the gate.
    original = [
        e
        for e in client.get(
            f"/api/v1/cases/{case.id}/events?limit=500", headers=auth(world.lao)
        ).json()["items"]
        if e["type"] == "COMPENSATION_ASSESSED"
    ][-1]
    must_record(
        case,
        "EVENT_REVERSED",
        award_on + timedelta(days=22),
        {"reversed_event_id": original["id"], "reason": "no award was ever valued"},
    )
    assert int(_state(db, case).comp_assessed_paise) == 0

    status, body = record(
        case, "POSSESSION_TAKEN_S38", award_on + timedelta(days=23), {}
    )
    assert status == 422, body
    assert body["type"] == "guard_failed"


def test_a_reversal_may_only_name_an_event_of_its_own_case(
    db, world, client, auth, must_record, record
):
    """`reversed_event_id` was never looked at, so a correction could be filed against
    an event of another case — a permanent, hash-chained marker pointing at nothing on
    the case that carries it."""
    case = world.case(db)
    other = world.case(db)
    walk_to_notified(must_record, case)
    foreign = must_record(other, "SIA_NOTIFIED", date(2025, 1, 5), {"agency": "SIA Unit"})

    status, body = record(
        case,
        "EVENT_REVERSED",
        date(2025, 2, 1),
        {"reversed_event_id": foreign["id"], "reason": "recorded against the wrong case"},
        user=world.collector,
    )
    assert status == 422, body
    assert body["type"] == "validation_error"
    assert body["errors"][0]["field"] == "payload.reversed_event_id"
    assert body["errors"][0]["message"] == "not an event of this case"

    for payload in (
        {"reason": "no target at all"},
        {"reversed_event_id": "not-a-uuid", "reason": "typo"},
        {"reversed_event_id": "", "reason": "blank"},
    ):
        status, body = record(
            case, "EVENT_REVERSED", date(2025, 2, 1), payload, user=world.collector
        )
        assert status == 422, body
        assert body["errors"][0]["message"] == "missing or not a uuid", payload

    assert "EVENT_REVERSED" not in event_types(client, case, auth(world.lao))


def test_only_a_collector_or_above_may_reverse_an_event(
    db, world, client, auth, must_record, record
):
    """Docs/APIs.md §3.4: EVENT_REVERSED is 'Collector or above'. It was open to every
    role the append endpoint accepts, so an LAO could withdraw their own entries."""
    case = world.case(db)
    first = must_record(case, "SIA_NOTIFIED", date(2025, 1, 5), {"agency": "SIA Unit"})
    payload = {
        "reversed_event_id": first["id"],
        "reason": "the agency named in the order is a different one",
    }

    status, body = record(
        case, "EVENT_REVERSED", date(2025, 1, 6), payload, user=world.lao
    )
    assert status == 404, body  # gated exactly like EXTENSION_GRANTED
    assert "EVENT_REVERSED" not in event_types(client, case, auth(world.lao))

    status, body = record(
        case, "EVENT_REVERSED", date(2025, 1, 6), payload, user=world.collector
    )
    assert status == 201, body
    assert "EVENT_REVERSED" in event_types(client, case, auth(world.lao))


def test_a_rebuild_reproduces_the_projection_after_reversals(
    db, world, client, auth, must_record
):
    """`rebuild_case` skips a reversed non-transition event rather than folding it in
    and taking it back out again, so the replay and the incremental fold must land on
    exactly the same figures. Transitions replay either way: a reversal corrects the
    numbers, it does not un-lapse or otherwise rewind a stage."""
    case = world.case(db)
    assessed = 10_00_000
    declared_on = walk_to_declared(must_record, case)  # 2025-06-30
    family = must_record(
        case,
        "FAMILY_ENUMERATED",
        declared_on + timedelta(days=1),
        {"count": 3, "displaced": True, "displaced_count": 2},
    )
    award_on = declared_on + timedelta(days=30)
    must_record(case, "AWARD_S23", award_on, {"award_no": "AWD/1"})
    must_record(
        case,
        "COMPENSATION_ASSESSED",
        award_on + timedelta(days=5),
        {"assessed_total_paise": assessed, "line_count": 1},
    )
    must_record(
        case,
        "PAYMENT_MADE",
        award_on + timedelta(days=9),
        {"pfms_ref": "PFMS/1", "amount_paise": 4_00_000, "mode": "PFMS"},
    )
    second_payment = must_record(
        case,
        "PAYMENT_MADE",
        award_on + timedelta(days=10),
        {"pfms_ref": "PFMS/2", "amount_paise": 6_00_000, "mode": "PFMS"},
    )
    enhanced = must_record(
        case,
        "COMPENSATION_ASSESSED",
        award_on + timedelta(days=11),
        {"assessed_total_paise": assessed * 5, "line_count": 1},
    )
    for target, when, why in (
        (second_payment, 12, "PFMS returned the transfer"),
        (enhanced, 13, "keyed against the wrong award"),
        (family, 14, "the household was enumerated twice"),
        # The same correction recorded a second time withdraws nothing further: the
        # incremental fold must not subtract twice where the replay skips once.
        (second_payment, 15, "the reversal was entered again by mistake"),
    ):
        must_record(
            case,
            "EVENT_REVERSED",
            award_on + timedelta(days=when),
            {"reversed_event_id": target["id"], "reason": why},
        )

    incremental = _figures(_state(db, case))
    assert incremental["comp_assessed_paise"] == assessed
    assert incremental["comp_paid_paise"] == 4_00_000
    assert incremental["families_affected"] == 0
    assert incremental["families_displaced"] == 0
    assert incremental["stage"] == "AWARDED"

    as_of = award_on + timedelta(days=15)
    res = client.post(
        f"/api/v1/cases/{case.id}/rebuild", headers=auth(world.collector, as_of)
    )
    assert res.status_code == 200, res.text
    assert _figures(_state(db, case)) == incremental


# --- risk drivers -------------------------------------------------------------------


def test_a_suspended_clock_drives_none_of_the_risk_score(
    db, world, client, auth, must_record
):
    """A clock a court has stopped scores nothing, but its elapsed fraction keeps
    climbing while the stay is on — so the drivers panel reported weight 100.0 beside a
    score of 0 and contradicted the number printed above it."""
    stayed = world.case(db)
    walk_to_notified(must_record, stayed)
    must_record(
        stayed, "COURT_STAY", date(2025, 3, 1), {"court": "High Court", "case_no": "WP 9/2025"}
    )

    body = client.get(
        f"/api/v1/cases/{stayed.id}/risk", headers=auth(world.lao, date(2027, 3, 1))
    ).json()
    assert body["score"] == 0
    driver = next(d for d in body["drivers"] if d["clock_id"] == "DECLARATION_S19")
    assert driver["status"] == "suspended"
    assert driver["elapsed_pct"] == 100.0  # the clock really has run its whole span
    assert driver["weight"] == 0.0  # but it contributes nothing to the score
    assert driver["counts_towards_score"] is False
    assert body["score"] == max(d["weight"] for d in body["drivers"])

    # Control: an ordinary running clock still drives the score it is shown beside.
    running = world.case(db)
    walk_to_notified(must_record, running)
    body = client.get(
        f"/api/v1/cases/{running.id}/risk", headers=auth(world.lao, date(2025, 12, 7))
    ).json()
    driver = next(d for d in body["drivers"] if d["clock_id"] == "DECLARATION_S19")
    assert driver["status"] == "running"
    assert driver["counts_towards_score"] is True
    assert driver["weight"] == driver["elapsed_pct"]
    assert body["score"] == max(d["weight"] for d in body["drivers"])
