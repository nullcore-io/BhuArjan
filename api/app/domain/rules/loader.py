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
    # A named predicate (app.domain.rules.predicates) that decides closure from the
    # state of the case rather than from a single event: the R&R clocks close when
    # every family has been served, not when the first delivery is recorded.
    ends_when: str | None = None
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
# The file each registry key was claimed by, so a collision can name both documents.
_SOURCES: dict[tuple[str, str], str] = {}

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

    The raw string is appended as a final tiebreak. Without it `'2026.9'` and
    `'2026.09'` — two distinct registry keys — compared *equal*, so which of them a new
    project landed on was decided by dict iteration order rather than by the rule-set
    directory.
    """
    chunks = tuple(
        (1, int(chunk), "") if chunk.isdigit() else (0, 0, chunk)
        for chunk in _VERSION_CHUNK.split(str(version))
        if chunk
    )
    return chunks + ((1, 0, str(version)),)


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
                ends_when=c.get("ends_when"),
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


def _merge_transitions(base: dict, overlay: dict, name: str) -> dict:
    """Transitions merged **per field**, not per event (Docs/Backend.md §5).

    A whole-value replace meant a state overlay restating a transition only to change
    its `section:` citation silently deleted that transition's `requires:` and `guard:`
    — including the s.38 possession-payment gate, so a case could walk from PROPOSED to
    POSSESSED with nothing assessed and nothing paid. An overlay that does not mention
    a key therefore keeps the base's value for it.

    A key the overlay *does* write still wins, `guard: null` and `requires: []`
    included: removing a gate is a legitimate thing for a State amendment to do, and
    saying so explicitly is how it is done. Because that is the dangerous direction, it
    is logged at WARNING.
    """
    eff = {k: (dict(v) if isinstance(v, dict) else v) for k, v in (base or {}).items()}
    for event_type, spec in (overlay or {}).items():
        current = eff.get(event_type)
        if not isinstance(spec, dict) or not isinstance(current, dict):
            eff[event_type] = spec
            continue
        for field_name in ("guard", "requires"):
            if field_name not in spec:
                continue
            was, now = current.get(field_name), spec.get(field_name)
            if was and not now:
                log.warning(
                    "overlay %s removes %s from transition %s (was %r): the base's "
                    "statutory precondition no longer applies under this rule-set",
                    name, field_name, event_type, was,
                )
        eff[event_type] = {**current, **spec}
    return eff


def _merge_stages(base: dict, overlay: dict, name: str) -> dict:
    """Stages merged per field too, with every event type an overlay drops logged.

    An overlay rewriting a stage's `on:` list is replacing the whole list — that is
    what a list means — but a stage that quietly loses PRELIM_NOTIFICATION_S11 or
    EVENT_REVERSED strands every case sitting in it with no way forward and no way to
    correct the record, and the admin diff renders the loss as an absent line rather
    than as a removal. So the loader says so, once per event type, at WARNING.
    """
    eff = {k: (dict(v) if isinstance(v, dict) else v) for k, v in (base or {}).items()}
    for stage, spec in (overlay or {}).items():
        current = eff.get(stage)
        if not isinstance(spec, dict) or not isinstance(current, dict):
            eff[stage] = spec
            continue
        merged_stage = {**current, **spec}
        dropped = [e for e in _stage_on(current) if e not in _stage_on(merged_stage)]
        for event_type in dropped:
            log.warning(
                "overlay %s removes %s from stage %s: no case in that stage can "
                "record it under this rule-set",
                name, event_type, stage,
            )
        eff[stage] = merged_stage
    return eff


def _merge_overlay(base_doc: dict, overlay_doc: dict, name: str = "overlay") -> dict:
    """Base + overlay -> effective document (Docs/Backend.md §5: keys override or add).

    stages and transitions: per-key merge one level down, so restating a stanza to
    change one field keeps the fields it does not mention; clocks: replace by id,
    append new ids; alerts: per-key replace one level down (thresholds/escalation).
    """
    merged = dict(base_doc)
    merged["version"] = str(overlay_doc["version"])
    merged["stages"] = _merge_stages(
        base_doc.get("stages") or {}, overlay_doc.get("stages") or {}, name
    )
    merged["transitions"] = _merge_transitions(
        base_doc.get("transitions") or {}, overlay_doc.get("transitions") or {}, name
    )
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


def _register(rs: Ruleset, name: str) -> bool:
    """Claim `(track, version)` for this document, or refuse it.

    First file wins. Two documents declaring the same pair used to overwrite each other
    with the winner decided by filename sort order, so copying an overlay to a new
    filename without bumping its version silently changed which rule-set the estate ran
    on — and an overlay whose `version` equalled its `base_version` replaced the base
    itself, which is precisely what pinning exists to prevent (see `get_ruleset`).
    """
    key = (rs.track, rs.version)
    incumbent = _SOURCES.get(key)
    if incumbent is not None:
        log.error(
            "rule-set %s@%s is declared twice: keeping %s, refusing %s — bump the "
            "version in one of them; a rule-set version is an identity, not a label",
            rs.track, rs.version, incumbent, name,
        )
        return False
    _REGISTRY[key] = rs
    _SOURCES[key] = name
    return True


def load_all_rulesets() -> dict[tuple[str, str], Ruleset]:
    _REGISTRY.clear()
    _SOURCES.clear()
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
            if _register(rs, name):
                log.info("loaded ruleset %s@%s from %s", rs.track, rs.version, name)
        except Exception:
            log.exception("failed to load ruleset %s", name)
    for doc, name in docs:
        if not doc.get("overlay"):
            continue
        try:
            base_version = str(doc["base_version"])
            if str(doc["version"]) == base_version:
                # Registering it would replace the base under its own key: every live
                # case pinned to that version would start being judged against a
                # different document, and the track would lose its default rule-set.
                log.error(
                    "overlay %s declares version %s, the same version as its base: an "
                    "overlay must carry a version of its own or it overwrites the "
                    "document it amends — refusing to load it",
                    name, base_version,
                )
                continue
            base = _REGISTRY.get((doc["track"], base_version))
            if base is None:
                log.error("overlay %s: base %s@%s not loaded", name, doc.get("track"),
                          doc.get("base_version"))
                continue
            rs = _parse(_merge_overlay(base.raw, doc, name))
            rs.base_version = base_version
            rs.overlay_title = doc.get("title")
            if _register(rs, name):
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
