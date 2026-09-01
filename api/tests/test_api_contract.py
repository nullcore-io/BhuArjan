"""The /v1 surface lane B1 owns — auth, projects, cases, the ledger endpoints.

Docs/APIs.md §3.1–3.4. These check the contract other lanes and the web client are
written against: the shapes, the RFC 7807 problem types, and the jurisdiction rule that
an out-of-scope resource is a 404 and never a 403.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from tests.conftest import TEST_PASSWORD, stage_of
from tests.helpers import S11_DEFAULT, walk_to_notified


# --- auth --------------------------------------------------------------------------


def test_token_and_me_carry_roles_and_org_unit_scopes(db, world, client):
    res = client.post(
        "/api/v1/auth/token",
        json={"username": world.lao.email, "password": TEST_PASSWORD},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expires_in"] > 0
    assert body["user"]["roles"] == ["LAO"]

    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    payload = me.json()
    assert payload["id"] == str(world.lao.id)
    assert payload["roles"] == ["LAO"]
    assert payload["scopes"] == [str(world.district.id)]
    assert payload["jurisdiction"][0]["kind"] == "district"


def test_bad_password_is_401_and_says_nothing_useful(db, world, client):
    res = client.post(
        "/api/v1/auth/token", json={"username": world.lao.email, "password": "wrong"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "invalid username or password"

    missing = client.post(
        "/api/v1/auth/token", json={"username": "nobody@test", "password": "wrong"}
    )
    assert missing.json()["detail"] == res.json()["detail"]


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/v1/projects").status_code == 401


# --- projects ----------------------------------------------------------------------


def test_project_create_pins_the_ruleset_version(db, world, client, auth):
    rb = client.post(
        "/api/v1/auth/token",
        json={"username": world.ministry_user.email, "password": TEST_PASSWORD},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {rb}"}

    res = client.post(
        "/api/v1/projects",
        json={
            "name": "NH-44 test package",
            "sector": "National Highways",
            "statute_track": "NH_ACT_1956",
            "state_code": "ts",
            "requiring_body_id": str(world.body.id),
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["statute_track"] == "NH_ACT_1956"
    assert body["ruleset_version"] == "2026.09"
    assert body["case_count"] == 0

    listed = client.get("/api/v1/projects?statute=NH_ACT_1956", headers=headers).json()
    assert body["id"] in [p["id"] for p in listed["items"]]


def test_unknown_statute_track_is_rejected(db, world, client):
    token = client.post(
        "/api/v1/auth/token",
        json={"username": world.ministry_user.email, "password": TEST_PASSWORD},
    ).json()["access_token"]
    res = client.post(
        "/api/v1/projects",
        json={"name": "x", "statute_track": "MADE_UP_ACT_1900"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422
    assert res.json()["type"] == "validation_error"


def test_lao_may_not_create_a_project(db, world, client, auth):
    res = client.post(
        "/api/v1/projects", json={"name": "x"}, headers=auth(world.lao)
    )
    assert res.status_code == 404  # not 403 — Docs/APIs.md §1


def test_project_detail_carries_kpis_and_its_cases(db, world, client, auth, must_record):
    case = world.case(db)
    walk_to_notified(must_record, case)

    res = client.get(f"/api/v1/projects/{case.project_id}", headers=auth(world.lao))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["kpis"]["area_notified_ha"] == 12.5
    assert body["kpis"]["notifications_issued"] == 1
    assert body["as_of_seq"] > 0
    row = next(c for c in body["cases"] if c["id"] == str(case.id))
    assert row["stage"] == "NOTIFIED"
    assert row["district_name"] == world.district.name
    assert row["next_clock_id"] in ("DECLARATION_S19", "OBJECTION_WINDOW")


# --- cases -------------------------------------------------------------------------


def test_create_case_starts_at_the_first_stage(db, world, client, auth):
    project = world.project(db)
    db.commit()
    res = client.post(
        "/api/v1/cases",
        json={
            "project_id": str(project.id),
            "district_id": str(world.district.id),
            "case_no": "LAQ/T/1",
        },
        headers=auth(world.lao),
    )
    assert res.status_code == 201, res.text
    assert res.json()["stage"] == "PROPOSED"
    assert res.json()["ruleset_version"] == "2026.09"


def test_case_detail_shape(db, world, client, auth, must_record):
    case = world.case(db)
    walk_to_notified(must_record, case)

    # A demo date inside the s.19 window: without one the read would evaluate against
    # the real today, and the 2026-01-01 deadline would (correctly) have lapsed.
    on = S11_DEFAULT + timedelta(days=30)
    body = client.get(f"/api/v1/cases/{case.id}", headers=auth(world.lao, on)).json()
    assert body["stage"] == "NOTIFIED"
    assert body["district_name"] == world.district.name
    assert body["project_name"]
    assert body["case_state"]["area_notified_ha"] == 12.5
    assert body["case_state"]["comp_assessed"] == body["case_state"]["comp_assessed_paise"]
    assert len(body["events"]) == 3
    assert body["events"][0]["seq"] > body["events"][1]["seq"]  # newest first
    assert {c["clock_id"] for c in body["clocks"]} >= {
        "S11_AFTER_APPRAISAL", "OBJECTION_WINDOW", "DECLARATION_S19"
    }


def test_out_of_jurisdiction_case_is_404(db, world, client, auth):
    from app.models import Case, OrgUnit, Project

    other_district = OrgUnit(kind="district", name="Elsewhere")
    db.add(other_district)
    db.flush()
    project = Project(
        name="Other", statute_track="RFCTLARR_2013", ruleset_version="2026.09"
    )
    db.add(project)
    db.flush()
    other = Case(
        project_id=project.id,
        district_id=other_district.id,
        statute_track="RFCTLARR_2013",
        ruleset_version="2026.09",
    )
    db.add(other)
    db.commit()

    assert client.get(f"/api/v1/cases/{other.id}", headers=auth(world.lao)).status_code == 404
    assert client.get(f"/api/v1/cases/{uuid.uuid4()}", headers=auth(world.lao)).status_code == 404


def test_allowed_events_reports_sections_and_unmet_preconditions(
    db, world, client, auth, must_record
):
    case = world.case(db)
    walk_to_notified(must_record, case)

    body = client.get(
        f"/api/v1/cases/{case.id}/allowed-events", headers=auth(world.lao)
    ).json()
    assert body["stage"] == "NOTIFIED"
    assert body["ruleset"] == "RFCTLARR_2013@2026.09"

    by_type = {a["type"]: a for a in body["items"]}
    s19 = by_type["DECLARATION_S19"]
    assert s19["section"] == "s.19"
    assert s19["to_stage"] == "DECLARED"
    assert s19["requires_met"] is False
    assert {r["type"]: r["satisfied"] for r in s19["requires"]} == {
        "RR_SCHEME_PUBLISHED_S18": False,
        "COST_DEPOSITED_S19_2": False,
    }
    assert by_type["OBJECTION_RECEIVED"]["is_transition"] is False
    assert by_type["OBJECTION_RECEIVED"]["document_required"] is False
    assert "AWARD_S23" not in by_type  # not reachable from NOTIFIED


def test_transition_from_the_wrong_stage_names_the_ruleset(db, world, client, record):
    case = world.case(db)
    status, body = record(case, "AWARD_S23", date(2025, 1, 1), {})
    assert status == 422
    assert body["type"] == "transition_not_allowed"
    assert body["ruleset_ref"] == "RFCTLARR_2013@2026.09/transitions/AWARD_S23"
    assert "PROPOSED" in body["detail"]


def test_event_outside_the_stage_on_list_is_refused(db, world, client, record):
    case = world.case(db)
    status, body = record(case, "CLAIMS_RECEIVED", date(2025, 1, 1), {})
    assert status == 422
    assert body["type"] == "transition_not_allowed"
    assert body["ruleset_ref"] == "RFCTLARR_2013@2026.09/stages/PROPOSED"


def test_statutory_event_without_paper_is_refused(db, world, client, record):
    case = world.case(db)
    status, body = record(
        case, "SIA_NOTIFIED", date(2025, 1, 1), {}, no_document_reason=None
    )
    assert status == 422
    assert body["type"] == "document_required"
    assert "s.4(1)" in body["detail"]

    # A recorded reason is enough — Docs/rules.md C1.
    status, _ = record(
        case, "SIA_NOTIFIED", date(2025, 1, 1), {},
        no_document_reason="gazette copy awaited from the press",
    )
    assert status == 201


def test_operational_events_do_not_demand_a_document(db, world, client, record, must_record):
    case = world.case(db)
    walk_to_notified(must_record, case)
    status, body = record(
        case, "PARCEL_ADDED", S11_DEFAULT + timedelta(days=5),
        {"survey_no": "1/1", "area_ha": "2.0000"},
        no_document_reason=None,
    )
    assert status == 201, body


def test_unknown_event_type_is_a_validation_error(db, world, client, record):
    case = world.case(db)
    status, body = record(case, "NOT_AN_EVENT", date(2025, 1, 1), {})
    assert status == 422
    assert body["type"] == "validation_error"


def test_if_match_mismatch_is_409_stale_state(db, world, client, auth, record, must_record):
    case = world.case(db)
    walk_to_notified(must_record, case)
    status, body = record(
        case, "OBJECTION_RECEIVED", S11_DEFAULT + timedelta(days=5), {"count": 2},
        if_match=1,
    )
    assert status == 409
    assert body["type"] == "stale_state"

    on = S11_DEFAULT + timedelta(days=5)
    current = client.get(
        f"/api/v1/cases/{case.id}", headers=auth(world.lao, on)
    ).json()["case_state"]["as_of_seq"]
    status, body = record(
        case, "OBJECTION_RECEIVED", S11_DEFAULT + timedelta(days=5), {"count": 2},
        if_match=current,
    )
    assert status == 201, body


def test_extension_granted_needs_a_collector(db, world, client, record, must_record):
    case = world.case(db)
    walk_to_notified(must_record, case)
    payload = {
        "clock_id": "DECLARATION_S19",
        "authority": "State Government",
        "reasons": "objections pending",
        "new_due_date": "2026-06-30",
    }
    status, _ = record(case, "EXTENSION_GRANTED", date(2025, 12, 1), payload, user=world.lao)
    assert status == 404  # LAO cannot grant an extension

    status, _ = record(
        case, "EXTENSION_GRANTED", date(2025, 12, 1), payload, user=world.collector
    )
    assert status == 201


def test_event_paging_walks_backwards(db, world, client, auth, must_record):
    case = world.case(db)
    walk_to_notified(must_record, case)
    headers = auth(world.lao)

    first = client.get(f"/api/v1/cases/{case.id}/events?limit=2", headers=headers).json()
    assert len(first["items"]) == 2
    assert first["total"] == 3
    assert first["next_cursor"] is not None

    second = client.get(
        f"/api/v1/cases/{case.id}/events?limit=2&cursor={first['next_cursor']}",
        headers=headers,
    ).json()
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    seqs = [e["seq"] for e in first["items"] + second["items"]]
    assert seqs == sorted(seqs, reverse=True)

    filtered = client.get(
        f"/api/v1/cases/{case.id}/events?type=SIA_NOTIFIED", headers=headers
    ).json()
    assert [e["type"] for e in filtered["items"]] == ["SIA_NOTIFIED"]


def test_risk_score_tracks_the_most_elapsed_clock(db, world, client, auth, must_record):
    case = world.case(db)
    walk_to_notified(must_record, case)

    # 2025-01-01 -> 2026-01-01; 340 days in is 93% elapsed.
    body = client.get(
        f"/api/v1/cases/{case.id}/risk", headers=auth(world.lao, date(2025, 12, 7))
    ).json()
    assert 92 <= body["score"] <= 95, body
    driver = next(d for d in body["drivers"] if d["clock_id"] == "DECLARATION_S19")
    assert driver["basis"] == "s.19(7)"
    assert driver["days_left"] == 25


def test_alerts_climb_the_escalation_ladder_once_per_level(
    db, world, client, auth, must_record
):
    """Docs/rules.md C2: amber at 75%, red at 90%, one alert per (case, clock, level),
    escalating LAO -> Collector -> State -> Ministry."""
    case = world.case(db)
    walk_to_notified(must_record, case)

    # 2025-01-01 -> 2026-01-01. 300 days in is 82% (amber); 340 is 93% (red).
    amber_day = auth(world.lao, S11_DEFAULT + timedelta(days=300))
    red_day = auth(world.lao, S11_DEFAULT + timedelta(days=340))
    client.get(f"/api/v1/cases/{case.id}/clocks", headers=amber_day)
    client.get(f"/api/v1/cases/{case.id}/clocks", headers=amber_day)  # idempotent
    client.get(f"/api/v1/cases/{case.id}/clocks", headers=red_day)
    client.get(f"/api/v1/cases/{case.id}/clocks", headers=red_day)

    body = client.get(f"/api/v1/alerts?case_id={case.id}", headers=red_day).json()
    rows = [a for a in body["items"] if a["clock_id"] == "DECLARATION_S19"]
    assert sorted(a["level"] for a in rows) == ["amber", "red"], body
    assert {a["level"]: a["escalated_to_role"] for a in rows} == {
        "amber": "LAO", "red": "COLLECTOR",
    }

    # Past the deadline the ladder goes to the State, and only once.
    lapsed_day = auth(world.lao, S11_DEFAULT + timedelta(days=366))
    client.get(f"/api/v1/cases/{case.id}/clocks", headers=lapsed_day)
    client.get(f"/api/v1/cases/{case.id}/clocks", headers=lapsed_day)
    body = client.get(f"/api/v1/alerts?case_id={case.id}", headers=lapsed_day).json()
    rows = [a for a in body["items"] if a["clock_id"] == "DECLARATION_S19"]
    assert sorted(a["level"] for a in rows) == ["amber", "lapsed", "red"]
    assert next(a for a in rows if a["level"] == "lapsed")["escalated_to_role"] == "MINISTRY"


def test_rebuild_replays_the_ledger_into_the_projection(db, world, client, auth, must_record):
    from app.models import CaseState

    case = world.case(db)
    walk_to_notified(must_record, case)

    state = db.get(CaseState, case.id)
    db.refresh(state)
    state.stage = "PROPOSED"
    state.area_notified_ha = 0
    db.commit()

    res = client.post(
        f"/api/v1/cases/{case.id}/rebuild", headers=auth(world.collector, S11_DEFAULT)
    )
    assert res.status_code == 200, res.text
    rebuilt = res.json()["case_state"]
    assert rebuilt["stage"] == "NOTIFIED"
    assert rebuilt["area_notified_ha"] == 12.5
    assert stage_of(db, case) == "NOTIFIED"


def test_the_no_document_path_is_collector_level(db, world, client, auth, record):
    """rules.md C1: an explicit no-document reason is recorded by a Collector-level
    role; an LAO posting one gets document_required, not a committed event."""
    from datetime import date

    case = world.case(db, "NH_ACT_1956")
    status, body = record(
        case, "NOTIFICATION_3A", date(2025, 1, 1), {},
        user=world.lao, no_document_reason="LAO trying the collector-only path",
    )
    assert status == 422
    assert body["type"] == "document_required"
    # The same append by the Collector commits.
    status2, body2 = record(
        case, "NOTIFICATION_3A", date(2025, 1, 1), {},
        user=world.collector, no_document_reason="entry made on the Collector's order",
    )
    assert status2 == 201, body2
