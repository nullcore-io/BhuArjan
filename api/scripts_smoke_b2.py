"""Lane B2 smoke test — extraction templates and compensation arithmetic.

No database, no MinIO, no network: it generates the demo gazette PDFs with
`seed.make_gazette_pdfs`, runs the regex extraction over them, and checks the First
Schedule computation against figures worked by hand.

    api/.venv/Scripts/python.exe scripts_smoke_b2.py

Exit code 0 = every check passed. Every check is run even after one fails, and the
tally at the end names how many ran, so a failure can never hide behind an early exit.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

FAILURES: list[str] = []
CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}" + (f" — {detail}" if detail else ""))
        FAILURES.append(label)


def eq(label: str, got, want) -> None:
    check(label, got == want, f"got {got!r}, want {want!r}")


# ---------------------------------------------------------------- extraction


def extraction_checks(tmp: Path) -> None:
    from app.domain.documents.extraction import (
        CONF_DERIVED,
        CONF_REGEX,
        extract_from_pages,
        page_texts,
    )
    from seed.make_gazette_pdfs import make_all

    print("\n[1] gazette PDF generation")
    paths = make_all(tmp)
    eq("four notifications generated", sorted(paths), ["3A", "3D", "S11", "S19"])
    for key, path in paths.items():
        check(f"{key} pdf is a non-trivial file", path.exists() and path.stat().st_size > 2000,
              f"{path} size={path.stat().st_size if path.exists() else 'missing'}")

    eq("regex confidence convention", CONF_REGEX, 0.95)
    eq("derived confidence convention", CONF_DERIVED, 0.70)

    texts = {k: page_texts(p.read_bytes()) for k, p in paths.items()}
    results = {k: extract_from_pages(t) for k, t in texts.items()}

    # --- NH Act 3A -----------------------------------------------------------
    print("\n[2] NH Act 1956 s.3A notification")
    r = results["3A"]
    f = r.fields
    eq("statute", f.get("statute"), "NH_ACT_1956")
    eq("section", f.get("section"), "3A")
    eq("gazette_no", f.get("gazette_no"), "S.O. 4211(E)")
    eq("publication_date", f.get("publication_date"), "2025-09-27")
    eq("state", f.get("state"), "Madhya Pradesh")
    eq("district", f.get("district"), "Seoni")
    eq("total_area_ha", f.get("total_area_ha"), "18.6400")
    check("competent_authority names the SDO",
          "Verma" in (f.get("competent_authority") or ""), repr(f.get("competent_authority")))
    eq("village count", len(f.get("villages") or []), 3)
    eq("village[0]", (f["villages"][0]["name"], f["villages"][0]["tehsil"],
                      f["villages"][0]["survey_nos"], f["villages"][0]["area_ha"]),
       ("Adegaon", "Seoni", ["112/1", "112/2", "118"], "7.2100"))
    eq("village[1] survey numbers", f["villages"][1]["survey_nos"], ["57", "58/2"])
    eq("village[2] area", f["villages"][2]["area_ha"], "5.4000")
    check("schedule areas sum to the printed total",
          abs(sum(float(v["area_ha"]) for v in f["villages"]) - 18.64) < 1e-9)

    eq("statute confidence is a regex hit", r.confidence.get("statute"), CONF_REGEX)
    eq("publication_date confidence is a regex hit",
       r.confidence.get("publication_date"), CONF_REGEX)
    check("a field the 3A does not carry has null confidence, not a number",
          r.confidence.get("prior_notification_date") is None,
          repr(r.confidence.get("prior_notification_date")))
    check("no warnings on a clean 3A", r.warnings == [], repr(r.warnings))
    eq("engine is regex-only offline", r.engine, "regex")

    span = r.source_spans.get("publication_date")
    check("publication_date has a source span", isinstance(span, dict) and "page" in span,
          repr(span))
    if span:
        quoted = texts["3A"][span["page"] - 1][span["start"]:span["end"]]
        check("the span quotes the dateline it read",
              "September" in quoted and "2025" in quoted, repr(quoted))
    check("every village row carries a span",
          all(f"villages[{i}]" in r.source_spans for i in range(3)),
          repr(sorted(k for k in r.source_spans if k.startswith("villages"))))

    ev = r.proposed_event
    check("a proposed event was produced", isinstance(ev, dict), repr(ev))
    eq("proposed event type", (ev or {}).get("type"), "NOTIFICATION_3A")
    eq("proposed occurred_at is the publication date",
       (ev or {}).get("occurred_at"), "2025-09-27")
    eq("proposed payload carries the schedule",
       len(((ev or {}).get("payload") or {}).get("villages") or []), 3)

    # --- NH Act 3D -----------------------------------------------------------
    print("\n[3] NH Act 1956 s.3D declaration")
    r = results["3D"]
    f = r.fields
    eq("statute", f.get("statute"), "NH_ACT_1956")
    eq("section", f.get("section"), "3D")
    eq("gazette_no is this notification, not the one it recites",
       f.get("gazette_no"), "S.O. 3902(E)")
    eq("publication_date is the dateline, not the recited 3A date",
       f.get("publication_date"), "2026-08-28")
    eq("prior_gazette_no", f.get("prior_gazette_no"), "S.O. 4211(E)")
    eq("prior_notification_date", f.get("prior_notification_date"), "2025-09-27")
    eq("proposed event type", (r.proposed_event or {}).get("type"), "DECLARATION_3D")
    eq("proposed occurred_at", (r.proposed_event or {}).get("occurred_at"), "2026-08-28")
    eq("village count", len(f.get("villages") or []), 3)
    eq("total_area_ha", f.get("total_area_ha"), "18.6400")

    # --- RFCTLARR s.11 -------------------------------------------------------
    print("\n[4] RFCTLARR 2013 s.11 preliminary notification")
    r = results["S11"]
    f = r.fields
    eq("statute", f.get("statute"), "RFCTLARR_2013")
    eq("section", f.get("section"), "11")
    eq("gazette_no", f.get("gazette_no"), "S.O. 812(E)")
    eq("publication_date", f.get("publication_date"), "2025-10-20")
    eq("district", f.get("district"), "Balaghat")
    eq("village count", len(f.get("villages") or []), 2)
    eq("total_area_ha", f.get("total_area_ha"), "13.5500")
    eq("proposed event type", (r.proposed_event or {}).get("type"),
       "PRELIM_NOTIFICATION_S11")

    # --- RFCTLARR s.19 -------------------------------------------------------
    print("\n[5] RFCTLARR 2013 s.19 declaration")
    r = results["S19"]
    f = r.fields
    eq("statute", f.get("statute"), "RFCTLARR_2013")
    eq("section", f.get("section"), "19")
    eq("gazette_no", f.get("gazette_no"), "S.O. 1477(E)")
    eq("publication_date is the declaration's own date",
       f.get("publication_date"), "2026-08-14")
    eq("prior_notification_date is the s.11 date",
       f.get("prior_notification_date"), "2025-10-20")
    eq("proposed event type", (r.proposed_event or {}).get("type"), "DECLARATION_S19")

    # --- negative cases ------------------------------------------------------
    print("\n[6] extraction refuses to guess")
    blank = extract_from_pages([""])
    check("an empty text layer is flagged for OCR, not silently emptied",
          blank.ocr is True and blank.proposed_event is None, repr(blank.as_dict()))
    junk = extract_from_pages(["A memorandum about office stationery. Nothing statutory."])
    eq("no statute -> no section", junk.fields.get("section"), None)
    check("no statute -> no proposed event", junk.proposed_event is None,
          repr(junk.proposed_event))
    check("no statute -> a warning says so", any("statute" in w for w in junk.warnings),
          repr(junk.warnings))


# ------------------------------------------------------------- compensation


def compensation_checks() -> None:
    from app.domain.compensation.service import INTEREST_RATE, compute_line

    print("\n[7] First Schedule computation (rules.md B4)")
    eq("s.30(3) interest rate", float(INTEREST_RATE), 0.12)

    # ₹1,00,000 market value, rural factor 2.0, ₹5,000 of attached assets,
    # one full year between the s.11/3A notification and the award.
    line = compute_line(
        market_value_paise=10_000_000,
        factor=2.0,
        assets_paise=500_000,
        interest_from=date(2025, 9, 27),
        interest_to=date(2026, 9, 27),
    )
    eq("T = MV x F + A", line["base_paise"], 20_500_000)
    eq("solatium is 100% of T (s.30(1))", line["solatium_paise"], line["base_paise"])
    eq("interest days", line["interest_days"], 365)
    eq("interest = 12% of MV for one year", line["interest_paise"], 1_200_000)
    eq("total = T + solatium + interest", line["total_paise"], 42_200_000)
    check("solatium is not charged on the interest",
          line["total_paise"] == 2 * line["base_paise"] + line["interest_paise"])

    # Part-year interest, worked by hand: 100,000,000 x 0.12 x 181 / 365
    part = compute_line(100_000_000, 1.0, 0, date(2025, 1, 1), date(2025, 7, 1))
    eq("part-year interest days", part["interest_days"], 181)
    eq("part-year interest rounds half-up", part["interest_paise"], 5_950_685)

    # Urban land: factor 1.00, no assets.
    urban = compute_line(75_000_000, 1.0, 0, None, None)
    eq("urban factor 1.0 leaves MV as T", urban["base_paise"], 75_000_000)
    eq("no interest window -> no interest", urban["interest_paise"], 0)
    eq("urban total is twice MV", urban["total_paise"], 150_000_000)

    # Rounding: a factor that lands on half a paisa rounds half-up, once.
    half = compute_line(333, 1.5, 0, None, None)
    eq("499.5 paise rounds half-up to 500", half["base_paise"], 500)
    eq("factor 1.5 total", half["total_paise"], 1000)

    # An award dated before the notification cannot generate negative interest.
    backwards = compute_line(10_000_000, 1.0, 0, date(2026, 1, 1), date(2025, 1, 1))
    eq("a reversed window yields zero days", backwards["interest_days"], 0)
    eq("a reversed window yields zero interest", backwards["interest_paise"], 0)

    # Assets are added after the factor, never multiplied by it (s.29 vs Schedule I).
    assets = compute_line(1_000_000, 2.0, 1_000_000, None, None)
    eq("A is not multiplied by F", assets["base_paise"], 3_000_000)

    # Portfolio total, the figure `assess()` puts on COMPENSATION_ASSESSED.
    lines = [
        compute_line(10_000_000, 2.0, 500_000, date(2025, 9, 27), date(2026, 9, 27)),
        compute_line(6_000_000, 1.5, 0, date(2025, 9, 27), date(2026, 9, 27)),
    ]
    # line 2 by hand: T = 6,000,000 x 1.5 = 9,000,000; solatium 9,000,000;
    # interest = 6,000,000 x 12% for one year = 720,000; total 18,720,000.
    eq("second line total", lines[1]["total_paise"], 18_720_000)
    eq("assessed total is the sum of the line totals",
       sum(line_["total_paise"] for line_ in lines),
       42_200_000 + 18_720_000)


# --------------------------------------------------------------- dashboards


def dashboard_contract_checks() -> None:
    from app.domain.dashboards.service import EXPLAIN_KPIS, KPI_KEYS

    print("\n[8] dashboard contract (APIs.md §3.10)")
    eq("KPI keys, in the order the contract lists them", KPI_KEYS, [
        "area_proposed_ha", "area_notified_ha", "area_acquired_ha",
        "notifications_issued", "awards_declared", "comp_assessed_paise",
        "comp_paid_paise", "possession_pct", "rr_progress_pct", "families_affected",
        "families_displaced", "timeline_adherence_pct", "clocks_by_status",
    ])
    for kpi in ("comp_assessed", "comp_paid", "area"):
        check(f"/explain accepts {kpi}", kpi in EXPLAIN_KPIS)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="bhuarjan-b2-") as tmp:
        extraction_checks(Path(tmp))
    compensation_checks()
    dashboard_contract_checks()

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    if FAILURES:
        print("failed:")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("lane B2 smoke: GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
