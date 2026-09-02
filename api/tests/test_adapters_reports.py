"""Module J adapters, the admin rule-set diff, and the MIS reports.

Docs/APIs.md §3.10 (reports), §3.12 (admin), §4 (adapter table); Docs/rules.md C7
(every export carries its as-of sequence and a report hash).

These tests do not stub the seams they are about. The report tests write real bytes
to MinIO, fetch them back over the presigned URL the API handed out, and recompute
the SHA-256 — because "the hash matches" is a claim about the file a judge would
download, not about a variable inside the process. They write into their own bucket
so the demo stack's `bhuarjan-docs` is never touched.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import date, timedelta

import httpx
import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy import select

from app.domain.integrations import ADAPTER_ORDER, get_adapter, list_adapters
from app.domain.reports.models import ReportJob  # noqa: F401 — registers the table
from app.models import AdminAudit, CompensationLine, Document, Parcel
from tests.helpers import walk_to_awarded, walk_to_notified

TEST_BUCKET = "bhuarjan-test-reports"

# A one-hectare-ish square near Seoni, MP — enough for PostGIS to compute an area.
SQUARE_WKT = (
    "MULTIPOLYGON((("
    "79.5000 22.0000, 79.5010 22.0000, 79.5010 22.0010, 79.5000 22.0010, 79.5000 22.0000"
    ")))"
)


@pytest.fixture(scope="module", autouse=True)
def storage_bucket():
    """Point object storage at a throwaway bucket for this module.

    The demo stack is live on the same MinIO; these tests must not leave report
    objects in the bucket the demo serves documents from.
    """
    from app.core.config import settings
    from app.domain.documents import storage

    original = settings.MINIO_BUCKET
    settings.MINIO_BUCKET = TEST_BUCKET
    storage._bucket_ready = False
    storage.ensure_bucket()
    yield TEST_BUCKET
    settings.MINIO_BUCKET = original
    storage._bucket_ready = False


TOTAL_PAISE = 202_00_000_00
PAID_PAISE = 2_00_000_00


@pytest.fixture()
def parcel(db, world):
    """A case with one geo-located parcel and a compensation line against it.

    The survey number, ULPIN and owner reference carry a per-test suffix: several
    tests use this fixture, they all run against the same schema, and a lookup that
    matched two tests' parcels would prove nothing about the query.
    """
    suffix = uuid.uuid4().hex[:6].upper()
    case = world.case(db)
    row = Parcel(
        case_id=case.id,
        village_lgd="482718",
        village_name="Adegaon",
        survey_no=f"112/{suffix}",
        ulpin=f"MP482718{suffix}",
        area_ha=7.2100,
        land_type="rural",
        status="notified",
        geom=WKTElement(SQUARE_WKT, srid=4326),
    )
    db.add(row)
    db.flush()
    db.add(CompensationLine(
        case_id=case.id,
        parcel_id=row.id,
        owner_ref=f"OWN/ADEGAON/{suffix}",
        market_value_paise=50_00_000_00,
        mv_method="circle_rate",
        factor=2.0,
        assets_paise=1_00_000_00,
        base_paise=101_00_000_00,
        solatium_paise=101_00_000_00,
        interest_paise=0,
        total_paise=TOTAL_PAISE,
        paid_paise=PAID_PAISE,
    ))
    db.commit()
    return case, row


# --- registry -----------------------------------------------------------------------


def test_the_registry_holds_the_six_adapters_and_every_one_says_mock():
    adapters = list_adapters()
    assert [a.name for a in adapters] == list(ADAPTER_ORDER)
    for adapter in adapters:
        assert adapter.mode == "mock", f"{adapter.name} claims mode {adapter.mode}"
        described = adapter.describe()
        assert described["title"] and described["real_target"]
        assert described["interface"], f"{adapter.name} describes no interface"
    assert get_adapter("ULPIN") is adapters[0], "lookup is case-insensitive"
    assert get_adapter("no-such-adapter") is None


def test_a_failing_adapter_reports_it_instead_of_raising(monkeypatch):
    adapter = get_adapter("gatishakti")
    monkeypatch.setattr(
        "app.domain.documents.storage.ensure_bucket",
        lambda: (_ for _ in ()).throw(OSError("minio unreachable")),
    )
    result = adapter.test(None)
    assert result["ok"] is False
    assert "minio unreachable" in result["detail"]
    assert adapter.last_test["ok"] is False


# --- ulpin --------------------------------------------------------------------------


def test_ulpin_lookup_answers_from_the_parcels_table_with_the_owner_masked(db, parcel):
    case, row = parcel
    adapter = get_adapter("ulpin")

    record = adapter.lookup(db, row.ulpin.lower())  # case-insensitive
    assert record["found"] is True
    assert record["area_ha"] == 7.21
    assert record["village_lgd"] == "482718"
    assert record["survey_no"] == row.survey_no
    assert record["case_id"] == str(case.id)
    assert record["owner_known"] is True
    masked = record["owner_ref_masked"]
    assert masked != f"OWN/ADEGAON/{row.ulpin[-6:]}" and "ADEGAON" not in masked
    assert masked.startswith("OW") and masked.endswith(row.ulpin[-2:])

    assert adapter.lookup(db, "MP0000000000ZZ")["found"] is False


def test_ulpin_by_survey_reports_which_keys_it_actually_matched_on(db, parcel):
    case, row = parcel
    adapter = get_adapter("ulpin")
    hit = adapter.by_survey(db, village="adegaon", survey_no=row.survey_no)
    assert hit["count"] == 1
    assert hit["matched_on"] == ["village", "survey_no"]
    assert hit["items"][0]["ulpin"] == row.ulpin

    assert adapter.by_survey(db, village="Adegaon", survey_no="999/none")["count"] == 0

    check = adapter.test(db)
    assert check["ok"] is True and check["with_ulpin"] >= 1


# --- pfms ---------------------------------------------------------------------------


def test_pfms_says_paid_only_for_a_reference_the_ledger_carries(db, world, must_record):
    case = world.case(db)
    award_on, _ = walk_to_awarded(must_record, case)
    must_record(case, "PAYMENT_MADE", award_on + timedelta(days=10), {
        "pfms_ref": "PFMS/TEST/9001", "amount_paise": 4_50_000, "mode": "PFMS",
    })
    db.rollback()  # see the API's committed writes, not this session's older snapshot

    adapter = get_adapter("pfms")
    paid = adapter.payment_status(db, "PFMS/TEST/9001")
    assert paid["status"] == "PAID"
    assert paid["amount_paise"] == 4_50_000
    assert paid["date"] == (award_on + timedelta(days=10)).isoformat()
    assert paid["case_id"] == str(case.id)

    unknown = adapter.payment_status(db, "PFMS/NEVER/HAPPENED")
    assert unknown["status"] == "UNKNOWN"
    assert unknown["amount_paise"] is None

    listed = adapter.list_payments(db, str(case.id))
    assert listed["found"] is True and listed["count"] == 1
    assert listed["total_paise"] == 4_50_000
    assert adapter.list_payments(db, "not-a-case")["found"] is False
    assert adapter.test(db)["ok"] is True


# --- gazette ------------------------------------------------------------------------


def test_gazette_search_and_fetch_read_the_seeded_notification_pdfs():
    adapter = get_adapter("gazette")
    found = adapter.search()
    assert found["count"] >= 2, f"no cached gazette PDFs in {found['cache_dir']}"
    refs = {item["ref"] for item in found["items"]}
    assert "gazette_3A_LAQ-SEO-2025-01" in refs
    assert "gazette_3D_LAQ-SEO-2025-01" in refs

    entry = next(i for i in found["items"] if i["ref"] == "gazette_3D_LAQ-SEO-2025-01")
    assert entry["statute"] == "NH_ACT_1956"
    assert entry["section"] == "3D" and entry["section_label"] == "s.3D"
    assert entry["case_ref"] == "LAQ/SEO/2025/01"

    filtered = adapter.search(section="3D")
    assert filtered["count"] == 1
    # No silent drops: every scanned file is either returned or explained.
    assert filtered["count"] + len(filtered["skipped"]) == filtered["scanned"]
    assert all("section" in s["reason"] for s in filtered["skipped"])

    fetched = adapter.fetch("gazette_3D_LAQ-SEO-2025-01")
    assert fetched["found"] is True
    assert fetched["content"].startswith(b"%PDF")
    assert hashlib.sha256(fetched["content"]).hexdigest() == fetched["sha256"]
    assert adapter.fetch("nothing_like_this")["found"] is False
    assert adapter.test()["ok"] is True


# --- digilocker ---------------------------------------------------------------------


def test_digilocker_issues_an_envelope_and_admits_it_stamped_nothing(db, world):
    case = world.case(db)
    sha = hashlib.sha256(b"a declaration").digest()
    doc = Document(
        case_id=case.id,
        kind="declaration_s19",
        storage_key=f"sha256/{sha.hex()[:2]}/{sha.hex()}",
        sha256=sha,
        mime="application/pdf",
        pages=2,
    )
    db.add(doc)
    db.commit()

    adapter = get_adapter("digilocker")
    envelope = adapter.issue(db, doc.id)
    assert envelope["found"] is True
    assert envelope["watermarked"] is True
    assert envelope["uri"].endswith(sha.hex())
    assert envelope["mode"] == "mock"
    # The honesty requirement of APIs.md §4: the reply says what was not done.
    assert "does not rewrite the PDF" in envelope["detail"]
    assert "esign(document_id, signer)" in adapter.describe()["deferred"]

    assert adapter.issue(db, uuid.uuid4())["found"] is False
    assert adapter.issue(db, "not-a-uuid")["found"] is False
    assert adapter.test(db)["ok"] is True


# --- gatishakti ---------------------------------------------------------------------


def test_gatishakti_export_writes_the_project_geojson_to_object_storage(db, parcel):
    case, row = parcel
    adapter = get_adapter("gatishakti")

    export = adapter.export(db, case.project_id)
    assert export["found"] is True
    assert export["features"] == 1
    assert export["cases"] >= 1
    assert export["mime"] == "application/geo+json"

    fetched = httpx.get(export["url"], timeout=20)
    assert fetched.status_code == 200, fetched.text
    assert hashlib.sha256(fetched.content).hexdigest() == export["sha256"]
    fc = json.loads(fetched.content)
    assert fc["type"] == "FeatureCollection"
    assert fc["properties"]["project_id"] == str(case.project_id)
    assert fc["features"][0]["properties"]["survey_no"] == row.survey_no

    assert adapter.export(db, uuid.uuid4())["found"] is False
    assert adapter.test(db)["ok"] is True


# --- notify -------------------------------------------------------------------------


def test_notify_logs_the_delivery_and_masks_the_recipient(caplog):
    adapter = get_adapter("notify")
    with caplog.at_level("INFO", logger="bhuarjan.notify"):
        record = adapter.send("sms", "9876543210", "clock_red", {"clock": "AWARD_S23"})
    assert record["status"] == "logged"
    assert record["to"] == "98••••••10"
    assert record["channel"] == "sms"
    assert record["vars"] == {"clock": "AWARD_S23"}
    assert "9876543210" not in caplog.text, "the raw recipient reached the log"
    assert "98••••••10" in caplog.text

    assert adapter.send("carrier-pigeon", "x@y.in", "t")["status"] == "rejected"
    assert adapter.send("email", "", "t")["status"] == "rejected"
    assert adapter.send("email", "officer@nic.in", "t")["to"] == "of•••er@nic.in"
    # An address is masked as an address whatever channel carried it.
    assert adapter.send("inapp", "officer@nic.in", "t")["to"] == "of•••er@nic.in"
    assert adapter.test()["ok"] is True


# --- admin: integrations ------------------------------------------------------------


def test_admin_integrations_lists_the_registry_and_the_test_button_runs_it(
    db, world, client, auth
):
    listed = client.get("/api/v1/admin/integrations", headers=auth(world.collector))
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert [i["name"] for i in body["items"]] == list(ADAPTER_ORDER)
    assert body["live_count"] == 0
    assert all(i["mode"] == "mock" for i in body["items"])

    ran = client.post(
        "/api/v1/admin/integrations/notify/test", headers=auth(world.collector)
    )
    assert ran.status_code == 200, ran.text
    assert ran.json()["ok"] is True
    assert ran.json()["mode"] == "mock"

    again = client.get("/api/v1/admin/integrations", headers=auth(world.collector))
    notify = next(i for i in again.json()["items"] if i["name"] == "notify")
    assert notify["last_test"]["ok"] is True and notify["last_test"]["at"]

    db.rollback()
    audited = db.scalars(
        select(AdminAudit).where(AdminAudit.action == "INTEGRATION_TEST")
    ).all()
    assert any(a.target == "notify" for a in audited)


def test_an_unknown_adapter_and_a_read_only_role_are_both_404(world, client, auth):
    assert client.post(
        "/api/v1/admin/integrations/nope/test", headers=auth(world.collector)
    ).status_code == 404
    # LAO records events; wiring a test call out to PFMS is not their button.
    assert client.post(
        "/api/v1/admin/integrations/pfms/test", headers=auth(world.lao)
    ).status_code == 404


# --- admin: rule-sets and the overlay diff ------------------------------------------


def test_admin_rulesets_show_the_overlay_with_its_base_and_title(world, client, auth):
    res = client.get("/api/v1/admin/rulesets", headers=auth(world.lao))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["overlay_count"] >= 1

    overlay = next(i for i in body["items"] if i["version"] == "2026.09-MH")
    assert overlay["is_overlay"] is True
    assert overlay["base_version"] == "2026.09"
    assert "Maharashtra" in overlay["overlay_title"]
    assert overlay["file"] == "rfctlarr_2013_mh_2018.yaml"
    assert overlay["ref"] == "RFCTLARR_2013@2026.09-MH"

    base = next(i for i in body["items"] if i["ref"] == "RFCTLARR_2013@2026.09")
    assert base["is_overlay"] is False and base["base_version"] is None


def test_the_ruleset_diff_shows_the_state_variation_as_a_config_change(
    world, client, auth
):
    res = client.get(
        "/api/v1/admin/rulesets/diff",
        params={
            "base": "RFCTLARR_2013@2026.09",
            "overlay": "RFCTLARR_2013@2026.09-MH",
        },
        headers=auth(world.lao),
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/plain")
    body = res.text
    assert "+++" in body and "---" in body
    assert "RFCTLARR_2013@2026.09-MH" in body
    # The two substantive lines the stage demo points at.
    assert "s.10A" in body
    assert "DIVISIONAL_COMMISSIONER" in body
    assert res.headers["X-Ruleset-Base"] == "RFCTLARR_2013@2026.09"


def test_a_diff_of_an_unloaded_or_malformed_ruleset_ref_is_refused(world, client, auth):
    missing = client.get(
        "/api/v1/admin/rulesets/diff",
        params={"base": "RFCTLARR_2013@1999.01", "overlay": "RFCTLARR_2013@2026.09-MH"},
        headers=auth(world.lao),
    )
    assert missing.status_code == 404
    assert missing.json()["type"] == "not_found"

    malformed = client.get(
        "/api/v1/admin/rulesets/diff",
        params={"base": "RFCTLARR_2013", "overlay": "RFCTLARR_2013@2026.09-MH"},
        headers=auth(world.lao),
    )
    assert malformed.status_code == 422
    assert malformed.json()["type"] == "validation_error"


# --- reports ------------------------------------------------------------------------


def _download(client, headers, job_id: str) -> tuple[dict, bytes]:
    """Fetch the job, follow its presigned URL, return (payload, body bytes)."""
    res = client.get(f"/api/v1/reports/{job_id}", headers=headers)
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["status"] == "done"
    fetched = httpx.get(payload["url"], timeout=20)
    assert fetched.status_code == 200, fetched.text
    return payload, fetched.content


def test_a_cases_register_csv_downloads_and_its_hash_matches_the_bytes(
    db, world, client, auth, must_record
):
    case = world.case(db, case_no="RPT/CSV/0001")
    walk_to_awarded(must_record, case)
    headers = auth(world.lao)

    created = client.post(
        "/api/v1/reports",
        json={"template": "cases_register", "filters": {}, "format": "csv"},
        headers=headers,
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    assert created.headers["Location"].endswith(job_id)

    payload, body = _download(client, headers, job_id)
    assert hashlib.sha256(body).hexdigest() == payload["report_hash"]
    assert payload["as_of_seq"] > 0
    assert payload["generated_at"]

    text = body.decode("utf-8")
    first_line = text.splitlines()[0]
    assert first_line == f"# as_of_seq={payload['as_of_seq']}"

    rows = list(csv.reader(io.StringIO(
        "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
    )))
    header = rows[0]
    assert header[:5] == ["case_no", "project", "statute", "stage", "district"]
    line = next(r for r in rows[1:] if r[0] == "RPT/CSV/0001")
    assert line[header.index("stage")] == "AWARDED"
    assert line[header.index("district")] == world.district.name
    assert payload["row_count"] == len(rows) - 1


def test_the_compensation_register_lists_every_award_line(db, world, client, auth, parcel):
    case, row = parcel
    headers = auth(world.lao)
    created = client.post(
        "/api/v1/reports",
        json={"template": "compensation_register", "format": "csv"},
        headers=headers,
    )
    assert created.status_code == 202, created.text
    payload, body = _download(client, headers, created.json()["job_id"])
    assert hashlib.sha256(body).hexdigest() == payload["report_hash"]

    text = body.decode("utf-8")
    rows = list(csv.reader(io.StringIO(
        "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
    )))
    header = rows[0]
    owner_ref = f"OWN/ADEGAON/{row.ulpin[-6:]}"
    line = next(r for r in rows[1:] if r[header.index("owner_ref")] == owner_ref)
    assert line[header.index("survey_no")] == row.survey_no
    assert line[header.index("total_paise")] == str(TOTAL_PAISE)
    assert line[header.index("paid_paise")] == str(PAID_PAISE)
    assert line[header.index("outstanding_paise")] == str(TOTAL_PAISE - PAID_PAISE)


def test_the_national_kpi_export_carries_the_source_of_every_number(
    db, world, client, auth, must_record
):
    case = world.case(db)
    walk_to_notified(must_record, case)
    headers = auth(world.lao)
    created = client.post(
        "/api/v1/reports", json={"template": "national_kpis"}, headers=headers
    )
    assert created.status_code == 202, created.text
    payload, body = _download(client, headers, created.json()["job_id"])
    text = body.decode("utf-8")
    assert text.startswith(f"# as_of_seq={payload['as_of_seq']}\n")
    assert "# template=national_kpis" in text

    rows = {
        r[0]: r
        for r in csv.reader(io.StringIO(
            "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
        ))
    }
    assert rows["kpi"][2] == "source"
    assert "area_notified_ha" in rows and "comp_paid_paise" in rows
    assert any(k.startswith("clocks_by_status.") for k in rows)


def test_the_cases_register_geojson_carries_the_parcels_and_the_as_of_seq(
    world, client, auth, parcel
):
    case, row = parcel
    headers = auth(world.lao)
    created = client.post(
        "/api/v1/reports",
        json={"template": "cases_register", "format": "geojson"},
        headers=headers,
    )
    assert created.status_code == 202, created.text
    payload, body = _download(client, headers, created.json()["job_id"])
    assert hashlib.sha256(body).hexdigest() == payload["report_hash"]

    fc = json.loads(body)
    assert fc["type"] == "FeatureCollection"
    assert fc["as_of_seq"] == payload["as_of_seq"]
    assert fc["report"]["template"] == "cases_register"
    feature = next(
        f for f in fc["features"] if f["properties"]["survey_no"] == row.survey_no
    )
    assert feature["properties"]["case_no"] == case.case_no
    assert feature["geometry"]["type"] == "MultiPolygon"


def test_a_report_only_covers_the_cases_its_requester_could_open(
    db, world, client, auth, must_record
):
    """A district officer's export cannot contain another district's case."""
    from app.models import Case, OrgUnit, Project
    from app.domain.cases.projections import ensure_case_state

    mine = world.case(db, case_no="RPT/SCOPE/MINE")
    other_district = OrgUnit(kind="district", name=f"Elsewhere {uuid.uuid4().hex[:6]}")
    db.add(other_district)
    db.flush()
    project = Project(
        name="Elsewhere project", sector="Testing", statute_track="RFCTLARR_2013",
        ruleset_version="2026.09", state_code="TS",
    )
    db.add(project)
    db.flush()
    theirs = Case(
        project_id=project.id, district_id=other_district.id,
        case_no="RPT/SCOPE/THEIRS", statute_track="RFCTLARR_2013",
        ruleset_version="2026.09",
    )
    db.add(theirs)
    db.flush()
    ensure_case_state(db, theirs)
    db.commit()

    headers = auth(world.lao)
    created = client.post(
        "/api/v1/reports", json={"template": "cases_register"}, headers=headers
    )
    _, body = _download(client, headers, created.json()["job_id"])
    text = body.decode("utf-8")
    assert "RPT/SCOPE/MINE" in text
    assert "RPT/SCOPE/THEIRS" not in text


def test_a_finished_report_is_readable_by_its_requester_and_the_ministry_only(
    db, world, client, auth
):
    headers = auth(world.lao)
    job_id = client.post(
        "/api/v1/reports", json={"template": "cases_register"}, headers=headers
    ).json()["job_id"]

    assert client.get(f"/api/v1/reports/{job_id}", headers=headers).status_code == 200
    assert client.get(
        f"/api/v1/reports/{job_id}", headers=auth(world.collector)
    ).status_code == 404
    assert client.get(
        f"/api/v1/reports/{job_id}", headers=auth(world.ministry_user)
    ).status_code == 200
    assert client.get(
        f"/api/v1/reports/{uuid.uuid4()}", headers=headers
    ).status_code == 404
    assert client.get("/api/v1/reports/not-a-uuid", headers=headers).status_code == 404


def test_a_template_or_format_this_build_cannot_produce_is_refused(world, client, auth):
    headers = auth(world.lao)
    unknown = client.post(
        "/api/v1/reports", json={"template": "quarterly_wishlist"}, headers=headers
    )
    assert unknown.status_code == 422
    assert unknown.json()["type"] == "validation_error"

    pdf = client.post(
        "/api/v1/reports",
        json={"template": "cases_register", "format": "pdf"},
        headers=headers,
    )
    assert pdf.status_code == 422
    assert "pdf" in json.dumps(pdf.json()["errors"])

    wrong_shape = client.post(
        "/api/v1/reports",
        json={"template": "national_kpis", "format": "geojson"},
        headers=headers,
    )
    assert wrong_shape.status_code == 422
    assert "geojson is only available" in json.dumps(wrong_shape.json()["errors"])

    templates = client.get("/api/v1/reports/templates", headers=headers).json()
    assert templates["templates"] == [
        "national_kpis", "cases_register", "compensation_register"
    ]
    assert templates["geojson_templates"] == ["cases_register"]


def test_an_operator_supplied_case_number_cannot_carry_a_formula_into_excel(
    db, world, client, auth
):
    """`case_no` is free text an officer types, and these exports are opened in
    Excel: a value starting `=` would be evaluated on open, from a file carrying our
    own report hash."""
    world.case(db, case_no="=HYPERLINK(\"http://evil.invalid\")")
    headers = auth(world.lao)
    created = client.post(
        "/api/v1/reports", json={"template": "cases_register"}, headers=headers
    )
    _, body = _download(client, headers, created.json()["job_id"])
    text = body.decode("utf-8")
    assert "=HYPERLINK" in text  # the value is preserved...
    assert "\n\"'=HYPERLINK" in text  # ...behind the apostrophe that defuses it


def test_reports_require_authentication(client):
    assert client.post("/api/v1/reports", json={"template": "cases_register"}).status_code == 401
    assert client.get(f"/api/v1/reports/{uuid.uuid4()}").status_code == 401


def test_an_empty_jurisdiction_still_produces_a_stamped_export(db, world, client, auth):
    """A caller whose scope holds nothing gets a header row and an as_of_seq, not a
    500 and not an empty file that says nothing about when it was true."""
    from app.core.security import create_token

    token = create_token(str(uuid.uuid4()), "nobody", ["LAO"], [str(uuid.uuid4())])
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/reports", json={"template": "cases_register"}, headers=headers
    )
    assert created.status_code == 202, created.text
    assert created.json()["row_count"] == 0

    payload, body = _download(client, headers, created.json()["job_id"])
    text = body.decode("utf-8")
    assert text.startswith("# as_of_seq=0\n")
    assert "case_no,project,statute" in text


def test_the_report_date_follows_the_demo_clock(db, world, client, auth, must_record):
    """X-Demo-Date reaches the KPI computation (Docs/rules.md C2) — a report run on
    the demo clock is the same report the dashboard shows on that date."""
    case = world.case(db)
    walk_to_notified(must_record, case)
    headers = auth(world.lao, date(2026, 11, 30))
    created = client.post(
        "/api/v1/reports", json={"template": "national_kpis"}, headers=headers
    )
    assert created.status_code == 202, created.text
    _, body = _download(client, headers, created.json()["job_id"])
    assert b"timeline_adherence_pct" in body
