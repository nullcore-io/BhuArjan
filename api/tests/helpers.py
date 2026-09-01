"""Statutory walk-ups shared by the fixture tests.

Each helper records the real sequence of events an acquisition actually goes through,
through the public API, so the tests exercise the same path an officer would.
"""

from __future__ import annotations

from datetime import date, timedelta

S11_DEFAULT = date(2025, 1, 1)


def walk_to_notified(must_record, case, s11: date = S11_DEFAULT) -> date:
    """PROPOSED -> SIA -> APPRAISED -> NOTIFIED. Returns the s.11 date."""
    must_record(case, "SIA_NOTIFIED", s11 - timedelta(days=61), {"agency": "SIA Unit"})
    must_record(case, "EXPERT_GROUP_APPRAISAL", s11 - timedelta(days=31), {})
    must_record(
        case,
        "PRELIM_NOTIFICATION_S11",
        s11,
        {
            "gazette_no": "S.O. 1(E)",
            "total_area_ha": "12.5000",
            "villages": [{"name": "Testpur", "survey_nos": ["1/1"], "area_ha": "12.5000"}],
        },
    )
    return s11


def satisfy_s19_preconditions(must_record, case, when: date) -> None:
    """s.18 R&R scheme publication and the s.19(2) cost deposit."""
    must_record(case, "RR_SCHEME_DRAFTED_S16", when - timedelta(days=60), {})
    must_record(case, "RR_SCHEME_APPROVED_S17", when - timedelta(days=30), {})
    must_record(case, "RR_SCHEME_PUBLISHED_S18", when, {"scheme_ref": "RR/2025/1"})
    must_record(
        case,
        "COST_DEPOSITED_S19_2",
        when + timedelta(days=1),
        {"amount_paise": 9_00_00_000_00, "challan": "TR-6/1"},
    )


def walk_to_declared(must_record, case, s11: date = S11_DEFAULT, declared_on: date | None = None) -> date:
    """...NOTIFIED -> DECLARED. Returns the s.19 declaration date."""
    walk_to_notified(must_record, case, s11)
    satisfy_s19_preconditions(must_record, case, s11 + timedelta(days=120))
    declared_on = declared_on or (s11 + timedelta(days=180))
    must_record(
        case,
        "DECLARATION_S19",
        declared_on,
        {"gazette_no": "S.O. 2(E)", "total_area_ha": "12.5000"},
    )
    return declared_on


def walk_to_awarded(
    must_record,
    case,
    s11: date = S11_DEFAULT,
    assessed_paise: int = 10_00_000,
) -> tuple[date, int]:
    """...DECLARED -> AWARDED, with the award assessed. Returns (award date, total)."""
    declared_on = walk_to_declared(must_record, case, s11)
    award_on = declared_on + timedelta(days=30)
    must_record(case, "AWARD_S23", award_on, {"award_no": "AWD/1"})
    must_record(
        case,
        "COMPENSATION_ASSESSED",
        award_on + timedelta(days=5),
        {"assessed_total_paise": assessed_paise, "line_count": 1},
    )
    return award_on, assessed_paise


def pay(must_record, case, when: date, amount_paise: int, ref: str = "PFMS/1") -> dict:
    return must_record(
        case,
        "PAYMENT_MADE",
        when,
        {"pfms_ref": ref, "amount_paise": amount_paise, "mode": "PFMS"},
    )


def clocks_on(client, case, headers) -> dict[str, dict]:
    res = client.get(f"/api/v1/cases/{case.id}/clocks", headers=headers)
    assert res.status_code == 200, res.text
    return {c["clock_id"]: c for c in res.json()["items"]}


def event_types(client, case, headers) -> list[str]:
    res = client.get(f"/api/v1/cases/{case.id}/events?limit=500", headers=headers)
    assert res.status_code == 200, res.text
    return [e["type"] for e in res.json()["items"]]
