"""Jurisdiction scoping (Docs/rules.md C6, Docs/APIs.md §1).

Every read in this lane resolves the caller's org-unit scopes to a concrete set of
case ids first, server-side. Out-of-scope resources are reported as `404`, never
`403`, so the API cannot be used to enumerate cases the caller may not see.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser
from app.models import Case, OrgUnit, Project

# Roles whose jurisdiction is the whole country.
NATIONAL_ROLES = {"MINISTRY", "AUDITOR", "ADMIN"}


def _as_uuid(value) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def expand_org_units(db: Session, roots: list[uuid.UUID]) -> set[uuid.UUID]:
    """A scope on a state covers its districts. Walk the org-unit tree downwards."""
    if not roots:
        return set()
    seen: set[uuid.UUID] = set(roots)
    frontier = list(roots)
    while frontier:
        children = db.scalars(
            select(OrgUnit.id).where(OrgUnit.parent_id.in_(frontier))
        ).all()
        new = [c for c in children if c not in seen]
        seen.update(new)
        frontier = new
    return seen


def is_national(db: Session, user: CurrentUser) -> bool:
    if any(r.upper() in NATIONAL_ROLES for r in user.roles):
        return True
    scope_ids = [u for u in (_as_uuid(s) for s in user.scopes) if u]
    if not scope_ids:
        return True  # no scope claim at all -> national read (demo tokens)
    kinds = db.scalars(select(OrgUnit.kind).where(OrgUnit.id.in_(scope_ids))).all()
    return any(k == "ministry" for k in kinds)


def scoped_case_ids(db: Session, user: CurrentUser) -> list[uuid.UUID] | None:
    """Case ids the caller may read. `None` means unrestricted (national)."""
    if is_national(db, user):
        return None
    scope_ids = [u for u in (_as_uuid(s) for s in user.scopes) if u]
    units = expand_org_units(db, scope_ids)
    if not units:
        return []
    rows = db.execute(
        select(Case.id)
        .join(Project, Project.id == Case.project_id)
        .where(
            Case.district_id.in_(units) | Project.requiring_body_id.in_(units)
        )
    ).all()
    return [r[0] for r in rows]


def case_ids_for_filters(
    db: Session,
    base: list[uuid.UUID] | None,
    *,
    state: str | None = None,
    district: str | None = None,
    sector: str | None = None,
    statute: str | None = None,
) -> list[uuid.UUID]:
    """Narrow a scope (or the whole estate) by the dashboard filters.

    `state` matches `project.state_code`; `district` matches `case.district_id` by
    uuid, LGD code or name (Docs/APIs.md §3.10).
    """
    q = select(Case.id).join(Project, Project.id == Case.project_id)
    if base is not None:
        if not base:
            return []
        q = q.where(Case.id.in_(base))
    if state:
        from sqlalchemy import func

        q = q.where(func.upper(Project.state_code) == state.strip().upper())
    if district:
        district_id = _as_uuid(district)
        if district_id:
            q = q.where(Case.district_id == district_id)
        else:
            from sqlalchemy import func, or_

            q = q.join(OrgUnit, OrgUnit.id == Case.district_id).where(
                or_(
                    OrgUnit.lgd_code == district.strip(),
                    func.lower(OrgUnit.name) == district.strip().lower(),
                )
            )
    if sector:
        q = q.where(Project.sector == sector)
    if statute:
        q = q.where(Project.statute_track == statute)
    return [r[0] for r in db.execute(q).all()]


def require_case(db: Session, case_id, user: CurrentUser) -> Case:
    """Load a case the caller may see, or raise `not_found` (never 403)."""
    from app.core.problems import not_found

    cid = _as_uuid(case_id)
    if cid is None:
        raise not_found()
    case = db.get(Case, cid)
    if case is None:
        raise not_found()
    allowed = scoped_case_ids(db, user)
    if allowed is not None and case.id not in allowed:
        raise not_found()
    return case
