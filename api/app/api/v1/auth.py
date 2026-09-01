"""Auth — Docs/APIs.md §3.1.

POST /auth/token   {username, password} -> {access_token, expires_in}
GET  /auth/me      -> {id, name, roles[], scopes[]}

Password login is the development path the demo runs on; production is OIDC
(Docs/Backend.md §10), which mints the same claims: `sub`, `roles[]`, `scopes[]`.
`scopes` are org-unit ids as strings — the jurisdiction every read is filtered by
server-side, never by the client.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.problems import Problem
from app.core.security import create_token, verify_password
from app.models import AdminAudit, OrgUnit, RoleAssignment, User

router = APIRouter()


class TokenIn(BaseModel):
    username: str
    password: str


def roles_and_scopes(db: Session, user_id: uuid.UUID) -> tuple[list[str], list[str]]:
    rows = db.execute(
        select(RoleAssignment.role, RoleAssignment.org_unit_id).where(
            RoleAssignment.user_id == user_id
        )
    ).all()
    roles: list[str] = []
    scopes: list[str] = []
    for role, org_unit_id in rows:
        if role and role not in roles:
            roles.append(role)
        if org_unit_id is not None and str(org_unit_id) not in scopes:
            scopes.append(str(org_unit_id))
    return roles, scopes


def _unauthenticated() -> Problem:
    # Deliberately one message for "no such user" and "wrong password": the login
    # form must not be an account-enumeration oracle.
    return Problem(
        "unauthenticated", "Unauthenticated", 401, "invalid username or password"
    )


@router.post("/auth/token")
def issue_token(body: TokenIn, db: Session = Depends(get_db)):
    username = (body.username or "").strip()
    if not username or not body.password:
        raise _unauthenticated()

    user = db.scalar(select(User).where(func.lower(User.email) == username.lower()))
    if user is None or not user.active:
        raise _unauthenticated()
    if not verify_password(body.password, user.password_hash or ""):
        raise _unauthenticated()

    roles, scopes = roles_and_scopes(db, user.id)
    token = create_token(str(user.id), user.name or user.email, roles, scopes)
    db.add(
        AdminAudit(
            user_id=user.id,
            action="LOGIN",
            target=user.email,
            meta={"roles": roles, "scopes": scopes},
        )
    )
    db.commit()
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.JWT_EXPIRE_MINUTES * 60,
        "user": {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "roles": roles,
            "scopes": scopes,
        },
    }


@router.get("/auth/me")
def me(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Claims, re-read from the database so a revoked role does not survive in a
    token that has not expired yet."""
    try:
        user_id = uuid.UUID(user.id)
    except (ValueError, TypeError):
        raise Problem("unauthenticated", "Unauthenticated", 401, "malformed subject")

    row = db.get(User, user_id)
    if row is None or not row.active:
        raise Problem("unauthenticated", "Unauthenticated", 401, "user is not active")

    roles, scopes = roles_and_scopes(db, user_id)
    units = (
        db.scalars(
            select(OrgUnit).where(
                OrgUnit.id.in_([uuid.UUID(s) for s in scopes])
            )
        ).all()
        if scopes
        else []
    )
    return {
        "id": str(row.id),
        "name": row.name,
        "email": row.email,
        "roles": roles,
        "scopes": scopes,
        "jurisdiction": [
            {"id": str(u.id), "kind": u.kind, "name": u.name, "lgd_code": u.lgd_code}
            for u in units
        ],
        "demo_mode": settings.DEMO_MODE,
    }
