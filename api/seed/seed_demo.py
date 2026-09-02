"""Demo seed — one real-shaped NH project walked through the statute, plus an RFCTLARR case.

Data is real-shaped but SYNTHETIC (parcels, names, amounts) — labelled via payload.synthetic.
Designed against today ≈ 2026-09-02:
  Case 1 LAQ/SEO/2025/01 (NH): 3A on 2025-09-27 → 3D clock due 2026-09-27 → ~93% elapsed, RED.
      The live demo uploads the 3D declaration PDF (seed/demo_uploads/) and closes the clock.
  Case 2 LAQ/SEO/2024/07 (NH): full lifecycle to possession — populates dashboards/compensation.
      4 affected families (2 displaced); Second Schedule heads mostly delivered after possession.
  Case 3 LAQ/BLG/2025/03 (RFCTLARR): s.11 2025-10-20 → s.19 clock ~87%, AMBER; preconditions
      (R&R published, cost deposited) already met so s.19 can be recorded live.
      5 affected families (3 displaced), every entitlement still due — there is no award yet.

Idempotent: seed_if_empty() no-ops when projects exist.
"""

import logging
import uuid
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

DEMO_PASSWORD = "demo123"


def seed_if_empty() -> None:
    from app.core.db import SessionLocal
    from app.models import Project

    with SessionLocal() as db:
        if db.query(Project).first() is not None:
            log.info("seed: projects exist, skipping")
            return
    seed()


def _mk_user(db, email, name, roles_scopes):
    from app.core.security import hash_password
    from app.models import RoleAssignment, User

    u = User(email=email, name=name, password_hash=hash_password(DEMO_PASSWORD))
    db.add(u)
    db.flush()
    for role, org_id in roles_scopes:
        db.add(RoleAssignment(user_id=u.id, role=role, org_unit_id=org_id))
    return u


def _rect(lon, lat, w=0.004, h=0.003):
    return (
        f"MULTIPOLYGON((({lon} {lat}, {lon + w} {lat}, {lon + w} {lat + h}, "
        f"{lon} {lat + h}, {lon} {lat})))"
    )


def _add_parcels(db, case, specs):
    from geoalchemy2.elements import WKTElement

    from app.models import Parcel

    parcels = []
    for village, lgd, survey, area, lon, lat, status in specs:
        p = Parcel(
            case_id=case.id,
            village_name=village,
            village_lgd=lgd,
            survey_no=survey,
            ulpin=f"MP{lgd}{survey.replace('/', '')}".ljust(14, "0")[:14],
            area_ha=area,
            land_type="rural",
            status=status,
            geom=WKTElement(_rect(lon, lat), srid=4326),
        )
        db.add(p)
        parcels.append(p)
    db.flush()
    return parcels


def _append(db, case, actor, type_, occurred, payload=None, document_id=None):
    from app.domain.events.service import append_event

    payload = dict(payload or {})
    payload.setdefault("synthetic", True)
    if document_id is None:
        payload.setdefault("no_document_reason", "seeded demo record; gazette copy pending upload")
    return append_event(
        db,
        case,
        type_,
        occurred,
        actor.id,
        payload,
        document_id=document_id,
        idempotency_key=f"seed:{case.id}:{type_}:{occurred.isoformat()}:{uuid.uuid4().hex[:6]}",
    )


def _seed_families(db, case, actor, specs):
    """Enumerate synthetic affected families (module F, Docs/APIs.md §3.8).

    Names are invented; the villages are real (Docs/rules.md A5: "use synthetic names on
    real geography if needed, and say so"). Every record is flagged `synthetic` both in
    the ledger payload and in the family's consent flags, and no real identifier is used
    — the ID and bank references are the last four characters only, by construction.

    Placement in the walk-up is not decorative. `FAMILY_ENUMERATED` is on the `NOTIFIED`
    and `DECLARED` stage lists of the rule-sets, not on `AWARDED`/`POSSESSED`, so the
    census is recorded where the Act actually takes it — with the R&R scheme, before the
    award — and the ledger refuses it anywhere else.
    """
    from app.domain.rr.service import enumerate_family

    families = []
    for spec in specs:
        enrolled = enumerate_family(
            db,
            case,
            actor.id,
            head=spec["head"],
            category=spec.get("category"),
            displaced=spec.get("displaced", False),
            sc_st=spec.get("sc_st", False),
            occurred_at=spec["on"],
            idempotency_key=f"seed:{case.id}:FAMILY_ENUMERATED:{spec['head']['name']}",
            synthetic=True,
        )
        families.append(enrolled.family)
    return families


def _seed_deliveries(db, case, actor, family, heads, start: date, every_days: int = 9):
    """Record Second/Third Schedule heads as delivered, one event each."""
    from app.domain.rr.service import deliver_entitlement

    when = start
    for head in heads:
        deliver_entitlement(
            db,
            case,
            family,
            head,
            actor.id,
            delivered_on=when,
            idempotency_key=f"seed:{case.id}:{family.id}:{head}",
            synthetic=True,
        )
        when = when + timedelta(days=every_days)


def _try_upload_pdf(db, case, actor, kind, pdf_path: Path):
    """Store a generated gazette PDF as a case document. Returns document id or None."""
    try:
        from app.domain.documents.storage import store_file

        data = pdf_path.read_bytes()
        doc = store_file(db, data, filename=pdf_path.name, case_id=case.id, kind=kind,
                         mime="application/pdf", uploaded_by=actor.id)
        return doc.id
    except Exception:
        log.exception("seed: document upload skipped (%s)", pdf_path.name)
        return None


def seed() -> None:
    from app.core.db import SessionLocal
    from app.models import Case, OrgUnit, Project

    log.info("seed: starting")
    with SessionLocal() as db:
        # --- org units ---
        dolr = OrgUnit(kind="ministry", name="Department of Land Resources (MoRD)")
        mp = OrgUnit(kind="state", name="Madhya Pradesh", lgd_code="23")
        db.add_all([dolr, mp])
        db.flush()
        seoni = OrgUnit(kind="district", name="Seoni", parent_id=mp.id, lgd_code="23413")
        balaghat = OrgUnit(kind="district", name="Balaghat", parent_id=mp.id, lgd_code="23417")
        nhai = OrgUnit(kind="requiring_body", name="National Highways Authority of India")
        mptransco = OrgUnit(kind="requiring_body", name="MP Power Transmission Co. Ltd.")
        db.add_all([seoni, balaghat, nhai, mptransco])
        db.flush()

        # --- users ---
        lao = _mk_user(db, "lao@demo", "A. Verma (LAO, Seoni)",
                       [("LAO", seoni.id), ("LAO", balaghat.id)])
        _mk_user(db, "collector@demo", "S. Iyer (Collector, Seoni)", [("COLLECTOR", seoni.id)])
        _mk_user(db, "state@demo", "R. Chauhan (State Revenue, MP)", [("STATE_REVENUE", mp.id)])
        _mk_user(db, "ministry@demo", "DoLR Programme Division", [("MINISTRY", dolr.id)])
        _mk_user(db, "auditor@demo", "CAG Audit Cell", [("AUDITOR", None)])
        _mk_user(db, "rb@demo", "NHAI PIU Seoni", [("RB", nhai.id)])

        # --- projects ---
        nh_project = Project(
            name="NH-44 Lakhnadon–Seoni 4-laning (Pkg II)",
            sector="National Highways",
            requiring_body_id=nhai.id,
            statute_track="NH_ACT_1956",
            ruleset_version="2026.09",
            state_code="MP",
        )
        tl_project = Project(
            name="Seoni–Balaghat 220 kV Transmission Line",
            sector="Power Transmission",
            requiring_body_id=mptransco.id,
            statute_track="RFCTLARR_2013",
            ruleset_version="2026.09",
            state_code="MP",
        )
        db.add_all([nh_project, tl_project])
        db.flush()

        # --- gazette PDFs (B2's generator; demo uploads dir for the live 3D upload) ---
        uploads = Path(__file__).parent / "demo_uploads"
        uploads.mkdir(exist_ok=True)
        pdf_3a = pdf_3d = None
        try:
            from seed.make_gazette_pdfs import make_3a_pdf, make_3d_pdf

            pdf_3a = uploads / "gazette_3A_LAQ-SEO-2025-01.pdf"
            pdf_3d = uploads / "gazette_3D_LAQ-SEO-2025-01.pdf"
            # Regenerate only when missing: the committed PDFs are the demo's known
            # inputs and reportlab would otherwise churn their bytes on every boot.
            if not pdf_3a.exists():
                pdf_3a = make_3a_pdf(pdf_3a)
            if not pdf_3d.exists():
                pdf_3d = make_3d_pdf(pdf_3d)
        except Exception:
            log.exception("seed: gazette PDF generation unavailable")

        # ---------- Case 1: the live-demo case (3D clock red, upload closes it) ----------
        case1 = Case(project_id=nh_project.id, district_id=seoni.id, case_no="LAQ/SEO/2025/01",
                     statute_track="NH_ACT_1956", ruleset_version="2026.09")
        db.add(case1)
        db.flush()
        doc_3a = _try_upload_pdf(db, case1, lao, "notification_3a", pdf_3a) if pdf_3a else None
        _append(db, case1, lao, "NOTIFICATION_3A", date(2025, 9, 27), {
            "gazette_no": "S.O. 4211(E)",
            "total_area_ha": "18.6400",
            "villages": [
                {"name": "Adegaon", "survey_nos": ["112/1", "112/2", "118"], "area_ha": "7.2100"},
                {"name": "Bhoma", "survey_nos": ["57", "58/2"], "area_ha": "6.0300"},
                {"name": "Chhapara", "survey_nos": ["203/1"], "area_ha": "5.4000"},
            ],
            "source_url": "https://egazette.gov.in (seeded copy)",
        }, document_id=doc_3a)
        _append(db, case1, lao, "OBJECTION_RECEIVED", date(2025, 10, 9),
                {"count": 14, "channel": "written"})
        _append(db, case1, lao, "OBJECTIONS_DISPOSED", date(2025, 12, 2), {"disposed": 14})
        _add_parcels(db, case1, [
            ("Adegaon", "484330", "112/1", 2.85, 79.552, 22.085, "notified"),
            ("Adegaon", "484330", "112/2", 2.10, 79.557, 22.085, "notified"),
            ("Adegaon", "484330", "118", 2.26, 79.552, 22.089, "notified"),
            ("Bhoma", "484351", "57", 3.40, 79.601, 22.121, "notified"),
            ("Bhoma", "484351", "58/2", 2.63, 79.606, 22.121, "notified"),
            ("Chhapara", "484372", "203/1", 5.40, 79.640, 22.158, "notified"),
        ])

        # ---------- Case 2: full lifecycle → dashboards/compensation ----------
        case2 = Case(project_id=nh_project.id, district_id=seoni.id, case_no="LAQ/SEO/2024/07",
                     statute_track="NH_ACT_1956", ruleset_version="2026.09")
        db.add(case2)
        db.flush()
        _append(db, case2, lao, "NOTIFICATION_3A", date(2024, 6, 14), {
            "gazette_no": "S.O. 2599(E)", "total_area_ha": "12.9000",
            "villages": [{"name": "Kahani", "survey_nos": ["41", "42/1", "44"], "area_ha": "12.9000"}],
        })
        parcels2 = _add_parcels(db, case2, [
            ("Kahani", "484391", "41", 4.90, 79.512, 22.052, "possessed"),
            ("Kahani", "484391", "42/1", 3.80, 79.517, 22.052, "possessed"),
            ("Kahani", "484391", "44", 4.20, 79.512, 22.056, "possessed"),
        ])
        _append(db, case2, lao, "DECLARATION_3D", date(2025, 2, 10),
                {"gazette_no": "S.O. 655(E)", "total_area_ha": "12.9000"})

        # R&R census (module F). Recorded in the DECLARED window, where the rule-set
        # permits enumeration; the entitlements are delivered after possession, below.
        families2 = _seed_families(db, case2, lao, [
            {"head": {"name": "Ramesh Prasad Yadav", "guardian": "Shivlal Yadav",
                      "id_ref_last4": "4417", "bank_ref_last4": "9032", "village": "Kahani"},
             "category": "agricultural landowner", "displaced": True, "sc_st": False,
             "on": date(2025, 6, 9)},
            {"head": {"name": "Sunita Bai Uikey", "guardian": "Ratanlal Uikey",
                      "id_ref_last4": "7781", "bank_ref_last4": "2264", "village": "Kahani"},
             "category": "agricultural landowner", "displaced": True, "sc_st": True,
             "on": date(2025, 6, 9)},
            {"head": {"name": "Mohan Lal Sahu", "guardian": "Bhagwandas Sahu",
                      "id_ref_last4": "1195", "bank_ref_last4": "5518", "village": "Kahani"},
             "category": "petty shopkeeper", "displaced": False, "sc_st": False,
             "on": date(2025, 6, 23)},
            {"head": {"name": "Phoolwati Dhurve", "guardian": "Sukhram Dhurve",
                      "id_ref_last4": "3620", "bank_ref_last4": "8874", "village": "Kahani"},
             "category": "agricultural labourer", "displaced": False, "sc_st": True,
             "on": date(2025, 6, 23)},
        ])

        _append(db, case2, lao, "AWARD_3G", date(2025, 11, 5),
                {"award_no": "CALA/SEO/2025/19"})

        # compensation: MV*F + assets; solatium 100%; 12% interest 3A→award (First Schedule)
        from app.models import CompensationLine

        assessed_total = 0
        for i, (p, mv) in enumerate(zip(parcels2, [5_20_00_000_00, 4_10_00_000_00, 4_45_00_000_00])):
            base = int(mv * 1.5) + 25_00_000_00           # factor 1.5 rural + assets
            solatium = base
            interest = int(mv * 0.12 * (510 / 365))        # 3A → award ≈ 510 days
            total = base + solatium + interest
            assessed_total += total
            db.add(CompensationLine(
                case_id=case2.id, parcel_id=p.id, owner_ref=f"OWN-{i + 1:03d}",
                market_value_paise=mv, mv_method="s.26(1)(b) sale-deed average", factor=1.5,
                assets_paise=25_00_000_00, base_paise=base, solatium_paise=solatium,
                interest_paise=interest, total_paise=total, paid_paise=total,
            ))
        _append(db, case2, lao, "COMPENSATION_ASSESSED", date(2025, 11, 5),
                {"assessed_total_paise": assessed_total, "line_count": 3})
        # Three instalments that add up to the award *exactly*. The last one is the
        # remainder, not a rounded fraction: truncating each instalment left the case a
        # few paise short of the assessed total, and the s.38 gate — which now reads the
        # paise and nothing else — would refuse possession on a fully settled award.
        paid_so_far = 0
        instalments = [(date(2025, 12, 12), 0.4, "PFMS/2025/88121"),
                       (date(2026, 1, 9), 0.35, "PFMS/2026/00944"),
                       (date(2026, 1, 28), None, "PFMS/2026/02611")]
        for pay_date, frac, ref in instalments:
            amount = assessed_total - paid_so_far if frac is None else int(assessed_total * frac)
            paid_so_far += amount
            _append(db, case2, lao, "PAYMENT_MADE", pay_date,
                    {"pfms_ref": ref, "amount_paise": amount, "mode": "PFMS"})
        assert paid_so_far == assessed_total, "seed case 2 must be paid to the paise"
        _append(db, case2, lao, "COMPENSATION_PAID_FULL", date(2026, 1, 28), {})
        _append(db, case2, lao, "POSSESSION_3E", date(2026, 2, 20),
                {"memo_no": "POSS/SEO/2026/04"})

        # R&R delivery after possession — the s.38(1) heads the two displaced families
        # have actually received. `land_for_land` stays due (this is a highway, not an
        # irrigation project) and so does whatever the household has not chosen yet, so
        # the screen shows a real mix rather than a wall of green.
        _seed_deliveries(db, case2, lao, families2[0], [
            "house", "subsistence_allowance", "transportation_allowance",
            "resettlement_allowance", "cattle_shed_grant", "employment",
            "stamp_duty_exemption", "resettlement_infrastructure",
        ], date(2026, 3, 5))
        _seed_deliveries(db, case2, lao, families2[1], [
            "house", "subsistence_allowance", "transportation_allowance",
            "resettlement_allowance", "cattle_shed_grant", "employment",
            "artisan_grant", "stamp_duty_exemption", "resettlement_infrastructure",
        ], date(2026, 3, 12))
        _seed_deliveries(db, case2, lao, families2[2],
                         ["employment", "artisan_grant", "stamp_duty_exemption"],
                         date(2026, 4, 2))
        _seed_deliveries(db, case2, lao, families2[3],
                         ["employment", "stamp_duty_exemption"], date(2026, 4, 16))

        # ---------- Case 3: RFCTLARR, s.19 clock amber, preconditions met ----------
        case3 = Case(project_id=tl_project.id, district_id=balaghat.id, case_no="LAQ/BLG/2025/03",
                     statute_track="RFCTLARR_2013", ruleset_version="2026.09")
        db.add(case3)
        db.flush()
        _append(db, case3, lao, "SIA_NOTIFIED", date(2025, 2, 10), {"agency": "MPSIA Unit"})
        _append(db, case3, lao, "SIA_PUBLIC_HEARING", date(2025, 4, 15), {"venue": "Gram Panchayat Kirnapur"})
        _append(db, case3, lao, "SIA_REPORT_PUBLISHED", date(2025, 6, 1), {})
        _append(db, case3, lao, "EXPERT_GROUP_APPRAISAL", date(2025, 8, 5), {})
        _append(db, case3, lao, "PRELIM_NOTIFICATION_S11", date(2025, 10, 20), {
            "gazette_no": "MP Gazette 812", "total_area_ha": "9.4000",
            "villages": [{"name": "Kirnapur", "survey_nos": ["77/2", "81"], "area_ha": "9.4000"}],
        })
        _add_parcels(db, case3, [
            ("Kirnapur", "486201", "77/2", 5.10, 80.310, 21.702, "notified"),
            ("Kirnapur", "486201", "81", 4.30, 80.315, 21.702, "notified"),
        ])
        # R&R census on the RFCTLARR case: enumerated, nothing delivered yet — the
        # award has not been made, so no Second Schedule head can be due for delivery.
        _seed_families(db, case3, lao, [
            {"head": {"name": "Devilal Marskole", "guardian": "Chhotelal Marskole",
                      "id_ref_last4": "5093", "bank_ref_last4": "1147", "village": "Kirnapur"},
             "category": "agricultural landowner", "displaced": True, "sc_st": True,
             "on": date(2025, 10, 28)},
            {"head": {"name": "Kamla Bai Bisen", "guardian": "Ganesh Prasad Bisen",
                      "id_ref_last4": "8812", "bank_ref_last4": "6605", "village": "Kirnapur"},
             "category": "agricultural landowner", "displaced": True, "sc_st": False,
             "on": date(2025, 10, 28)},
            {"head": {"name": "Anil Kumar Turkar", "guardian": "Rameshwar Turkar",
                      "id_ref_last4": "2340", "bank_ref_last4": "7719", "village": "Kirnapur"},
             "category": "artisan (carpenter)", "displaced": True, "sc_st": False,
             "on": date(2025, 11, 18)},
            {"head": {"name": "Shanti Bai Nagpure", "guardian": "Devraj Nagpure",
                      "id_ref_last4": "6674", "bank_ref_last4": "3358", "village": "Kirnapur"},
             "category": "agricultural labourer", "displaced": False, "sc_st": False,
             "on": date(2025, 11, 18)},
            {"head": {"name": "Jagdish Prasad Rahangdale", "guardian": "Motiram Rahangdale",
                      "id_ref_last4": "9021", "bank_ref_last4": "4486", "village": "Kirnapur"},
             "category": "agricultural landowner", "displaced": False, "sc_st": False,
             "on": date(2025, 12, 15)},
        ])

        _append(db, case3, lao, "RR_SCHEME_DRAFTED_S16", date(2026, 3, 10), {})
        _append(db, case3, lao, "RR_SCHEME_APPROVED_S17", date(2026, 5, 2), {})
        _append(db, case3, lao, "RR_SCHEME_PUBLISHED_S18", date(2026, 6, 15), {})
        _append(db, case3, lao, "COST_DEPOSITED_S19_2", date(2026, 7, 30),
                {"amount_paise": 92_00_00_000_00, "challan": "TR-6/2026/1188"})

        db.commit()

        # evaluate clocks once so alerts exist at first boot
        try:
            from app.core.time import ist_today
            from app.domain.alerts.service import evaluate_case_clocks

            for c in (case1, case2, case3):
                evaluate_case_clocks(db, c, ist_today())
            db.commit()
        except Exception:
            log.exception("seed: initial clock evaluation failed")

    log.info(
        "seed: done — 2 projects, 3 cases, 9 affected families, 6 users (password %s)",
        DEMO_PASSWORD,
    )
