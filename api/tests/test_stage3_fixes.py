"""The stage-3 adversarial findings, each reproduced before it was fixed.

Fourteen defects the second review found by execution, grouped as the review grouped
them. Each test states the untrue thing the system used to say, then the true one.

    overlay merge     a citation-only restatement deleting the s.38 payment gate
    overlay identity  an overlay overwriting the base every live case is pinned to
    PII key           `PII_KEY` unreachable, so every family name under a repo constant
    reversal          a withdrawn payment still shown paid on the lines and the export
    R&R clocks        one delivery to one family closing the six-month clock for all
    idempotency       a reused key answering 201 with somebody else's family
    un-reversal       a correction of a correction, accepted and doing nothing
    audit scope       /admin/audit enumerating the country to a district officer
    withdrawal        a reversed enumeration keeping its obligation and its PII
    decrypt           one bad ciphertext taking the whole register down with a 500
    role gates        the family register and the exports with no RBAC at all
    snapshot          `as_of_seq` read before the rows it is supposed to anchor
    scope             an empty scope claim reading as national jurisdiction
"""

from __future__ import annotations

import logging
import shutil
import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app.domain.rr.schedules import SECOND_SCHEDULE
from tests.conftest import World
from tests.helpers import S11_DEFAULT, walk_to_awarded, walk_to_notified

MONETARY_KINDS = ("monetary", "land", "employment")


# --- helpers -----------------------------------------------------------------------


def _user(db, role: str, org_unit_id):
    user = World._user(db, f"{role.lower()}-{uuid.uuid4().hex[:8]}@test", role, org_unit_id)
    db.commit()
    return user


def _applicable_heads(kinds, *, displaced: bool, irrigation: bool = False) -> list[str]:
    """What the Schedule actually owes this family — derived from the data, not typed
    out, so a schedule edit moves the test with it."""
    out = []
    for head in SECOND_SCHEDULE:
        if head["kind"] not in kinds:
            continue
        applies_to = head["applies_to"]
        if applies_to == "displaced" and not displaced:
            continue
        if applies_to == "irrigation" and not irrigation:
            continue
        out.append(head["head"])
    return out


def _enumerate(client, auth, case, name, user, *, on: date, displaced: bool = False,
               sc_st: bool = False, category: str = "agricultural landowner") -> dict:
    res = client.post(
        f"/api/v1/cases/{case.id}/families",
        json={
            "head": {"name": name, "guardian": f"Guardian {name.split()[-1]}",
                     "village": "Bakhari Buzurg"},
            "category": category,
            "displaced": displaced,
            "sc_st": sc_st,
            "occurred_at": on.isoformat(),
        },
        headers={**auth(user, on), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _deliver(client, auth, user, family_id: str, head: str, on: date) -> None:
    res = client.post(
        f"/api/v1/families/{family_id}/entitlements/{head}/deliver",
        json={"delivered_on": on.isoformat()},
        headers=auth(user, on),
    )
    assert res.status_code == 200, res.text


def _rr_clocks(client, auth, user, case, on: date) -> dict[str, dict]:
    res = client.get(
        f"/api/v1/cases/{case.id}/rr/summary", headers=auth(user, on)
    )
    assert res.status_code == 200, res.text
    return {c["clock_id"]: c for c in res.json()["clocks"]}


@pytest.fixture()
def ruleset_tree(tmp_path):
    """A throwaway copy of `api/rulesets` a test can drop an overlay into.

    The registry is process-global, so the real rule-sets are reloaded on the way out —
    otherwise one overlay test would decide what every later test's cases are judged by.
    """
    from app.core.config import settings
    from app.domain.rules.loader import load_all_rulesets, rulesets_dir

    source = rulesets_dir()
    target = tmp_path / "rulesets"
    shutil.copytree(source, target)
    original = settings.RULESETS_DIR
    settings.RULESETS_DIR = str(target)
    try:
        yield target
    finally:
        settings.RULESETS_DIR = original
        load_all_rulesets()


def _loader_log(caplog, level: int) -> str:
    """Everything the loader said at `level` or above, formatted."""
    return "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "app.domain.rules.loader" and record.levelno >= level
    )


def _overlay(tree, filename: str, body: str) -> None:
    (tree / "overlays" / filename).write_text(body, encoding="utf-8")


def _pinned_case(db, world, version: str, track: str = "RFCTLARR_2013"):
    """A case filed under a specific rule-set version — an overlay, usually."""
    from app.domain.cases.projections import ensure_case_state
    from app.models import Case

    project = world.project(db, track)
    project.ruleset_version = version
    db.flush()
    case = Case(
        project_id=project.id,
        district_id=world.district.id,
        case_no=f"OV/{uuid.uuid4().hex[:6]}",
        statute_track=track,
        ruleset_version=version,
    )
    db.add(case)
    db.flush()
    ensure_case_state(db, case)
    db.commit()
    return case


CITATION_ONLY_OVERLAY = """
track: RFCTLARR_2013
version: "2026.09-XX"
overlay: true
base_version: "2026.09"
title: "State X Amendment 2021 — citations only"
transitions:
  DECLARATION_S19:
    from: NOTIFIED
    to: DECLARED
    section: "s.19 read with State X Amendment 2021"
  POSSESSION_TAKEN_S38:
    from: AWARDED
    to: POSSESSED
    section: "s.38 read with State X Amendment 2021"
"""


# --- 1. overlay merge is field-level ------------------------------------------------


def test_a_citation_only_overlay_keeps_the_gate_and_the_preconditions(ruleset_tree):
    """`eff.update(overlay['transitions'])` replaced the whole stanza, so an overlay
    restating a transition to change its `section:` deleted that transition's
    `requires:` and `guard:` — the s.38 possession-payment gate included."""
    from app.domain.rules.loader import get_ruleset, load_all_rulesets

    _overlay(ruleset_tree, "state_x.yaml", CITATION_ONLY_OVERLAY)
    load_all_rulesets()

    rs = get_ruleset("RFCTLARR_2013", "2026.09-XX")
    assert rs is not None
    possession = rs.transitions["POSSESSION_TAKEN_S38"]
    assert possession.guard == "possession_payment_gate"
    assert possession.section == "s.38 read with State X Amendment 2021"
    declaration = rs.transitions["DECLARATION_S19"]
    assert declaration.requires == ["RR_SCHEME_PUBLISHED_S18", "COST_DEPOSITED_S19_2"]
    assert declaration.section == "s.19 read with State X Amendment 2021"
    # Everything the overlay never mentioned is still there.
    assert rs.transitions["AWARD_S23"].to_stage == "AWARDED"


def test_a_case_under_a_citation_only_overlay_still_cannot_take_possession_unpaid(
    db, world, client, auth, must_record, record, ruleset_tree
):
    """The end of the same story, run through the API: PROPOSED -> POSSESSED with
    nothing assessed and nothing paid, under an overlay that only changed a citation."""
    from app.domain.rules.loader import load_all_rulesets

    _overlay(ruleset_tree, "state_x.yaml", CITATION_ONLY_OVERLAY)
    load_all_rulesets()

    case = _pinned_case(db, world, "2026.09-XX")
    award_on, _ = walk_to_awarded(must_record, case)

    status, body = record(case, "POSSESSION_TAKEN_S38", award_on + timedelta(days=5), {})
    assert status == 422, body
    assert body["type"] == "guard_failed"

    # And the s.18/s.19(2) preconditions still bite on a case that has not met them.
    other = _pinned_case(db, world, "2026.09-XX")
    walk_to_notified(must_record, other)
    status, body = record(
        other, "DECLARATION_S19", S11_DEFAULT + timedelta(days=30), {"gazette_no": "X"}
    )
    assert status == 422, body
    assert body["type"] == "precondition_failed"


def test_an_overlay_that_removes_a_guard_explicitly_is_honoured_and_logged(
    ruleset_tree, caplog
):
    """Removing a gate is a legitimate thing for a State amendment to do — but only by
    saying so. `guard: null` wins; the loader warns, because that is the direction that
    opens a statutory gate."""
    from app.domain.rules.loader import get_ruleset, load_all_rulesets

    _overlay(ruleset_tree, "state_y.yaml", """
track: RFCTLARR_2013
version: "2026.09-YY"
overlay: true
base_version: "2026.09"
transitions:
  POSSESSION_TAKEN_S38:
    from: AWARDED
    to: POSSESSED
    guard: null
  DECLARATION_S19:
    from: NOTIFIED
    to: DECLARED
    requires: []
""")
    with caplog.at_level(logging.WARNING, logger="app.domain.rules.loader"):
        load_all_rulesets()

    rs = get_ruleset("RFCTLARR_2013", "2026.09-YY")
    assert rs.transitions["POSSESSION_TAKEN_S38"].guard is None
    assert rs.transitions["DECLARATION_S19"].requires == []
    warnings = _loader_log(caplog, logging.WARNING)
    assert "POSSESSION_TAKEN_S38" in warnings and "guard" in warnings
    assert "DECLARATION_S19" in warnings and "requires" in warnings


def test_an_overlay_that_drops_event_types_from_a_stage_names_every_one_of_them(
    ruleset_tree, caplog
):
    """A stage that quietly loses PRELIM_NOTIFICATION_S11 and EVENT_REVERSED strands
    every case sitting in it with no way forward and no way to correct the record; the
    admin diff renders the loss as an absent line, not a removal."""
    from app.domain.rules.loader import get_ruleset, load_all_rulesets

    _overlay(ruleset_tree, "state_z.yaml", """
track: RFCTLARR_2013
version: "2026.09-ZZ"
overlay: true
base_version: "2026.09"
stages:
  APPRAISED: { on: [COURT_STAY] }
""")
    with caplog.at_level(logging.WARNING, logger="app.domain.rules.loader"):
        load_all_rulesets()

    rs = get_ruleset("RFCTLARR_2013", "2026.09-ZZ")
    assert rs.stages["APPRAISED"] == ["COURT_STAY"]
    warnings = _loader_log(caplog, logging.WARNING)
    for lost in ("PRELIM_NOTIFICATION_S11", "EVENT_REVERSED"):
        assert lost in warnings, f"{lost} disappeared from APPRAISED without a word"


# --- 2. rule-set identity -----------------------------------------------------------


def test_an_overlay_may_not_take_its_own_base_version(ruleset_tree, caplog):
    """Registering it replaced the base under the base's own key: `get_ruleset(track)`
    returned None (no base candidate left), so no new project on the track could be
    created, and every live case pinned to 2026.09 started being judged against the
    overlay instead."""
    from app.domain.rules.loader import get_ruleset, load_all_rulesets

    _overlay(ruleset_tree, "collide.yaml", """
track: RFCTLARR_2013
version: "2026.09"
overlay: true
base_version: "2026.09"
stages:
  AWARDED: { on: [EVENT_REVERSED] }
""")
    with caplog.at_level(logging.ERROR, logger="app.domain.rules.loader"):
        load_all_rulesets()

    base = get_ruleset("RFCTLARR_2013", "2026.09")
    assert base is not None and base.base_version is None
    assert "PAYMENT_MADE" in base.stages["AWARDED"]
    assert get_ruleset("RFCTLARR_2013") is base  # the track still has a default
    errors = _loader_log(caplog, logging.ERROR)
    assert "collide.yaml" in errors


def test_two_files_claiming_one_version_keep_the_first_and_name_both(
    ruleset_tree, caplog
):
    """The winner used to be decided by filename sort order: copying an overlay to a new
    filename without bumping its version silently changed the rule-set the estate ran
    on, and the loser was logged at INFO as 'loaded'."""
    from app.domain.rules.loader import get_ruleset, load_all_rulesets

    for name, title in (("aaa_dup.yaml", "AAA"), ("zzz_dup.yaml", "ZZZ")):
        _overlay(ruleset_tree, name, f"""
track: RFCTLARR_2013
version: "2026.09-DUP"
overlay: true
base_version: "2026.09"
title: "{title}"
""")
    with caplog.at_level(logging.ERROR, logger="app.domain.rules.loader"):
        load_all_rulesets()

    rs = get_ruleset("RFCTLARR_2013", "2026.09-DUP")
    assert rs.overlay_title == "AAA", "the first document must keep the version"
    errors = _loader_log(caplog, logging.ERROR)
    assert "aaa_dup.yaml" in errors and "zzz_dup.yaml" in errors


def test_two_spellings_of_one_version_order_deterministically():
    """`version_sort_key('2026.9') == version_sort_key('2026.09')` made 'newest' a coin
    toss decided by dict iteration order — on the code path that picks the rule-set a
    new project is filed under."""
    from app.domain.rules.loader import version_sort_key

    assert version_sort_key("2026.9") != version_sort_key("2026.09")
    assert version_sort_key("2026.09") < version_sort_key("2026.9")
    assert version_sort_key("2026.9") < version_sort_key("2026.10")
    assert version_sort_key("2026.10") < version_sort_key("2027.1")
    assert sorted(["2026.9", "2026.09"], key=version_sort_key) == ["2026.09", "2026.9"]
    assert sorted(["2026.09", "2026.9"], key=version_sort_key) == ["2026.09", "2026.9"]


# --- 3. the PII key -----------------------------------------------------------------


def test_the_pii_key_is_read_from_settings(monkeypatch):
    """`os.environ.get('PII_KEY')` never saw a key configured in `.env`, because
    pydantic-settings loads `.env` into the settings object and never exports it — so
    every family's name was encrypted under the constant published in crypto.py."""
    from app.core import crypto
    from app.core.config import settings

    monkeypatch.setattr(settings, "PII_KEY", "ab" * 32)
    blob = crypto.encrypt_pii({"name": "Configured Key"})
    assert crypto.decrypt_pii(blob) == {"name": "Configured Key"}

    monkeypatch.setattr(settings, "PII_KEY", "")
    with pytest.raises(Exception):
        crypto.decrypt_pii(blob)  # the dev constant must not open it


def test_a_production_deployment_without_a_key_refuses_to_run(monkeypatch):
    from app.core import crypto
    from app.core.config import settings

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    for value in ("", "6b" * 32):
        monkeypatch.setattr(settings, "PII_KEY", value)
        with pytest.raises(RuntimeError):
            crypto.assert_key_configured()
        with pytest.raises(RuntimeError):
            crypto.encrypt_pii({"name": "X"})

    monkeypatch.setattr(settings, "PII_KEY", "not-hex")
    with pytest.raises(RuntimeError):
        crypto.assert_key_configured()

    monkeypatch.setattr(settings, "PII_KEY", "cd" * 32)
    crypto.assert_key_configured()  # a real key: no complaint


# --- 4. reversing a payment ---------------------------------------------------------


def _assess_and_pay(client, auth, world, case, award_on: date) -> tuple[int, dict]:
    """Assess one award line and pay it in full, through the API."""
    assessed = client.post(
        f"/api/v1/cases/{case.id}/compensation/assess",
        json={"lines": [{"owner_ref": "OWN-001", "market_value_paise": 50_00_000,
                         "factor": 1.0, "assets_paise": 0,
                         "mv_method": "s.26(1)(b)"}]},
        headers={**auth(world.collector, award_on), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert assessed.status_code == 200, assessed.text
    total = assessed.json()["assessed_total_paise"]

    paid = client.post(
        f"/api/v1/cases/{case.id}/payments",
        json={"pfms_ref": "PFMS/2026/1", "amount_paise": total,
              "occurred_at": (award_on + timedelta(days=10)).isoformat()},
        headers={**auth(world.collector, award_on + timedelta(days=10)),
                 "Idempotency-Key": str(uuid.uuid4())},
    )
    assert paid.status_code == 201, paid.text
    return total, paid.json()


def test_reversing_a_payment_puts_the_money_back_on_the_award_lines(
    db, world, client, auth, must_record, record
):
    """`_apply_reversal` decremented `case_state.comp_paid_paise` and stopped there, so
    `compensation_lines.paid_paise` kept the money: the compensation screen reported
    `outstanding 0` and `possession_gate_open true` on an award the bank had returned,
    while the s.38 gate on the same case refused possession for non-payment."""
    from app.models import CompensationLine

    case = world.case(db)
    award_on, _ = walk_to_awarded(must_record, case, assessed_paise=1)
    total, _ = _assess_and_pay(client, auth, world, case, award_on)

    before = client.get(
        f"/api/v1/cases/{case.id}/compensation", headers=auth(world.lao, award_on)
    ).json()
    assert before["possession_gate_open"] is True
    assert before["outstanding_paise"] == 0

    payment_id = before["payments"][-1]["event_id"]
    reversed_on = award_on + timedelta(days=12)
    status, body = record(
        case, "EVENT_REVERSED", reversed_on,
        {"reversed_event_id": payment_id, "reason": "PFMS returned the transfer"},
        user=world.collector,
    )
    assert status == 201, body

    after = client.get(
        f"/api/v1/cases/{case.id}/compensation", headers=auth(world.lao, reversed_on)
    ).json()
    assert after["paid_total_paise"] == 0
    assert after["outstanding_paise"] == after["assessed_total_paise"] == total
    assert after["possession_gate_open"] is False

    db.expire_all()
    lines = db.scalars(
        select(CompensationLine).where(CompensationLine.case_id == case.id)
    ).all()
    assert [int(line.paid_paise or 0) for line in lines] == [0]

    # The COMPENSATION_PAID_FULL the payment bought is withdrawn as the SYSTEM actor,
    # so the s.38(1) three-month clock is running again.
    clocks = client.get(
        f"/api/v1/cases/{case.id}/clocks", headers=auth(world.lao, reversed_on)
    ).json()["items"]
    comp = next(c for c in clocks if c["clock_id"] == "COMPENSATION_3M")
    assert comp["status"] == "running", comp
    events = client.get(
        f"/api/v1/cases/{case.id}/events", params={"limit": 100},
        headers=auth(world.lao),
    ).json()["items"]
    unwind = [
        e for e in events
        if e["type"] == "EVENT_REVERSED"
        and (e["payload"] or {}).get("reason") == "payment withdrawn"
    ]
    assert len(unwind) == 1, events


def test_the_compensation_register_export_shows_a_withdrawn_payment_as_unpaid(
    db, world, client, auth, must_record, record
):
    """The export is hashed and the hash certifies the bytes: an unpaid award exported
    as `paid=total, outstanding=0` is a certified false statement."""
    case = world.case(db, case_no=f"REV/{uuid.uuid4().hex[:6]}")
    award_on, _ = walk_to_awarded(must_record, case, assessed_paise=1)
    total, _ = _assess_and_pay(client, auth, world, case, award_on)

    payment_id = client.get(
        f"/api/v1/cases/{case.id}/compensation", headers=auth(world.lao, award_on)
    ).json()["payments"][-1]["event_id"]
    reversed_on = award_on + timedelta(days=12)
    status, body = record(
        case, "EVENT_REVERSED", reversed_on,
        {"reversed_event_id": payment_id, "reason": "PFMS returned the transfer"},
        user=world.collector,
    )
    assert status == 201, body

    headers = auth(world.lao, reversed_on)
    job = client.post(
        "/api/v1/reports", json={"template": "compensation_register"}, headers=headers
    )
    assert job.status_code == 202, job.text
    payload = client.get(
        f"/api/v1/reports/{job.json()['job_id']}", headers=headers
    ).json()
    csv_text = httpx.get(payload["url"], timeout=20).text
    row = next(line for line in csv_text.splitlines() if case.case_no in line)
    assert row.endswith(f",{total},0,{total}"), row


def test_a_case_can_be_re_assessed_once_its_payment_is_withdrawn(
    db, world, client, auth, must_record, record
):
    """`assess()` refuses while any line shows money against it, which was permanent:
    the lines were never put back, so a case whose payment had been reversed could not
    be corrected forward either."""
    case = world.case(db)
    award_on, _ = walk_to_awarded(must_record, case, assessed_paise=1)
    total, _ = _assess_and_pay(client, auth, world, case, award_on)

    payment_id = client.get(
        f"/api/v1/cases/{case.id}/compensation", headers=auth(world.lao, award_on)
    ).json()["payments"][-1]["event_id"]
    reversed_on = award_on + timedelta(days=12)
    assert record(
        case, "EVENT_REVERSED", reversed_on,
        {"reversed_event_id": payment_id, "reason": "PFMS returned the transfer"},
        user=world.collector,
    )[0] == 201

    again = client.post(
        f"/api/v1/cases/{case.id}/compensation/assess",
        json={"lines": [{"owner_ref": "OWN-001", "market_value_paise": 60_00_000,
                         "factor": 1.0, "assets_paise": 0}]},
        headers={**auth(world.collector, reversed_on),
                 "Idempotency-Key": str(uuid.uuid4())},
    )
    assert again.status_code == 200, again.text
    assert again.json()["assessed_total_paise"] != total
    assert again.json()["paid_total_paise"] == 0


def test_the_chain_and_the_replay_survive_the_system_unwind(
    db, world, client, auth, must_record, record
):
    """Withdrawing a payment now appends a *second* event — the SYSTEM reversal of
    COMPENSATION_PAID_FULL — from inside the first append's projection. That is the
    risky part of the fix, so this asks the two questions it could break: does the hash
    chain still verify, and does a full replay land on the same figures the incremental
    fold did (Docs/rules.md C1, Docs/Backend.md §8)?"""
    case = world.case(db)
    award_on, _ = walk_to_awarded(must_record, case, assessed_paise=1)
    _assess_and_pay(client, auth, world, case, award_on)

    payment_id = client.get(
        f"/api/v1/cases/{case.id}/compensation", headers=auth(world.lao, award_on)
    ).json()["payments"][-1]["event_id"]
    reversed_on = award_on + timedelta(days=12)
    assert record(
        case, "EVENT_REVERSED", reversed_on,
        {"reversed_event_id": payment_id, "reason": "PFMS returned the transfer"},
        user=world.collector,
    )[0] == 201

    integrity = client.get(
        f"/api/v1/cases/{case.id}/integrity", headers=auth(world.lao)
    ).json()
    assert integrity["verified"] is True, integrity

    before = client.get(
        f"/api/v1/cases/{case.id}", headers=auth(world.lao, reversed_on)
    ).json()["case_state"]
    rebuilt = client.post(
        f"/api/v1/cases/{case.id}/rebuild", headers=auth(world.collector, reversed_on)
    )
    assert rebuilt.status_code == 200, rebuilt.text
    after = rebuilt.json()["case_state"]
    for key in ("stage", "comp_assessed_paise", "comp_paid_paise", "as_of_seq",
                "families_affected", "possession_pct"):
        assert before[key] == after[key], key


# --- 5. per-family R&R clocks -------------------------------------------------------


def test_one_delivery_to_one_family_does_not_close_the_six_month_clock(
    db, world, client, auth, must_record
):
    """`ends_on: RR_ENTITLEMENT_DELIVERED` closed RR_MONETARY_6M on the first delivery
    anywhere on the case: the clock reported statutory compliance beside a delivery rate
    in the single digits, with no breach, no amber and no escalation."""
    case = world.case(db)
    award_on, _ = walk_to_awarded(must_record, case)
    a = _enumerate(client, auth, case, "Zubeida Khatoon Ansari", world.collector,
                   on=award_on + timedelta(days=1), displaced=True)
    _enumerate(client, auth, case, "Harphool Singh Rathore", world.collector,
               on=award_on + timedelta(days=1))

    _deliver(client, auth, world.collector, a["id"], "subsistence_allowance",
             award_on + timedelta(days=30))

    clocks = _rr_clocks(client, auth, world.lao, case, award_on + timedelta(days=40))
    assert clocks["RR_MONETARY_6M"]["status"] == "running"
    assert clocks["RR_INFRA_18M"]["status"] == "running"


def test_delivering_every_applicable_head_to_every_family_closes_the_clocks(
    db, world, client, auth, must_record
):
    """And the mirror image: RR_INFRA_18M carried no `ends_on` at all, so nothing could
    close it — a case with every head delivered still sat `breached` under an alert no
    action could clear."""
    case = world.case(db)
    award_on, _ = walk_to_awarded(must_record, case)
    enumerated_on = award_on + timedelta(days=1)
    displaced = _enumerate(client, auth, case, "Zubeida Khatoon Ansari", world.collector,
                           on=enumerated_on, displaced=True)
    resident = _enumerate(client, auth, case, "Harphool Singh Rathore", world.collector,
                          on=enumerated_on)

    monetary_on = award_on + timedelta(days=30)
    for family, is_displaced in ((displaced, True), (resident, False)):
        for head in _applicable_heads(MONETARY_KINDS, displaced=is_displaced):
            _deliver(client, auth, world.collector, family["id"], head, monetary_on)

    # `land_for_land` is confined to irrigation projects and this one is not, so it is
    # still due — and the clock is closed anyway.
    clocks = _rr_clocks(client, auth, world.lao, case, monetary_on + timedelta(days=5))
    assert clocks["RR_MONETARY_6M"]["status"] == "closed"
    assert clocks["RR_MONETARY_6M"]["closed_on"] == monetary_on.isoformat()
    assert clocks["RR_INFRA_18M"]["status"] == "running"

    infra_on = award_on + timedelta(days=200)
    for family in (displaced, resident):
        _deliver(client, auth, world.collector, family["id"],
                 "resettlement_infrastructure", infra_on)
    clocks = _rr_clocks(client, auth, world.lao, case, infra_on + timedelta(days=5))
    assert clocks["RR_INFRA_18M"]["status"] == "closed"
    assert clocks["RR_INFRA_18M"]["closed_on"] == infra_on.isoformat()

    summary = client.get(
        f"/api/v1/cases/{case.id}/rr/summary",
        headers=auth(world.lao, infra_on + timedelta(days=5)),
    ).json()
    assert summary["families"]["total"] == 2
    assert {c["clock_id"]: c["status"] for c in summary["clocks"]} == {
        "RR_MONETARY_6M": "closed", "RR_INFRA_18M": "closed",
    }


def test_completing_the_obligation_late_does_not_erase_the_breach(
    db, world, client, auth, must_record
):
    """The in-time rule applies to a predicate closer exactly as it does to `ends_on`:
    R&R delivered eight months after the award discharges the obligation but does not
    make the six months have been kept, and treating it as a closure would make late
    recording the way to erase a statutory consequence."""
    case = world.case(db)
    award_on, _ = walk_to_awarded(must_record, case)
    enumerated_on = award_on + timedelta(days=1)
    family = _enumerate(client, auth, case, "Zubeida Khatoon Ansari", world.collector,
                        on=enumerated_on, displaced=True)

    late = award_on + timedelta(days=240)  # six months due; this is eight
    for head in _applicable_heads(MONETARY_KINDS, displaced=True):
        _deliver(client, auth, world.collector, family["id"], head, late)

    clocks = _rr_clocks(client, auth, world.lao, case, late + timedelta(days=5))
    assert clocks["RR_MONETARY_6M"]["status"] == "breached"
    assert clocks["RR_MONETARY_6M"]["closed_on"] is None


def test_a_case_with_no_families_keeps_the_rr_clocks_running(
    db, world, client, auth, must_record
):
    """An undetermined obligation is not a discharged one: closing the clock on a case
    whose census has not been taken would report compliance on the one case that has
    not started."""
    case = world.case(db)
    award_on, _ = walk_to_awarded(must_record, case)
    clocks = _rr_clocks(client, auth, world.lao, case, award_on + timedelta(days=30))
    assert clocks["RR_MONETARY_6M"]["status"] == "running"
    assert clocks["RR_INFRA_18M"]["status"] == "running"


# --- 6. enumeration idempotency -----------------------------------------------------


def test_a_reused_key_with_a_different_family_is_refused(
    db, world, client, auth, must_record
):
    """A reused key answered 201 with the *first* family: the second household was never
    enumerated, never reached the ledger and never entered the case's R&R obligation —
    a silent statutory drop reported to the officer as a success."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    key = "officer-retry-key-1"
    on = date(2025, 2, 3)

    first = client.post(
        f"/api/v1/cases/{case.id}/families",
        json={"head": {"name": "Ram Kumar Yadav"}, "displaced": True,
              "occurred_at": on.isoformat()},
        headers={**auth(world.collector, on), "Idempotency-Key": key},
    )
    assert first.status_code == 201, first.text

    second = client.post(
        f"/api/v1/cases/{case.id}/families",
        json={"head": {"name": "Sita Devi Patil"}, "sc_st": True,
              "occurred_at": on.isoformat()},
        headers={**auth(world.collector, on), "Idempotency-Key": key},
    )
    assert second.status_code == 422, second.text
    assert second.json()["type"] == "validation_error"

    # The honest retry — same key, same body — still replays.
    replay = client.post(
        f"/api/v1/cases/{case.id}/families",
        json={"head": {"name": "Ram Kumar Yadav"}, "displaced": True,
              "occurred_at": on.isoformat()},
        headers={**auth(world.collector, on), "Idempotency-Key": key},
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["duplicate"] is True
    assert replay.json()["id"] == first.json()["id"]


# --- 7. un-reversal -----------------------------------------------------------------


def test_a_reversal_of_a_reversal_is_refused(db, world, client, auth, must_record, record):
    """It used to be accepted and do nothing: `_apply_reversal` has no branch for it and
    `rebuild_case` drops the inner marker as withdrawn, so the ledger permanently
    recorded a correction that corrected nothing."""
    case = world.case(db)
    award_on, assessed = walk_to_awarded(must_record, case)
    payment = must_record(
        case, "PAYMENT_MADE", award_on + timedelta(days=10),
        {"pfms_ref": "PFMS/1", "amount_paise": assessed, "mode": "PFMS"},
    )
    status, reversal = record(
        case, "EVENT_REVERSED", award_on + timedelta(days=12),
        {"reversed_event_id": payment["id"], "reason": "recorded in error"},
        user=world.collector,
    )
    assert status == 201, reversal

    status, body = record(
        case, "EVENT_REVERSED", award_on + timedelta(days=13),
        {"reversed_event_id": reversal["id"], "reason": "the reversal was the mistake"},
        user=world.collector,
    )
    assert status == 422, body
    assert body["type"] == "validation_error"
    assert "un-reversal is not supported" in body["detail"]


# --- 8. audit scope -----------------------------------------------------------------


def test_an_out_of_district_officer_sees_no_pii_reads_from_another_district(
    db, world, client, auth, must_record
):
    """`GET /admin/audit` had no jurisdiction filter while AUDIT_ROLES admits COLLECTOR,
    so it enumerated the case numbers, case ids and family ids of cases the same caller
    is 404'd from — and disclosed which officer read which family, and why."""
    from app.models import OrgUnit

    case = world.case(db)
    walk_to_notified(must_record, case)
    family = _enumerate(client, auth, case, "Zubeida Khatoon Ansari", world.collector,
                        on=date(2025, 2, 3))
    seen = client.get(
        f"/api/v1/cases/{case.id}/families",
        params={"purpose": "grievance hearing 15 Mar"},
        headers=auth(world.collector),
    )
    assert seen.status_code == 200 and seen.json()["pii"] == "unlocked"

    elsewhere = OrgUnit(kind="district", name=f"Elsewhere {uuid.uuid4().hex[:6]}")
    db.add(elsewhere)
    db.commit()
    outsider = _user(db, "COLLECTOR", elsewhere.id)

    assert client.get(
        f"/api/v1/cases/{case.id}/families", headers=auth(outsider)
    ).status_code == 404

    audit = client.get(
        "/api/v1/admin/audit", params={"action": "PII_READ", "limit": 1000},
        headers=auth(outsider),
    )
    assert audit.status_code == 200, audit.text
    rows = audit.json()["items"]
    assert rows == [] or all(
        (r["meta"] or {}).get("case_id") != str(case.id) for r in rows
    )
    assert all(r["target"] != family["id"] for r in rows)

    # The officer with jurisdiction still sees their own case's reads.
    mine = client.get(
        "/api/v1/admin/audit", params={"action": "PII_READ", "limit": 1000},
        headers=auth(world.collector),
    ).json()["items"]
    assert any(r["target"] == family["id"] for r in mine)


# --- 9. reversing an enumeration ----------------------------------------------------


def test_reversing_an_enumeration_withdraws_the_family_and_erases_its_pii(
    db, world, client, auth, must_record, record
):
    """The reversal moved the KPI and left everything else: the R&R register still
    listed the family, still owed it ten Schedule heads, and still held its encrypted
    name — the one record DPDP says to stop processing."""
    from app.models import AffectedFamily, CaseState, PersonInterested

    case = world.case(db)
    walk_to_notified(must_record, case)
    on = date(2025, 2, 3)
    family = _enumerate(client, auth, case, "Zubeida Khatoon Ansari", world.collector,
                        on=on, displaced=True)

    enumerated = client.get(
        f"/api/v1/cases/{case.id}/events", params={"type": "FAMILY_ENUMERATED"},
        headers=auth(world.lao),
    ).json()["items"][0]
    status, body = record(
        case, "EVENT_REVERSED", on + timedelta(days=1),
        {"reversed_event_id": enumerated["id"], "reason": "enumerated on the wrong case"},
        user=world.collector,
    )
    assert status == 201, body

    db.expire_all()
    row = db.get(AffectedFamily, uuid.UUID(family["id"]))
    assert row.withdrawn_at is not None
    person = db.get(PersonInterested, row.head_person_id)
    assert bytes(person.pii_enc) == b""
    assert person.consent_flags["masked_ref"] == "Family ZKA"  # the ref survives

    listed = client.get(
        f"/api/v1/cases/{case.id}/families", headers=auth(world.lao)
    ).json()
    assert listed["total"] == 0 and listed["items"] == []
    summary = client.get(
        f"/api/v1/cases/{case.id}/rr/summary", headers=auth(world.lao, on)
    ).json()
    assert summary["families"] == {"total": 0, "displaced": 0, "sc_st": 0}
    assert summary["status_counts"] == {"due": 0, "delivered": 0}
    assert int(db.get(CaseState, case.id).families_affected) == 0

    from app.domain.dashboards import service as dash

    assert dash.kpis(db, [case.id], on)["families_affected"] == 0


# --- 10. one bad ciphertext ---------------------------------------------------------


def test_one_undecryptable_row_does_not_take_the_register_down(
    db, world, client, auth, must_record
):
    """`decrypt_pii` in the unlocked branch had no error handling: one bad row (a stale
    restore, a half-finished re-key) raised InvalidTag out of the endpoint as a bare
    500, denied the names of every other family on the case, and wrote no audit trail
    at all — at the moment an officer needed a name."""
    from app.models import AffectedFamily

    case = world.case(db)
    walk_to_notified(must_record, case)
    on = date(2025, 2, 3)
    broken = _enumerate(client, auth, case, "Zubeida Khatoon Ansari", world.collector, on=on)
    intact = _enumerate(client, auth, case, "Harphool Singh Rathore", world.collector, on=on)

    db.expire_all()
    head_id = db.get(AffectedFamily, uuid.UUID(broken["id"])).head_person_id
    db.execute(
        text(
            "UPDATE persons_interested SET pii_enc = "
            "set_byte(pii_enc, 5, (get_byte(pii_enc, 5) + 1) % 256) WHERE id = :id"
        ),
        {"id": str(head_id)},
    )
    db.commit()

    res = client.get(
        f"/api/v1/cases/{case.id}/families",
        params={"purpose": "grievance hearing 15 Mar"},
        headers=auth(world.collector),
    )
    assert res.status_code == 200, res.text
    rows = {r["id"]: r for r in res.json()["items"]}
    assert rows[broken["id"]]["pii_error"] == "undecryptable"
    assert "head" not in rows[broken["id"]]
    assert rows[broken["id"]]["ref"] == "Family ZKA"  # the clear masked ref still reads
    assert rows[intact["id"]]["head"]["name"] == "Harphool Singh Rathore"

    audited = client.get(
        "/api/v1/admin/audit", params={"action": "PII_READ", "limit": 1000},
        headers=auth(world.collector),
    ).json()["items"]
    targets = [r["target"] for r in audited]
    assert intact["id"] in targets
    assert broken["id"] not in targets, "a read that disclosed nothing was audited"


# --- 11. role gates -----------------------------------------------------------------


def test_the_family_register_follows_the_rbac_matrix(
    db, world, client, auth, must_record
):
    """Docs/APIs.md §2 'R&R families (PII)': RB '—', Ministry 'aggregate', Auditor
    'masked'. The endpoint carried no role gate at all, so a requiring body read the
    register of the families its own project displaces."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    _enumerate(client, auth, case, "Zubeida Khatoon Ansari", world.collector,
               on=date(2025, 2, 3), sc_st=True)

    rb = _user(db, "RB", world.body.id)
    auditor = _user(db, "AUDITOR", None)

    for who in (rb, world.ministry_user):
        res = client.get(f"/api/v1/cases/{case.id}/families", headers=auth(who))
        assert res.status_code == 404, f"{who.name}: {res.text}"

    res = client.get(f"/api/v1/cases/{case.id}/families", headers=auth(auditor))
    assert res.status_code == 200, res.text
    row = res.json()["items"][0]
    assert res.json()["pii"] == "masked"
    assert "sc_st" not in row, "caste is sensitive personal data (DPDP)"
    assert row["displaced"] is False


def test_the_exports_follow_the_rbac_matrix(db, world, client, auth, must_record):
    """`POST /reports` resolved scope and nothing else, so an RB user exported the whole
    compensation register — award lines with their free-text `owner_ref` — from a row
    the matrix marks '—'."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    rb = _user(db, "RB", world.body.id)

    for template in ("compensation_register", "cases_register"):
        denied = client.post(
            "/api/v1/reports", json={"template": template}, headers=auth(rb)
        )
        assert denied.status_code == 404, f"{template}: {denied.text}"

    allowed = client.post(
        "/api/v1/reports", json={"template": "national_kpis"}, headers=auth(rb)
    )
    assert allowed.status_code == 202, allowed.text

    for template in ("compensation_register", "cases_register", "national_kpis"):
        res = client.post(
            "/api/v1/reports", json={"template": template}, headers=auth(world.lao)
        )
        assert res.status_code == 202, f"{template}: {res.text}"


# --- 12. one snapshot per report ----------------------------------------------------


def test_a_report_reads_its_rows_on_the_snapshot_its_as_of_seq_names(
    db, world, client, auth, must_record, monkeypatch
):
    """`as_of_seq` was read before the rows under READ COMMITTED, so a commit landing in
    between put data in the body that the header's sequence number excludes — under a
    `report_hash` certifying those bytes (Docs/rules.md C7)."""
    from app.domain.reports import service as reports_service

    case = world.case(db)
    walk_to_notified(must_record, case)

    seen: dict[str, str] = {}
    real = reports_service.dash.as_of_seq

    def spy(session, case_ids):
        seen["isolation"] = session.connection().get_isolation_level()
        return real(session, case_ids)

    monkeypatch.setattr(reports_service.dash, "as_of_seq", spy)
    created = client.post(
        "/api/v1/reports", json={"template": "cases_register"}, headers=auth(world.lao)
    )
    assert created.status_code == 202, created.text
    assert seen["isolation"] == reports_service.SNAPSHOT_ISOLATION


# --- 13. jurisdiction, and the texts ------------------------------------------------


def test_a_role_with_no_org_unit_reads_nothing(db, world, client, auth, must_record):
    """`is_national` returned True for an empty scope claim, so a COLLECTOR or ADMIN_RR
    row created without an org unit got country-wide reads — and those are exactly the
    two roles that can unlock names."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    _enumerate(client, auth, case, "Zubeida Khatoon Ansari", world.collector,
               on=date(2025, 2, 3))

    unscoped = _user(db, "COLLECTOR", None)
    assert client.get(f"/api/v1/cases/{case.id}", headers=auth(unscoped)).status_code == 404
    assert client.get(
        f"/api/v1/cases/{case.id}/families", params={"purpose": "anything"},
        headers=auth(unscoped),
    ).status_code == 404
    listed = client.get("/api/v1/cases", headers=auth(unscoped))
    assert listed.status_code == 200
    assert listed.json()["items"] == []


def test_the_masking_refusal_names_only_the_roles_that_can_unlock(
    client, auth, world, db, must_record
):
    """The refusal told State Revenue that names are released to it, so a State officer
    who read it added a purpose and was refused again by the same sentence, with no way
    to tell that their role was the reason."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    _enumerate(client, auth, case, "Zubeida Khatoon Ansari", world.collector,
               on=date(2025, 2, 3))
    state = _user(db, "STATE_REVENUE", world.state.id)

    body = client.get(
        f"/api/v1/cases/{case.id}/families", params={"purpose": "state scrutiny"},
        headers=auth(state),
    ).json()
    assert body["pii"] == "masked"
    assert "State Revenue" not in body["masked_reason"]
    assert "Collector" in body["masked_reason"]
    assert "Administrator R&R" in body["masked_reason"]


def test_delivery_to_a_withdrawn_family_is_refused(db, client, auth, world, must_record):
    """The one seam the F9 exclusion left open: a family whose enumeration was
    reversed must not be able to accrue a new delivery."""
    from datetime import date
    import uuid as _uuid

    from app.domain.rr.service import deliver_entitlement, enumerate_family
    from app.core.problems import Problem
    from tests.helpers import walk_to_awarded

    case = world.case(db)
    walk_to_awarded(must_record, case)
    fam = enumerate_family(
        db, case, world.collector.id,
        head={"name": "Withdrawn Test Family"}, category="landowner",
        displaced=True, sc_st=False, occurred_at=date(2026, 3, 1),
        idempotency_key=str(_uuid.uuid4()),
    )
    db.commit()
    row = fam.family
    from datetime import datetime, timezone
    row.withdrawn_at = datetime.now(timezone.utc)
    db.commit()
    import pytest
    with pytest.raises(Problem) as exc:
        deliver_entitlement(db, case, row, "subsistence_allowance", world.collector.id,
                            delivered_on=date(2026, 4, 1))
    assert exc.value.status == 422
