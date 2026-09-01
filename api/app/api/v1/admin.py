"""Admin — Docs/APIs.md §3.12.

GET /admin/rulesets                     -> tracks, versions, stage/clock counts
GET /admin/rulesets/{track}/{version}   -> the raw YAML, as shipped
GET /admin/integrations                 -> adapter status; every one of them is `mock`
GET /admin/audit                        -> the non-domain audit trail

The rule-set screen is shown on stage: it is the evidence that the statutory timelines
are configuration, not code (Docs/rules.md C3). The integrations list says `mock`
truthfully — Docs/APIs.md §4 is explicit that we say so out loud.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone

import yaml
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.problems import not_found
from app.models import AdminAudit, User

router = APIRouter()

AUDIT_ROLES = {"MINISTRY", "AUDITOR", "STATE_REVENUE", "ADMIN", "COLLECTOR"}

# Docs/APIs.md §4. Every adapter is a mock in this build; `live` requires the real
# endpoint plus credentials, which the offline demo laptop does not have.
INTEGRATIONS = [
    {
        "name": "ulpin",
        "title": "ULPIN / DILRMP land records",
        "mode": "mock",
        "interface": "lookup(ulpin); by_survey(state, district, village, survey_no)",
        "real_target": "State Bhulekh / DILRMP APIs via ULPIN",
        "mock_behaviour": "fixture table for the seeded villages",
    },
    {
        "name": "pfms",
        "title": "PFMS payments",
        "mode": "mock",
        "interface": "payment_status(pfms_ref); list_payments(case_ref)",
        "real_target": "PFMS APIs",
        "mock_behaviour": "fixture statuses; PAID after 2 minutes in demo",
    },
    {
        "name": "gazette",
        "title": "e-Gazette notifications",
        "mode": "mock",
        "interface": "search(statute, section, from, to, state); fetch(ref)",
        "real_target": "egazette.gov.in",
        "mock_behaviour": "local cache of scraped and synthetic PDFs",
    },
    {
        "name": "digilocker",
        "title": "DigiLocker / eSign",
        "mode": "mock",
        "interface": "issue(document_id); esign(document_id, signer)",
        "real_target": "DigiLocker / eSign (CDAC)",
        "mock_behaviour": "stamps a watermark",
    },
    {
        "name": "gatishakti",
        "title": "PM Gati Shakti NMP",
        "mode": "mock",
        "interface": "export(project_id)",
        "real_target": "PM Gati Shakti National Master Plan",
        "mock_behaviour": "writes GeoJSON to MinIO with a public URL",
    },
    {
        "name": "notify",
        "title": "Notification gateway",
        "mode": "mock",
        "interface": "send(channel, to, template, vars)",
        "real_target": "DLT-registered SMS, SMTP, push",
        "mock_behaviour": "console + in-app",
    },
]


def _ruleset_files() -> list[tuple[str, str, object]]:
    """(track, version, path) for every YAML in the rule-set directory."""
    from app.domain.rules.loader import rulesets_dir

    out = []
    for path in sorted(rulesets_dir().glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            out.append((str(doc.get("track", "")), str(doc.get("version", "")), path))
        except Exception:
            continue
    return out


@router.get("/admin/rulesets")
def list_rulesets_endpoint(user: CurrentUser = Depends(get_current_user)):
    """Loaded tracks with their stage/transition/clock counts. Read-only and free of
    case data, so any authenticated role may see it."""
    from app.domain.rules.loader import list_rulesets

    files = {(t, v): p for t, v, p in _ruleset_files()}
    items = []
    for rs in sorted(list_rulesets(), key=lambda r: (r.track, r.version)):
        path = files.get((rs.track, rs.version))
        items.append({
            "track": rs.track,
            "version": rs.version,
            "stages": len(rs.stages),
            "clocks": len(rs.clocks),
            "transitions": len(rs.transitions),
            "stage_names": list(rs.stages.keys()),
            "clock_ids": [c.id for c in rs.clocks],
            "alerts": rs.alerts,
            "file": path.name if path is not None else None,
            "is_overlay": bool(path is not None and "overlay" in str(path).lower()),
        })
    return {"items": items, "count": len(items)}


@router.get("/admin/rulesets/{track}/{version}")
def get_ruleset_yaml(
    track: str,
    version: str,
    user: CurrentUser = Depends(get_current_user),
):
    """The YAML exactly as it ships — this is the artefact an NIC reviewer reads."""
    for t, v, path in _ruleset_files():
        if t.upper() == track.strip().upper() and v == version.strip():
            return Response(
                content=path.read_text(encoding="utf-8"),
                media_type="text/yaml; charset=utf-8",
                headers={"X-Ruleset": f"{t}@{v}"},
            )
    raise not_found()


@router.get("/admin/integrations")
def list_integrations(user: CurrentUser = Depends(get_current_user)):
    return {
        "items": INTEGRATIONS,
        "count": len(INTEGRATIONS),
        "live_count": sum(1 for a in INTEGRATIONS if a["mode"] == "live"),
        "note": "All adapters are mocks in this build; interfaces are real.",
    }


@router.get("/admin/audit")
def list_audit(
    user_id: str | None = Query(None, alias="user"),
    action: str | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    caller: CurrentUser = Depends(get_current_user),
):
    """Non-domain audit: logins, role changes, PII reads, alert acks, extraction
    rejections (Docs/Backend.md §2). Statutory history lives in the ledger, not here."""
    if not caller.has_role(*AUDIT_ROLES):
        raise not_found()

    q = select(AdminAudit)
    if user_id:
        try:
            q = q.where(AdminAudit.user_id == uuid.UUID(str(user_id)))
        except (ValueError, TypeError):
            raise not_found()
    if action:
        q = q.where(AdminAudit.action == action.strip().upper())
    if date_from:
        q = q.where(AdminAudit.at >= datetime.combine(date_from, time.min, timezone.utc))
    if date_to:
        q = q.where(AdminAudit.at <= datetime.combine(date_to, time.max, timezone.utc))

    rows = db.scalars(
        q.order_by(AdminAudit.seq.desc()).offset(offset).limit(limit)
    ).all()
    names = {
        u.id: u.name
        for u in db.scalars(
            select(User).where(User.id.in_([r.user_id for r in rows if r.user_id]))
        ).all()
    } if rows else {}

    return {
        "items": [
            {
                "seq": r.seq,
                "at": r.at.isoformat() if r.at else None,
                "user_id": str(r.user_id) if r.user_id else None,
                "user_name": names.get(r.user_id),
                "action": r.action,
                "target": r.target,
                "meta": r.meta,
            }
            for r in rows
        ],
        "next_offset": offset + len(rows) if len(rows) == limit else None,
    }
