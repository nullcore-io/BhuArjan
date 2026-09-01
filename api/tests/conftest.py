"""Test harness — real PostgreSQL + PostGIS, in a dedicated schema.

These are not unit tests with a fake database. The clock engine does calendar-month
arithmetic, the ledger takes a row lock, and the parcels table is PostGIS; a SQLite
stand-in would prove nothing about any of it. So the suite runs against the same
server the demo runs on (localhost:5433), inside its own schema `test_b1`, which is
dropped and recreated at the start of every session. The `public` schema — the demo
database — is never touched.

The schema is created and the environment is pointed at it *before* `app.core.config`
is imported, because the engine is built from `settings.DATABASE_URL` at import time.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

API_DIR = Path(__file__).resolve().parents[1]
TEST_SCHEMA = "test_b1"
BASE_URL = "postgresql+psycopg://bhuarjan:bhuarjan_dev@localhost:5433/bhuarjan"
SCHEMA_URL = f"{BASE_URL}?options=-csearch_path%3D{TEST_SCHEMA},public"

# --- bootstrap: must run before anything imports app.core.config -------------------

_boot = create_engine(BASE_URL)
with _boot.begin() as _conn:
    _conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    _conn.execute(text(f"CREATE SCHEMA {TEST_SCHEMA}"))
_boot.dispose()

os.environ["DATABASE_URL"] = SCHEMA_URL
os.environ["RULESETS_DIR"] = str(API_DIR / "rulesets")
os.environ["DEMO_MODE"] = "true"
os.environ["SEED_ON_START"] = "false"
os.environ["JWT_SECRET"] = "test-secret"

from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import (  # noqa: E402
    Case,
    CaseState,
    OrgUnit,
    Project,
    RoleAssignment,
    User,
)

TEST_PASSWORD = "test-pass"


@pytest.fixture(scope="session", autouse=True)
def schema():
    assert str(engine.url).find(TEST_SCHEMA) >= 0, "tests must not run on the demo schema"

    # `checkfirst=True` would ask "does `events` exist?", the search_path would answer
    # yes from `public` (the demo database), and every table would be skipped — leaving
    # the whole suite writing into the demo data. The schema was just recreated empty,
    # so the existence check has nothing to tell us: skip it and create unconditionally.
    Base.metadata.create_all(engine, checkfirst=False)

    with engine.connect() as conn:
        for table in ("events", "cases", "clocks", "alerts", "case_state"):
            landed = conn.execute(
                text(
                    "SELECT n.nspname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.oid = cast(:t as regclass)"
                ),
                {"t": table},
            ).scalar()
            assert landed == TEST_SCHEMA, (
                f"'{table}' resolves to schema '{landed}', not '{TEST_SCHEMA}' — "
                "the suite would be writing into the demo database"
            )

    from app.domain.rules.loader import load_all_rulesets

    loaded = load_all_rulesets()
    assert loaded, "no rule-sets loaded; check RULESETS_DIR"
    yield
    engine.dispose()
    drop = create_engine(BASE_URL)
    with drop.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE"))
    drop.dispose()


@pytest.fixture()
def db(schema):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(schema):
    from fastapi.testclient import TestClient

    from app.main import app

    # No lifespan: create_all already ran, and the hourly clock scheduler would only
    # race the tests' own explicit evaluations.
    return TestClient(app)


# --- fixture data ------------------------------------------------------------------


class World:
    """One state, one district, one requiring body, one officer of every rank."""

    def __init__(self, db):
        suffix = uuid.uuid4().hex[:8]
        self.ministry = OrgUnit(kind="ministry", name=f"DoLR {suffix}")
        self.state = OrgUnit(kind="state", name=f"Test State {suffix}", lgd_code=suffix)
        db.add_all([self.ministry, self.state])
        db.flush()
        self.district = OrgUnit(
            kind="district", name=f"Test District {suffix}", parent_id=self.state.id
        )
        self.body = OrgUnit(kind="requiring_body", name=f"Requiring Body {suffix}")
        db.add_all([self.district, self.body])
        db.flush()

        self.lao = self._user(db, f"lao-{suffix}@test", "LAO", self.district.id)
        self.collector = self._user(
            db, f"collector-{suffix}@test", "COLLECTOR", self.district.id
        )
        self.ministry_user = self._user(
            db, f"ministry-{suffix}@test", "MINISTRY", self.ministry.id
        )
        db.commit()

    @staticmethod
    def _user(db, email: str, role: str, org_unit_id) -> User:
        user = User(email=email, name=email, password_hash=hash_password(TEST_PASSWORD))
        db.add(user)
        db.flush()
        db.add(RoleAssignment(user_id=user.id, role=role, org_unit_id=org_unit_id))
        db.flush()
        return user

    def project(self, db, track: str = "RFCTLARR_2013") -> Project:
        project = Project(
            name=f"{track} project",
            sector="Testing",
            requiring_body_id=self.body.id,
            statute_track=track,
            ruleset_version="2026.09",
            state_code="TS",
        )
        db.add(project)
        db.flush()
        return project

    def case(self, db, track: str = "RFCTLARR_2013", case_no: str | None = None) -> Case:
        from app.domain.cases.projections import ensure_case_state

        project = self.project(db, track)
        case = Case(
            project_id=project.id,
            district_id=self.district.id,
            case_no=case_no or f"T/{uuid.uuid4().hex[:6]}",
            statute_track=track,
            ruleset_version=project.ruleset_version,
        )
        db.add(case)
        db.flush()
        ensure_case_state(db, case)
        db.commit()
        return case


@pytest.fixture()
def world(db) -> World:
    return World(db)


@pytest.fixture()
def token(client, world):
    def _token(user: User) -> str:
        res = client.post(
            "/api/v1/auth/token",
            json={"username": user.email, "password": TEST_PASSWORD},
        )
        assert res.status_code == 200, res.text
        return res.json()["access_token"]

    return _token


@pytest.fixture()
def auth(client, world, token):
    """`auth(user, on='2026-01-02')` -> headers with bearer token and demo date."""
    cache: dict[str, str] = {}

    def _auth(user: User | None = None, on: date | str | None = None) -> dict:
        user = user or world.lao
        if user.email not in cache:
            cache[user.email] = token(user)
        headers = {"Authorization": f"Bearer {cache[user.email]}"}
        if on is not None:
            headers["X-Demo-Date"] = on if isinstance(on, str) else on.isoformat()
        return headers

    return _auth


@pytest.fixture()
def record(client, auth, world):
    """Append one event through the API and return (status_code, body)."""

    def _record(
        case: Case,
        event_type: str,
        occurred_at: date,
        payload: dict | None = None,
        *,
        user: User | None = None,
        on: date | str | None = None,
        document_id: str | None = None,
        no_document_reason: str | None = "test fixture; gazette copy not attached",
        idempotency_key: str | None = None,
        if_match: int | None = None,
    ) -> tuple[int, dict]:
        headers = dict(auth(user, on if on is not None else occurred_at))
        headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
        if if_match is not None:
            headers["If-Match"] = str(if_match)
        body: dict = {
            "type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "payload": payload or {},
        }
        if document_id:
            body["document_id"] = document_id
        elif no_document_reason:
            body["no_document_reason"] = no_document_reason
        res = client.post(f"/api/v1/cases/{case.id}/events", json=body, headers=headers)
        return res.status_code, res.json()

    return _record


@pytest.fixture()
def must_record(record):
    """As `record`, but asserts the append succeeded — keeps the walk-up readable."""

    def _must(*args, **kwargs) -> dict:
        status, body = record(*args, **kwargs)
        assert status == 201, f"{args[1]} rejected: {body}"
        return body

    return _must


def stage_of(db, case: Case) -> str:
    db.expire_all()
    state = db.get(CaseState, case.id)
    return state.stage if state else "PROPOSED"
