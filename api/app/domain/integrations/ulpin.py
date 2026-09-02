"""ULPIN / DILRMP land-record adapter (Docs/APIs.md §4).

Live target: the State Bhulekh / DILRMP record APIs, addressed by ULPIN — the
14-character Unique Land Parcel Identification Number.

The mock answers from the `parcels` table this system already holds, which is the
same table a real lookup would be reconciled against, so the reply shape is the one
the live adapter has to produce. Nothing invented: a parcel we have never seen
returns `found: false` rather than a plausible-looking record.

The owner reference is masked (Docs/rules.md C5). `compensation_lines.owner_ref` is
already pseudonymous — no name, no Aadhaar — but this is the one call that joins a
land record to a person, so it leaves only enough to recognise a record the caller
already holds.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.integrations.base import BaseAdapter, mask_ref, register
from app.models import Case, CompensationLine, OrgUnit, Parcel, Project

# Reserved TLD (RFC 2606): a mock record URL that can never resolve to something
# that pretends to be a real Bhulekh page.
RECORD_URL = "https://bhulekh.example.invalid/ulpin/{ulpin}"


class UlpinAdapter(BaseAdapter):
    name = "ulpin"
    title = "ULPIN / DILRMP land records"
    mode = "mock"
    interface = "lookup(ulpin); by_survey(state, district, village, survey_no)"
    real_target = "State Bhulekh / DILRMP APIs via ULPIN"
    mock_behaviour = "answers from the seeded parcels table; owner reference masked"

    # --- reads --------------------------------------------------------------------

    def lookup(self, db: Session, ulpin: str) -> dict:
        """`{found, ulpin, owner_ref_masked, area_ha, village_lgd, record_url, ...}`."""
        key = (ulpin or "").strip()
        if not key:
            return {"found": False, "ulpin": ulpin, "detail": "no ULPIN supplied"}
        parcel = db.scalars(
            select(Parcel).where(func.upper(Parcel.ulpin) == key.upper()).limit(1)
        ).first()
        if parcel is None:
            return {
                "found": False,
                "ulpin": key,
                "detail": "no parcel with that ULPIN in the land-record fixture",
            }
        return self._record(db, parcel)

    def by_survey(
        self,
        db: Session,
        state: str | None = None,
        district: str | None = None,
        village: str | None = None,
        survey_no: str | None = None,
    ) -> dict:
        """Records matching whichever of the four keys were supplied.

        Every supplied key narrows the query; `matched_on` reports which ones were
        actually applied, so a caller can never mistake "we ignored your district"
        for "your district matched".
        """
        q = select(Parcel).join(Case, Case.id == Parcel.case_id)
        matched_on: list[str] = []
        if state:
            q = q.join(Project, Project.id == Case.project_id).where(
                func.upper(Project.state_code) == state.strip().upper()
            )
            matched_on.append("state")
        if district:
            q = q.join(OrgUnit, OrgUnit.id == Case.district_id).where(
                (OrgUnit.lgd_code == district.strip())
                | (func.lower(OrgUnit.name) == district.strip().lower())
            )
            matched_on.append("district")
        if village:
            q = q.where(
                (Parcel.village_lgd == village.strip())
                | (func.lower(Parcel.village_name) == village.strip().lower())
            )
            matched_on.append("village")
        if survey_no:
            q = q.where(func.lower(Parcel.survey_no) == survey_no.strip().lower())
            matched_on.append("survey_no")

        rows = db.scalars(
            q.order_by(Parcel.village_name.asc(), Parcel.survey_no.asc()).limit(100)
        ).all()
        return {
            "items": [self._record(db, p) for p in rows],
            "count": len(rows),
            "matched_on": matched_on,
        }

    # --- internals ----------------------------------------------------------------

    def _record(self, db: Session, parcel: Parcel) -> dict:
        owner_ref = db.scalar(
            select(CompensationLine.owner_ref)
            .where(CompensationLine.parcel_id == parcel.id)
            .where(CompensationLine.owner_ref.is_not(None))
            .limit(1)
        )
        return {
            "found": True,
            "ulpin": parcel.ulpin,
            "owner_ref_masked": mask_ref(owner_ref),
            "owner_known": owner_ref is not None,
            "area_ha": float(parcel.area_ha) if parcel.area_ha is not None else None,
            "village_lgd": parcel.village_lgd,
            "village_name": parcel.village_name,
            "survey_no": parcel.survey_no,
            "land_type": parcel.land_type,
            "status": parcel.status,
            "case_id": str(parcel.case_id),
            "parcel_id": str(parcel.id),
            "record_url": RECORD_URL.format(ulpin=parcel.ulpin or ""),
            "source": "mock: bhuarjan parcels table",
        }

    def _test(self, db: Session | None = None) -> dict:
        if db is None:
            return {"ok": False, "detail": "no database session supplied"}
        total = db.scalar(select(func.count()).select_from(Parcel)) or 0
        with_ulpin = (
            db.scalar(
                select(func.count()).select_from(Parcel).where(Parcel.ulpin.is_not(None))
            )
            or 0
        )
        return {
            "ok": True,
            "detail": (
                f"mock fixture readable: {with_ulpin} of {total} parcels carry a ULPIN"
            ),
            "parcels": int(total),
            "with_ulpin": int(with_ulpin),
        }


adapter = register(UlpinAdapter())
