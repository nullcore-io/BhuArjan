"""Rule-set loader — YAML tracks into an in-memory registry.
Cases pin `ruleset_version` at creation; the registry keys on (track, version)."""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.core.config import settings

log = logging.getLogger(__name__)


@dataclass
class ClockSpec:
    id: str
    starts_on: str
    duration: dict
    ends_on: str | None = None
    basis: str = ""
    consequence: str = ""
    kind: str = "deadline"  # deadline | window
    extendable: dict | None = None
    suspend_on: list[str] = field(default_factory=list)
    resume_on: list[str] = field(default_factory=list)
    on_breach: dict | None = None


@dataclass
class TransitionSpec:
    event_type: str
    from_stages: list[str]
    to_stage: str
    section: str = ""
    requires: list[str] = field(default_factory=list)
    guard: str | None = None


@dataclass
class Ruleset:
    track: str
    version: str
    stages: dict[str, list[str]]  # stage -> allowed event types while in stage
    transitions: dict[str, TransitionSpec]  # event type -> spec
    clocks: list[ClockSpec]
    alerts: dict
    raw: dict
    base_version: str | None = None  # set when this ruleset is an overlay on a base
    overlay_title: str | None = None

    def allowed_event_types(self, stage: str) -> list[str]:
        allowed = list(self.stages.get(stage, []))
        return allowed

    def transition_for(self, event_type: str) -> TransitionSpec | None:
        return self.transitions.get(event_type)


_REGISTRY: dict[tuple[str, str], Ruleset] = {}

_VERSION_CHUNK = re.compile(r"(\d+)")


def version_sort_key(version: str) -> tuple:
    """Natural order for rule-set versions: `2026.9` sorts *before* `2026.10`.

    The plain string sort this replaced ranked `2026.9` above `2026.10`, so the tenth
    revision of a track would never become the "whatever is current" answer that project
    creation lands on — new projects would keep being filed under the older rule-set
    while the newer one sat in `rulesets/` looking loaded. Digit runs compare
    numerically; whatever separates them compares as text. Every element is the same
    3-tuple shape so a version that mixes digits and letters can never raise on
    comparison.
    """
    return tuple(
        (1, int(chunk), "") if chunk.isdigit() else (0, 0, chunk)
        for chunk in _VERSION_CHUNK.split(str(version))
        if chunk
    )


def _stage_on(spec) -> list[str]:
    """The `on:` list of a stage.

    YAML 1.1 (which PyYAML implements) resolves a bare `on` to the boolean `True`, so
    `{ on: [...] }` arrives keyed by `True`, not `"on"`. Quoting the key in every
    rule-set would work but would make the YAML worse to read for the officer who has
    to review it — so both spellings are accepted here instead.
    """
    spec = spec or {}
    if not isinstance(spec, dict):
        return []
    value = spec.get("on", spec.get(True, []))
    if isinstance(value, str):
        return [value]
    return list(value or [])


def _parse(doc: dict) -> Ruleset:
    stages = {name: _stage_on(spec) for name, spec in (doc.get("stages") or {}).items()}
    transitions: dict[str, TransitionSpec] = {}
    for ev, spec in (doc.get("transitions") or {}).items():
        spec = spec or {}
        frm = spec.get("from", [])
        if isinstance(frm, str):
            frm = [frm]
        transitions[ev] = TransitionSpec(
            event_type=ev,
            from_stages=frm,
            to_stage=spec.get("to", ""),
            section=spec.get("section", ""),
            requires=spec.get("requires", []) or [],
            guard=spec.get("guard"),
        )
    clocks = []
    for c in doc.get("clocks") or []:
        clocks.append(
            ClockSpec(
                id=c["id"],
                starts_on=c["starts_on"],
                ends_on=c.get("ends_on"),
                duration=c.get("duration", {}),
                basis=c.get("basis", ""),
                consequence=c.get("consequence", ""),
                kind=c.get("kind", "deadline"),
                extendable=c.get("extendable"),
                suspend_on=c.get("suspend_on", []) or [],
                resume_on=c.get("resume_on", []) or [],
                on_breach=c.get("on_breach"),
            )
        )
    return Ruleset(
        track=doc["track"],
        version=str(doc["version"]),
        stages=stages,
        transitions=transitions,
        clocks=clocks,
        alerts=doc.get("alerts", {}),
        raw=doc,
    )


def rulesets_dir() -> Path:
    p = Path(settings.RULESETS_DIR)
    if not p.is_absolute():
        p = Path(os.getcwd()) / p
    return p


def _merge_overlay(base_doc: dict, overlay_doc: dict) -> dict:
    """Base + overlay -> effective document (Docs/Backend.md §5: keys override or add).

    stages: per-stage replace; transitions: per-event replace; clocks: replace by id,
    append new ids; alerts: per-key replace one level down (thresholds/escalation).
    """
    merged = dict(base_doc)
    merged["version"] = str(overlay_doc["version"])
    for section in ("stages", "transitions"):
        eff = dict(base_doc.get(section) or {})
        eff.update(overlay_doc.get(section) or {})
        merged[section] = eff
    if overlay_doc.get("clocks"):
        by_id = {c["id"]: c for c in (base_doc.get("clocks") or [])}
        for c in overlay_doc["clocks"]:
            by_id[c["id"]] = {**by_id.get(c["id"], {}), **c}
        merged["clocks"] = list(by_id.values())
    if overlay_doc.get("alerts"):
        eff_alerts = {k: dict(v) if isinstance(v, dict) else v
                      for k, v in (base_doc.get("alerts") or {}).items()}
        for k, v in overlay_doc["alerts"].items():
            if isinstance(v, dict) and isinstance(eff_alerts.get(k), dict):
                eff_alerts[k].update(v)
            else:
                eff_alerts[k] = v
        merged["alerts"] = eff_alerts
    return merged


def _normalise_doc(doc: dict) -> dict:
    """Undo YAML 1.1's `on` -> True key resolution in the raw document so the
    effective YAML (admin diff viewer) reads `on:` like the file the officer wrote,
    and stringify the version so `'2026.09'` and `2026.09` never diff against each other."""
    if not isinstance(doc, dict):
        return doc
    if "version" in doc:
        doc["version"] = str(doc["version"])
    if "base_version" in doc:
        doc["base_version"] = str(doc["base_version"])
    for name, spec in (doc.get("stages") or {}).items():
        if isinstance(spec, dict) and True in spec and "on" not in spec:
            spec["on"] = spec.pop(True)
    return doc


def load_all_rulesets() -> dict[tuple[str, str], Ruleset]:
    _REGISTRY.clear()
    d = rulesets_dir()
    docs: list[tuple[dict, str]] = []
    for f in sorted(d.rglob("*.yaml")):
        try:
            docs.append((_normalise_doc(yaml.safe_load(f.read_text(encoding="utf-8"))), f.name))
        except Exception:
            log.exception("failed to read ruleset %s", f)
    # Two passes: bases first, then overlays — file order must not matter.
    for doc, name in docs:
        if doc.get("overlay"):
            continue
        try:
            rs = _parse(doc)
            _REGISTRY[(rs.track, rs.version)] = rs
            log.info("loaded ruleset %s@%s from %s", rs.track, rs.version, name)
        except Exception:
            log.exception("failed to load ruleset %s", name)
    for doc, name in docs:
        if not doc.get("overlay"):
            continue
        try:
            base = _REGISTRY.get((doc["track"], str(doc["base_version"])))
            if base is None:
                log.error("overlay %s: base %s@%s not loaded", name, doc.get("track"),
                          doc.get("base_version"))
                continue
            rs = _parse(_merge_overlay(base.raw, doc))
            rs.base_version = str(doc["base_version"])
            rs.overlay_title = doc.get("title")
            _REGISTRY[(rs.track, rs.version)] = rs
            log.info("loaded overlay %s@%s (base %s) from %s", rs.track, rs.version,
                     rs.base_version, name)
        except Exception:
            log.exception("failed to load overlay %s", name)
    return _REGISTRY


def effective_yaml(rs: Ruleset) -> str:
    """The merged document as YAML — what the admin diff viewer compares."""
    return yaml.safe_dump(rs.raw, sort_keys=False, allow_unicode=True)


def get_ruleset(track: str, version: str | None = None) -> Ruleset | None:
    """The rule-set for `track`, pinned to `version` when one is given.

    A pin that is not loaded returns None — it never falls back to the newest version
    of the track. Falling back re-evaluated live cases against rules they were not
    filed under, which is exactly what pinning exists to prevent: a dropped-in
    `rfctlarr_2027.yaml`, or a YAML typo that makes `load_all_rulesets` skip the
    pinned file, would have silently recomputed every clock from new durations.
    Callers that want "whatever is current" (project creation) pass no version; "newest"
    is decided by `version_sort_key`, not by a string sort.
    """
    if not _REGISTRY:
        load_all_rulesets()
    if version:
        return _REGISTRY.get((track, version))
    # No pin -> the current BASE ruleset. Overlays are opt-in per case, never the
    # default a new project silently lands on.
    candidates = [
        rs for (t, _v), rs in _REGISTRY.items() if t == track and rs.base_version is None
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: version_sort_key(r.version))[-1]


def list_rulesets() -> list[Ruleset]:
    if not _REGISTRY:
        load_all_rulesets()
    return list(_REGISTRY.values())
