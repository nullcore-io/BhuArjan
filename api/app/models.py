"""All tables. Principle: `events` is the truth; case_state/clocks/alerts are projections
(rebuildable by replay). See Docs/Backend.md §2."""

import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def uid() -> uuid.UUID:
    return uuid.uuid4()


class OrgUnit(Base):
    __tablename__ = "org_units"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(Text)  # ministry|state|district|requiring_body
    name: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org_units.id"), nullable=True)
    lgd_code: Mapped[str | None] = mapped_column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    # A national role (MINISTRY, AUDITOR) has no org unit, and PostgreSQL will not
    # accept a NULL inside a primary key — so the natural triple is a unique index
    # over a surrogate key rather than the primary key itself.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(Text)
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("org_units.id"), nullable=True
    )


Index(
    "uq_role_assignments",
    RoleAssignment.user_id,
    RoleAssignment.role,
    RoleAssignment.org_unit_id,
    unique=True,
    postgresql_nulls_not_distinct=True,
)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)
    requiring_body_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org_units.id"), nullable=True)
    statute_track: Mapped[str] = mapped_column(Text)  # RFCTLARR_2013 | NH_ACT_1956
    ruleset_version: Mapped[str] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"))
    district_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("org_units.id"), nullable=True)
    case_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    statute_track: Mapped[str] = mapped_column(Text)
    ruleset_version: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    __tablename__ = "events"
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, default=uid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"))
    type: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[date] = mapped_column(Date)  # legal date (gazette publication)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    hash: Mapped[bytes] = mapped_column(LargeBinary)


Index("ix_events_case_seq", Event.case_id, Event.seq)
Index("ix_events_case_type", Event.case_id, Event.type)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"), nullable=True)
    kind: Mapped[str] = mapped_column(Text)  # notification_s11|declaration_s19|award|payment|...
    storage_key: Mapped[str] = mapped_column(Text)
    sha256: Mapped[bytes] = mapped_column(LargeBinary)
    mime: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    extraction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extraction_status: Mapped[str] = mapped_column(Text, default="pending")  # pending|proposed|confirmed|rejected


class Parcel(Base):
    __tablename__ = "parcels"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"))
    village_lgd: Mapped[str | None] = mapped_column(Text, nullable=True)
    village_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    survey_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    ulpin: Mapped[str | None] = mapped_column(Text, nullable=True)
    area_ha: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    land_type: Mapped[str | None] = mapped_column(Text, nullable=True)  # rural|urban
    status: Mapped[str] = mapped_column(Text, default="notified")  # notified|awarded|paid|possessed|disputed
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)


class PersonInterested(Base):
    __tablename__ = "persons_interested"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"), nullable=True)
    parcel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parcels.id"), nullable=True)
    pii_enc: Mapped[bytes] = mapped_column(LargeBinary)  # AES-GCM at app layer
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    sc_st: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    consent_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class AffectedFamily(Base):
    __tablename__ = "affected_families"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id"), nullable=True)
    head_person_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("persons_interested.id"), nullable=True)
    displaced: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rr_entitlements: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Set when the FAMILY_ENUMERATED that created this row is reversed. The row itself
    # stays — the ledger recorded that it existed — but it stops being an affected
    # family everywhere: registers, R&R summaries, clock predicates and dashboard
    # counts all exclude it, and its `persons_interested.pii_enc` is erased, because a
    # withdrawn enumeration is exactly the record DPDP says to stop processing
    # (Docs/rules.md C5).
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---- projections (rebuildable) ----

class CaseState(Base):
    __tablename__ = "case_state"
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    stage: Mapped[str] = mapped_column(Text, default="PROPOSED")
    as_of_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    area_notified_ha: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    area_acquired_ha: Mapped[float] = mapped_column(Numeric(14, 4), default=0)
    comp_assessed_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    comp_paid_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    families_affected: Mapped[int] = mapped_column(Integer, default=0)
    families_displaced: Mapped[int] = mapped_column(Integer, default=0)
    possession_pct: Mapped[float] = mapped_column(Numeric(6, 2), default=0)
    risk_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Clock(Base):
    __tablename__ = "clocks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"))
    clock_id: Mapped[str] = mapped_column(Text)  # e.g. AWARD_S23
    basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    consequence: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="running")  # running|closed|extended|suspended|breached|lapsed
    closed_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    suspended_days: Mapped[int] = mapped_column(Integer, default=0)
    # --- clock-engine projection detail (lane B1) ---
    kind: Mapped[str] = mapped_column(Text, default="deadline")  # deadline|window
    extendable: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {by, reasons_required}
    original_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # start + duration
    extended_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # EXTENSION_GRANTED
    stay_started_on: Mapped[date | None] = mapped_column(Date, nullable=True)  # open COURT_STAY
    elapsed_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)


# One row per (case, clock) — the engine upserts on it, and lane B2 relies on the
# uniqueness for ON CONFLICT.
Index("ix_clocks_case", Clock.case_id, Clock.clock_id, unique=True)
Index("ix_clocks_status_due", Clock.status, Clock.due_date)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"))
    clock_id: Mapped[str] = mapped_column(Text)
    level: Mapped[str] = mapped_column(Text)  # amber|red|breached|lapsed
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    escalated_to_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Alerts are deduped per (case, clock, level) by the clock engine.
Index("ix_alerts_case_clock_level", Alert.case_id, Alert.clock_id, Alert.level, unique=True)


class AdminAudit(Base):
    __tablename__ = "admin_audit"
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CompensationLine(Base):
    """Award lines per parcel/owner — First Schedule computation output (Docs/Backend.md §7)."""

    __tablename__ = "compensation_lines"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uid)
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"))
    parcel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parcels.id"), nullable=True)
    owner_ref: Mapped[str | None] = mapped_column(Text, nullable=True)  # masked reference, no PII
    market_value_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    mv_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    factor: Mapped[float] = mapped_column(Numeric(4, 2), default=1)
    assets_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    base_paise: Mapped[int] = mapped_column(BigInteger, default=0)  # T = MV*F + A
    solatium_paise: Mapped[int] = mapped_column(BigInteger, default=0)  # = T (100%)
    interest_paise: Mapped[int] = mapped_column(BigInteger, default=0)  # 12% s.30(3)
    total_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
