"""Rule-set loader — YAML tracks into an in-memory registry.
Cases pin `ruleset_version` at creation; the registry keys on (track, version)."""

import logging
import os
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

    def allowed_event_types(self, stage: str) -> list[str]:
        allowed = list(self.stages.get(stage, []))
        return allowed

    def transition_for(self, event_type: str) -> TransitionSpec | None:
        return self.transitions.get(event_type)


_REGISTRY: dict[tuple[str, str], Ruleset] = {}


def _parse(doc: dict) -> Ruleset:
    stages = {name: (spec or {}).get("on", []) for name, spec in (doc.get("stages") or {}).items()}
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


def load_all_rulesets() -> dict[tuple[str, str], Ruleset]:
    _REGISTRY.clear()
    d = rulesets_dir()
    for f in sorted(d.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            rs = _parse(doc)
            _REGISTRY[(rs.track, rs.version)] = rs
            log.info("loaded ruleset %s@%s from %s", rs.track, rs.version, f.name)
        except Exception:
            log.exception("failed to load ruleset %s", f)
    return _REGISTRY


def get_ruleset(track: str, version: str | None = None) -> Ruleset | None:
    if not _REGISTRY:
        load_all_rulesets()
    if version:
        rs = _REGISTRY.get((track, version))
        if rs:
            return rs
    candidates = [rs for (t, _v), rs in _REGISTRY.items() if t == track]
    if not candidates:
        return None
    return sorted(candidates, key=lambda r: r.version)[-1]


def list_rulesets() -> list[Ruleset]:
    if not _REGISTRY:
        load_all_rulesets()
    return list(_REGISTRY.values())
