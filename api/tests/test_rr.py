"""Module F — R&R and affected families (Docs/APIs.md §3.8, Docs/rules.md C5, B4).

The questions these tests actually ask:

  * Does the register hide names from everyone by default?
  * Does a purpose plus the right role release them, and is that release written into
    the audit register with the purpose that was given?
  * Does a role without the entitlement stay masked even when it supplies a purpose?
  * Does enumerating a family reach the ledger and move `families_affected`?
  * Does delivering a Second Schedule head flip that head and only that head, and does
    the rule-set still decide when a delivery may be recorded at all?
  * Do the summary counts add up?
  * And the one that matters most: **is there a name anywhere in `events.payload`?**
    The ledger is hash-chained and un-deletable, so a name that lands there is a name
    that can never be erased. That test is the DPDP promise in Docs/rules.md C5.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import World
from tests.helpers import S11_DEFAULT, pay, satisfy_s19_preconditions, walk_to_notified

# A full Aadhaar-shaped string the officer might paste into the form. It must never be
# stored: only its last four characters may survive the write.
FULL_ID = "4321 8765 1098"
BANK_REF = "000111222333"
NAME_A = "Zubeida Khatoon Ansari"
NAME_B = "Harphool Singh Rathore"
# Deliberately not the fixture village ("Testpur"): a village named in a gazette
# notification is public record and does appear in event payloads, so testing for a
# leak with that name would prove nothing.
VILLAGE = "Bakhari Buzurg"

ALL_HEADS = 10  # len(SECOND_SCHEDULE)


# --- helpers -----------------------------------------------------------------------


def res_text(body: dict) -> str:
    return json.dumps(body, default=str)


def _user(db, role: str, org_unit_id):
    """Another officer of a rank the shared `World` does not carry."""
    user = World._user(db, f"{role.lower()}-{uuid.uuid4().hex[:8]}@test", role, org_unit_id)
    db.commit()
    return user


def _enumerate(
    client,
    auth,
    case,
    name: str,
    *,
    user=None,
    on: date = date(2025, 2, 3),
    displaced: bool = False,
    sc_st: bool = False,
    category: str = "agricultural landowner",
) -> dict:
    res = client.post(
        f"/api/v1/cases/{case.id}/families",
        json={
            "head": {
                "name": name,
                "guardian": "Guardian " + name.split()[-1],
                "id_ref": FULL_ID,
                "bank_ref": BANK_REF,
                "village": VILLAGE,
            },
            "category": category,
            "displaced": displaced,
            "sc_st": sc_st,
            "occurred_at": on.isoformat(),
        },
        headers={**auth(user, on), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _families(client, auth, case, *, user=None, purpose: str | None = None, on=None, **params):
    query = dict(params)
    if purpose is not None:
        query["purpose"] = purpose
    res = client.get(
        f"/api/v1/cases/{case.id}/families", params=query, headers=auth(user, on)
    )
    assert res.status_code == 200, res.text
    return res.json()


def _walk_to_possessed(must_record, case, s11: date = S11_DEFAULT) -> date:
    """NOTIFIED -> ... -> POSSESSED. The caller enumerates families while the case is
    still NOTIFIED, because that is where the rule-set puts the census."""
    satisfy_s19_preconditions(must_record, case, s11 + timedelta(days=120))
    declared_on = s11 + timedelta(days=180)
    must_record(case, "DECLARATION_S19", declared_on,
                {"gazette_no": "S.O. 2(E)", "total_area_ha": "12.5000"})
    award_on = declared_on + timedelta(days=30)
    must_record(case, "AWARD_S23", award_on, {"award_no": "AWD/1"})
    must_record(case, "COMPENSATION_ASSESSED", award_on + timedelta(days=5),
                {"assessed_total_paise": 10_00_000, "line_count": 1})
    pay(must_record, case, award_on + timedelta(days=10), 10_00_000)
    possession_on = award_on + timedelta(days=20)
    must_record(case, "POSSESSION_TAKEN_S38", possession_on, {"memo_no": "POSS/1"})
    return possession_on


@pytest.fixture()
def notified_case(db, world, must_record):
    case = world.case(db)
    walk_to_notified(must_record, case)
    return case


# --- masking -----------------------------------------------------------------------


def test_the_register_is_masked_for_everyone_by_default(client, auth, world, notified_case):
    """No purpose, no name — whatever the caller's rank (Docs/rules.md C5)."""
    _enumerate(client, auth, notified_case, NAME_A, user=world.collector, displaced=True)

    # Ministry is deliberately absent: Docs/APIs.md §2 gives it 'aggregate' on this
    # row, which is /rr/summary — the register itself is a 404 for it.
    for who in (world.lao, world.collector):
        body = _families(client, auth, notified_case, user=who)
        assert body["pii"] == "masked", who
        assert body["total"] == 1
        row = body["items"][0]
        assert "head" not in row, f"{who.name} was handed the PII blob without asking"
        assert row["ref"] == "Family ZKA"  # initials only, per core.crypto.mask_name
        assert row["category"] == "agricultural landowner"
        assert row["displaced"] is True
        # Caste is sensitive personal data: it is not on the masked row at all.
        assert "sc_st" not in row
        assert NAME_A not in res_text(body)
        assert VILLAGE not in res_text(body)
        assert body["masked_reason"]


def test_a_collector_with_a_purpose_sees_the_names_and_the_read_is_audited(
    client, auth, world, notified_case
):
    created = _enumerate(client, auth, notified_case, NAME_A, user=world.collector)
    purpose = "s.31 R&R award verification for LAQ hearing on 2026-03-04"

    body = _families(client, auth, notified_case, user=world.collector, purpose=purpose)
    assert body["pii"] == "unlocked"
    assert body["purpose"] == purpose
    head = body["items"][0]["head"]
    assert head["name"] == NAME_A
    assert head["village"] == VILLAGE
    # The full identifier was never stored, so it cannot be released.
    assert head["id_ref_last4"] == "1098"
    assert FULL_ID not in res_text(body)
    assert FULL_ID.replace(" ", "") not in res_text(body)

    audit = client.get(
        "/api/v1/admin/audit", params={"action": "PII_READ"},
        headers=auth(world.collector),
    )
    assert audit.status_code == 200, audit.text
    rows = [r for r in audit.json()["items"] if r["target"] == created["id"]]
    assert len(rows) == 1, "an unlocked read must write exactly one PII_READ row"
    assert rows[0]["meta"]["purpose"] == purpose
    assert "name" in rows[0]["meta"]["fields"]
    assert rows[0]["user_id"] == str(world.collector.id)


def test_a_masked_read_writes_no_audit_row(client, auth, world, notified_case):
    """Initials are public-safe (rules.md C5) and are stored in the clear, so a masked
    read never touches the key — and must not fill the register with empty rows."""
    created = _enumerate(client, auth, notified_case, NAME_B, user=world.collector)
    _families(client, auth, notified_case, user=world.collector)  # no purpose
    _families(client, auth, notified_case, user=world.lao, purpose="curiosity")

    audit = client.get(
        "/api/v1/admin/audit", params={"action": "PII_READ"},
        headers=auth(world.collector),
    )
    assert [r for r in audit.json()["items"] if r["target"] == created["id"]] == []


def test_an_lao_with_a_purpose_is_still_masked(client, auth, world, notified_case):
    """A purpose is necessary, not sufficient: Docs/APIs.md §2 gives LAO the masked
    register only."""
    _enumerate(client, auth, notified_case, NAME_A, user=world.collector)
    body = _families(
        client, auth, notified_case, user=world.lao,
        purpose="I would like to see the names",
    )
    assert body["pii"] == "masked"
    assert "head" not in body["items"][0]
    assert NAME_A not in res_text(body)
    assert "role" in body["masked_reason"]


def test_admin_rr_unlocks_state_stays_masked_and_ministry_gets_the_aggregate_only(
    db, client, auth, world, notified_case
):
    """Docs/APIs.md §2: R&R PII is 'full (purpose)' for the Collector and the
    Administrator R&R only; State Revenue sees masked rows; the Ministry's entry on
    that row is 'aggregate', which is /rr/summary, not a masked family list."""
    _enumerate(client, auth, notified_case, NAME_A, user=world.collector)
    admin_rr = _user(db, "ADMIN_RR", world.district.id)
    state = _user(db, "STATE_REVENUE", world.state.id)

    body = _families(client, auth, notified_case, user=admin_rr, purpose="R&R disbursement audit")
    assert body["pii"] == "unlocked"
    assert body["items"][0]["head"]["name"] == NAME_A

    body = _families(client, auth, notified_case, user=state, purpose="state scrutiny")
    assert body["pii"] == "masked"
    assert NAME_A not in res_text(body)

    denied = client.get(
        f"/api/v1/cases/{notified_case.id}/families",
        params={"purpose": "national R&R review"},
        headers=auth(world.ministry_user),
    )
    assert denied.status_code == 404, denied.text
    summary = client.get(
        f"/api/v1/cases/{notified_case.id}/rr/summary",
        headers=auth(world.ministry_user, "2025-03-01"),
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["families"]["total"] == 1


# --- enumeration -------------------------------------------------------------------


def test_enumeration_reaches_the_ledger_and_moves_families_affected(
    client, auth, world, notified_case
):
    # Read the case as of a date inside its own life: `GET /cases/{id}` evaluates the
    # clocks as of the effective date, and asking "as of today" would lapse a 2025 case
    # under s.19(7) before the census could be recorded.
    before = client.get(
        f"/api/v1/cases/{notified_case.id}", headers=auth(world.lao, "2025-02-01")
    )
    assert before.json()["case_state"]["families_affected"] == 0

    a = _enumerate(client, auth, notified_case, NAME_A, user=world.collector, displaced=True)
    b = _enumerate(client, auth, notified_case, NAME_B, user=world.collector, displaced=False)
    assert a["entitlements"]["house"] == {
        "status": "due", "delivered_on": None, "evidence_document_id": None
    }
    assert len(a["entitlements"]) == ALL_HEADS
    assert a["heads_due"] == ALL_HEADS and a["heads_delivered"] == 0

    after = client.get(
        f"/api/v1/cases/{notified_case.id}", headers=auth(world.lao, "2025-02-04")
    )
    state = after.json()["case_state"]
    assert state["families_affected"] == 2
    assert state["families_displaced"] == 1

    events = client.get(
        f"/api/v1/cases/{notified_case.id}/events",
        params={"type": "FAMILY_ENUMERATED"}, headers=auth(world.lao),
    ).json()["items"]
    assert len(events) == 2
    payloads = {e["payload"]["family_id"]: e["payload"] for e in events}
    assert set(payloads) == {a["id"], b["id"]}
    assert payloads[a["id"]]["displaced"] is True
    assert payloads[a["id"]]["count"] == 1
    assert payloads[b["id"]]["displaced"] is False


def test_enumeration_is_refused_where_the_rule_set_does_not_allow_it(
    db, client, auth, world
):
    """`FAMILY_ENUMERATED` is allowed from notification onward (a family found after
    the award still has s.38(1) entitlements) but not on a case nobody has notified
    yet: there is no acquisition to be affected by. The ledger says so."""
    proposed_case = world.case(db)  # PROPOSED: no SIA, no s.11
    res = client.post(
        f"/api/v1/cases/{proposed_case.id}/families",
        json={"head": {"name": NAME_A}, "category": "landowner", "displaced": False,
              "sc_st": False, "occurred_at": "2025-09-01"},
        headers={**auth(world.collector, "2025-09-01"), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert res.status_code == 422, res.text
    assert res.json()["type"] == "transition_not_allowed"
    assert "PROPOSED" in res.json()["detail"]


def test_a_family_needs_a_name(client, auth, world, notified_case):
    res = client.post(
        f"/api/v1/cases/{notified_case.id}/families",
        json={"head": {"name": "   "}, "displaced": False, "sc_st": False},
        headers={**auth(world.collector), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert res.status_code == 422, res.text
    assert res.json()["type"] == "validation_error"


def test_a_retried_enumeration_returns_the_same_family(client, auth, world, notified_case):
    """A dropped connection must not enumerate the family twice — and must not read as
    a validation error on a request that already succeeded."""
    key = str(uuid.uuid4())
    body = {
        "head": {"name": NAME_A, "village": VILLAGE},
        "category": "agricultural landowner",
        "displaced": True,
        "sc_st": False,
        "occurred_at": "2025-02-03",
    }
    headers = {**auth(world.collector, "2025-02-03"), "Idempotency-Key": key}
    first = client.post(f"/api/v1/cases/{notified_case.id}/families", json=body, headers=headers)
    second = client.post(f"/api/v1/cases/{notified_case.id}/families", json=body, headers=headers)
    assert first.status_code == 201 and second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["seq"] == first.json()["seq"]
    assert second.json()["duplicate"] is True
    assert second.headers.get("Idempotent-Replay") == "true"

    listed = _families(client, auth, notified_case, user=world.lao)
    assert listed["total"] == 1, "the retry minted a second family"
    state = client.get(
        f"/api/v1/cases/{notified_case.id}", headers=auth(world.lao, "2025-02-04")
    ).json()["case_state"]
    assert state["families_affected"] == 1


def test_the_register_pages(client, auth, world, notified_case):
    for i in range(5):
        _enumerate(client, auth, notified_case, f"Paging Family {i}", user=world.collector)
    first = _families(client, auth, notified_case, user=world.lao, limit=2)
    assert len(first["items"]) == 2 and first["total"] == 5 and first["next_cursor"]
    second = _families(
        client, auth, notified_case, user=world.lao, limit=2, cursor=first["next_cursor"]
    )
    assert len(second["items"]) == 2
    assert {r["id"] for r in first["items"]}.isdisjoint({r["id"] for r in second["items"]})


# --- delivery ----------------------------------------------------------------------


def test_delivering_a_head_flips_that_head_and_appends_the_event(
    client, auth, world, notified_case, must_record
):
    family = _enumerate(client, auth, notified_case, NAME_A, user=world.collector, displaced=True)
    possession_on = _walk_to_possessed(must_record, notified_case)
    delivered_on = possession_on + timedelta(days=14)

    res = client.post(
        f"/api/v1/families/{family['id']}/entitlements/subsistence_allowance/deliver",
        json={"delivered_on": delivered_on.isoformat()},
        headers=auth(world.collector, delivered_on),
    )
    assert res.status_code == 200, res.text
    entitlements = res.json()["family"]["entitlements"]
    assert entitlements["subsistence_allowance"] == {
        "status": "delivered",
        "delivered_on": delivered_on.isoformat(),
        "evidence_document_id": None,
    }
    assert entitlements["house"]["status"] == "due", "only the named head may move"
    assert res.json()["family"]["heads_delivered"] == 1

    events = client.get(
        f"/api/v1/cases/{notified_case.id}/events",
        params={"type": "RR_ENTITLEMENT_DELIVERED"}, headers=auth(world.lao),
    ).json()["items"]
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["family_id"] == family["id"]
    assert payload["head"] == "subsistence_allowance"
    assert payload["evidence_doc"] is None

    # And it survives the read path.
    listed = _families(client, auth, notified_case, user=world.lao)["items"][0]
    assert listed["entitlements"]["subsistence_allowance"]["status"] == "delivered"
    assert listed["heads_delivered"] == 1


def test_an_unknown_head_is_rejected(client, auth, world, notified_case, must_record):
    family = _enumerate(client, auth, notified_case, NAME_A, user=world.collector)
    possession_on = _walk_to_possessed(must_record, notified_case)
    res = client.post(
        f"/api/v1/families/{family['id']}/entitlements/free_tractor/deliver",
        json={"delivered_on": possession_on.isoformat()},
        headers=auth(world.collector, possession_on),
    )
    assert res.status_code == 422, res.text
    assert res.json()["type"] == "validation_error"
    assert "Second/Third Schedule" in res.json()["detail"]


def test_delivery_before_possession_is_refused_by_the_rule_set(
    client, auth, world, notified_case
):
    """Both tracks put RR_ENTITLEMENT_DELIVERED on POSSESSED: s.38(1) measures the R&R
    clocks from the award, and possession follows payment."""
    family = _enumerate(client, auth, notified_case, NAME_A, user=world.collector)
    res = client.post(
        f"/api/v1/families/{family['id']}/entitlements/house/deliver",
        json={"delivered_on": "2025-03-01"},
        headers=auth(world.collector, "2025-03-01"),
    )
    assert res.status_code == 422, res.text
    assert res.json()["type"] == "transition_not_allowed"

    # Nothing was written: the head is still due and the ledger is untouched.
    listed = _families(client, auth, notified_case, user=world.lao)["items"][0]
    assert listed["entitlements"]["house"]["status"] == "due"
    assert client.get(
        f"/api/v1/cases/{notified_case.id}/events",
        params={"type": "RR_ENTITLEMENT_DELIVERED"}, headers=auth(world.lao),
    ).json()["total"] == 0


def test_an_out_of_scope_family_is_a_404_not_a_403(db, client, auth, world, notified_case):
    """Docs/APIs.md §1: out of jurisdiction is reported as 404, so the family-addressed
    route cannot be used to discover that a family exists somewhere else."""
    from app.models import OrgUnit

    family = _enumerate(client, auth, notified_case, NAME_A, user=world.collector)
    elsewhere = OrgUnit(kind="district", name=f"Elsewhere {uuid.uuid4().hex[:6]}")
    db.add(elsewhere)
    db.commit()
    outsider = _user(db, "COLLECTOR", elsewhere.id)

    res = client.post(
        f"/api/v1/families/{family['id']}/entitlements/house/deliver",
        json={"delivered_on": "2025-03-01"},
        headers=auth(outsider, "2025-03-01"),
    )
    assert res.status_code == 404, res.text
    listed = client.get(
        f"/api/v1/cases/{notified_case.id}/families", headers=auth(outsider)
    )
    assert listed.status_code == 404, listed.text


# --- summary -----------------------------------------------------------------------


def test_the_summary_counts_heads_by_status_and_carries_the_s38_clocks(
    client, auth, world, notified_case, must_record
):
    a = _enumerate(client, auth, notified_case, NAME_A, user=world.collector, displaced=True,
                   sc_st=True)
    _enumerate(client, auth, notified_case, NAME_B, user=world.collector, displaced=False)
    possession_on = _walk_to_possessed(must_record, notified_case)
    delivered_on = possession_on + timedelta(days=7)
    for head in ("house", "subsistence_allowance", "transportation_allowance"):
        assert client.post(
            f"/api/v1/families/{a['id']}/entitlements/{head}/deliver",
            json={"delivered_on": delivered_on.isoformat()},
            headers=auth(world.collector, delivered_on),
        ).status_code == 200

    body = client.get(
        f"/api/v1/cases/{notified_case.id}/rr/summary",
        headers=auth(world.lao, delivered_on),
    )
    assert body.status_code == 200, body.text
    summary = body.json()

    assert summary["families"] == {"total": 2, "displaced": 1, "sc_st": 1}
    assert len(summary["heads"]) == ALL_HEADS
    cells = 2 * ALL_HEADS
    assert summary["status_counts"] == {"due": cells - 3, "delivered": 3}
    assert summary["rr_progress_pct"] == round(100.0 * 3 / cells, 2)

    by_head = {h["head"]: h for h in summary["heads"]}
    assert by_head["house"]["counts"] == {"due": 1, "delivered": 1}
    assert by_head["land_for_land"]["counts"] == {"due": 2, "delivered": 0}
    # The schedule is data, and it refuses to quote a rupee figure.
    assert "verify current indexation" in by_head["house"]["amount"]
    assert by_head["resettlement_infrastructure"]["kind"] == "infra"

    # s.38(1) and its proviso, both started by the award. Neither closes on a partial
    # delivery: the obligation is per family and per head (see the R&R clock tests in
    # tests/test_stage3_fixes.py).
    clocks = {c["clock_id"]: c for c in summary["clocks"]}
    assert set(clocks) == {"RR_MONETARY_6M", "RR_INFRA_18M"}
    assert clocks["RR_MONETARY_6M"]["basis"] == "s.38(1)"
    assert clocks["RR_MONETARY_6M"]["status"] == "running"
    assert clocks["RR_INFRA_18M"]["status"] == "running"


def test_the_summary_reports_every_head_even_with_no_families(
    client, auth, world, notified_case
):
    summary = client.get(
        f"/api/v1/cases/{notified_case.id}/rr/summary", headers=auth(world.lao, "2025-03-01")
    ).json()
    assert summary["families"]["total"] == 0
    assert len(summary["heads"]) == ALL_HEADS
    assert summary["status_counts"] == {"due": 0, "delivered": 0}
    assert summary["rr_progress_pct"] == 0.0
    assert summary["clocks"] == []  # no award yet, so neither R&R clock has started


# --- the DPDP promise ---------------------------------------------------------------


def test_no_pii_ever_reaches_the_event_ledger(db, client, auth, world, notified_case,
                                              must_record):
    """`events` is hash-chained and append-only. A name written there could never be
    corrected or erased, so nothing about a family but its id and its flags goes in."""
    family = _enumerate(client, auth, notified_case, NAME_A, user=world.collector,
                        displaced=True, sc_st=True)
    possession_on = _walk_to_possessed(must_record, notified_case)
    delivered_on = possession_on + timedelta(days=3)
    assert client.post(
        f"/api/v1/families/{family['id']}/entitlements/house/deliver",
        json={"delivered_on": delivered_on.isoformat()},
        headers=auth(world.collector, delivered_on),
    ).status_code == 200

    db.rollback()
    ledger = "\n".join(
        row[0] for row in db.execute(text("SELECT payload::text FROM events")).all()
    )
    for secret in (NAME_A, NAME_B, VILLAGE, FULL_ID, FULL_ID.replace(" ", ""),
                   "Guardian Ansari", BANK_REF):
        assert secret not in ledger, f"{secret!r} leaked into events.payload"
    assert family["id"] in ledger  # the id is the only handle the ledger holds

    # And the name is not lying about in the clear in `persons_interested` either.
    rows = db.execute(
        text(
            "SELECT pii_enc, consent_flags->>'masked_ref' FROM persons_interested "
            "WHERE case_id = :case_id"
        ),
        {"case_id": str(notified_case.id)},
    ).all()
    assert rows
    assert all(NAME_A.encode() not in bytes(blob) for blob, _ in rows)
    # The reference stored in the clear beside the ciphertext is initials only.
    assert all(ref and NAME_A not in ref for _, ref in rows)


def test_a_family_found_after_possession_can_still_be_enumerated(
    client, auth, world, notified_case, must_record
):
    """s.38(1) runs R&R to 18 months past the award, so a family discovered late must
    still reach the ledger — both tracks list FAMILY_ENUMERATED at AWARDED and POSSESSED."""
    _walk_to_possessed(must_record, notified_case)
    res = client.post(
        f"/api/v1/cases/{notified_case.id}/families",
        json={"head": {"name": NAME_A}, "category": "landowner", "displaced": True,
              "sc_st": False, "occurred_at": "2025-09-01"},
        headers={**auth(world.collector, "2025-09-01"), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert res.status_code == 201, res.text
