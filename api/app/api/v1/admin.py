"""Admin — Docs/APIs.md §3.12.

GET  /admin/rulesets                     -> tracks, versions, overlays, counts
GET  /admin/rulesets/{track}/{version}   -> the raw YAML, as shipped
GET  /admin/rulesets/diff?base=&overlay= -> unified diff of the two effective rule-sets
GET  /admin/integrations                 -> adapter status; every one of them is `mock`
POST /admin/integrations/{name}/test     -> run that adapter's self-check
GET  /admin/audit                        -> the non-domain audit trail

The rule-set screen is shown on stage: it is the evidence that the statutory timelines
are configuration, not code (Docs/rules.md C3), and the diff is the evidence that a
state variation is a config change and not a fork — `s.10A` appears in the Maharashtra
overlay as an added line, in a diff a reviewer can read.

The integrations list is generated from the live adapter registry
(`app.domain.integrations`), not from a hand-written table: `mode` is whatever the
adapter object says it is, so the screen cannot drift into claiming a `live`
connection that the code does not have. Docs/APIs.md §4 is explicit that we say so
out loud.
"""

from __future__ import annotations

import difflib
import uuid
from datetime import date, datetime, time, timezone

import yaml
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.problems import Problem, not_found
from app.domain.dashboards.scope import scoped_case_ids
from app.domain.integrations import get_adapter, list_adapters
from app.models import AdminAudit, User

router = APIRouter()

AUDIT_ROLES = {"MINISTRY", "AUDITOR", "STATE_REVENUE", "ADMIN", "COLLECTOR"}
# Firing an adapter's self-check is an outbound call, so it is not a read: an
# AUDITOR, who may see everything and change nothing, is deliberately not here.
INTEGRATION_TEST_ROLES = {"MINISTRY", "STATE_REVENUE", "ADMIN", "COLLECTOR"}


def _ruleset_files() -> list[tuple[str, str, object]]:
    """(track, version, path) for every YAML in the rule-set directory.

    `rglob`, not `glob`: overlays live in `rulesets/overlays/`, and a plain glob left
    every overlay with `file: null` and `is_overlay: false` on the admin screen —
    the one screen whose whole job is to show that the state variation is a file.
    """
    from app.domain.rules.loader import rulesets_dir

    out = []
    for path in sorted(rulesets_dir().rglob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            out.append((str(doc.get("track", "")), str(doc.get("version", "")), path))
        except Exception:
            continue
    return out


@router.get("/admin/rulesets")
def list_rulesets_endpoint(user: CurrentUser = Depends(get_current_user)):
    """Loaded tracks with their stage/transition/clock counts, overlays included.

    An overlay is a loaded rule-set like any other — the loader merges it onto its
    base and registers it under its own version — so it appears here as its own
    entry, carrying `base_version` and `overlay_title` for the diff link. Read-only
    and free of case data, so any authenticated role may see it.
    """
    from app.domain.rules.loader import list_rulesets

    files = {(t, v): p for t, v, p in _ruleset_files()}
    items = []
    for rs in sorted(list_rulesets(), key=lambda r: (r.track, r.version)):
        path = files.get((rs.track, rs.version))
        items.append({
            "track": rs.track,
            "version": rs.version,
            "ref": f"{rs.track}@{rs.version}",
            "stages": len(rs.stages),
            "clocks": len(rs.clocks),
            "transitions": len(rs.transitions),
            "stage_names": list(rs.stages.keys()),
            "clock_ids": [c.id for c in rs.clocks],
            "alerts": rs.alerts,
            "file": path.name if path is not None else None,
            # The loader is the authority on what an overlay is, not the file path.
            "is_overlay": rs.base_version is not None,
            "base_version": rs.base_version,
            "overlay_title": rs.overlay_title,
        })
    overlays = [i for i in items if i["is_overlay"]]
    return {"items": items, "count": len(items), "overlay_count": len(overlays)}


def _parse_ruleset_ref(ref: str, field: str):
    """`RFCTLARR_2013@2026.09` -> the loaded rule-set, or a 404."""
    from app.domain.rules.loader import get_ruleset

    text = (ref or "").strip()
    if "@" not in text:
        raise Problem(
            "validation_error",
            "Validation error",
            422,
            f"{field} must be TRACK@VERSION, e.g. RFCTLARR_2013@2026.09",
            errors=[{"field": field, "got": ref}],
        )
    track, _, version = text.partition("@")
    rs = get_ruleset(track.strip().upper(), version.strip())
    if rs is None:
        raise not_found()
    return rs


@router.get("/admin/rulesets/diff")
def diff_rulesets(
    base: str = Query(..., description="TRACK@VERSION, e.g. RFCTLARR_2013@2026.09"),
    overlay: str = Query(..., description="TRACK@VERSION, e.g. RFCTLARR_2013@2026.09-MH"),
    user: CurrentUser = Depends(get_current_user),
):
    """Unified diff of the two *effective* rule-sets — base merged, overlay merged.

    This is the artefact shown on stage for "a state variation is a config change":
    the Maharashtra overlay's s.10A exemption and its Divisional Commissioner rung on
    the escalation ladder show up as added lines in a diff any reviewer can read. It
    diffs the merged documents rather than the two files, because the file only says
    what changed — the merged pair says what each case is actually judged against.

    `text/plain`, so it can be piped, saved, or pasted into a note verbatim.
    """
    from app.domain.rules.loader import effective_yaml

    base_rs = _parse_ruleset_ref(base, "base")
    overlay_rs = _parse_ruleset_ref(overlay, "overlay")
    base_ref = f"{base_rs.track}@{base_rs.version}"
    overlay_ref = f"{overlay_rs.track}@{overlay_rs.version}"
    lines = difflib.unified_diff(
        effective_yaml(base_rs).splitlines(),
        effective_yaml(overlay_rs).splitlines(),
        fromfile=base_ref,
        tofile=overlay_ref,
        lineterm="",
    )
    body = "\n".join(lines)
    if body:
        body += "\n"
    else:
        body = f"# {base_ref} and {overlay_ref} are identical\n"
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Ruleset-Base": base_ref,
            "X-Ruleset-Overlay": overlay_ref,
            # HTTP headers are latin-1; the overlay titles carry em dashes.
            "X-Overlay-Title": (overlay_rs.overlay_title or "")
            .encode("ascii", "replace")
            .decode("ascii"),
        },
    )


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
    """The live adapter registry (Docs/APIs.md §4).

    `mode` and `last_test` are read off the adapter objects themselves, so this list
    cannot describe a connection the process does not have. `last_test` is
    in-process and resets on restart — it records the last time someone pressed the
    button, not a background sync we do not run.
    """
    items = [a.describe() for a in list_adapters()]
    return {
        "items": items,
        "count": len(items),
        "live_count": sum(1 for a in items if a["mode"] == "live"),
        "note": "All adapters are mocks in this build; the interfaces are real.",
    }


@router.post("/admin/integrations/{name}/test")
def test_integration(
    name: str,
    db: Session = Depends(get_db),
    caller: CurrentUser = Depends(get_current_user),
):
    """Run one adapter's self-check and record who ran it.

    A failing dependency is a `200` with `ok: false`, not a `5xx`: showing that
    state is the whole point of the screen. Unknown adapter names are `404` like
    every other missing resource.
    """
    if not caller.has_role(*INTEGRATION_TEST_ROLES):
        raise not_found()
    adapter = get_adapter(name)
    if adapter is None:
        raise not_found()

    result = adapter.test(db)
    try:
        actor = uuid.UUID(str(caller.id))
    except (ValueError, TypeError):
        actor = None
    db.add(AdminAudit(
        user_id=actor,
        action="INTEGRATION_TEST",
        target=adapter.name,
        meta={"ok": result["ok"], "mode": result["mode"], "detail": result["detail"]},
    ))
    db.commit()
    return result


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
    rejections (Docs/Backend.md §2). Statutory history lives in the ledger, not here.

    Scoped by jurisdiction like every other read (Docs/rules.md C6, Docs/APIs.md §1).
    AUDIT_ROLES admits COLLECTOR and STATE_REVENUE, and the unfiltered query made this
    endpoint a nationwide enumeration oracle: it listed the case numbers, case ids and
    family ids of cases the same caller is 404'd from, together with which officer read
    which family's name and why. A row that names no case is a system-level record
    (logins, role changes) and stays national-only.
    """
    if not caller.has_role(*AUDIT_ROLES):
        raise not_found()

    q = select(AdminAudit)
    allowed = scoped_case_ids(db, caller)
    if allowed is not None:
        q = q.where(
            AdminAudit.meta["case_id"].astext.in_([str(cid) for cid in allowed])
        )
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
