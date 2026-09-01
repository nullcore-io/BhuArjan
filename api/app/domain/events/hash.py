"""Per-case tamper-evident hash chain (Docs/Backend.md §4).

    hash = sha256( prev_hash || canonical_json(event) )

`canonical_json` is JSON over exactly seven fields, sorted keys, no whitespace. Anything
else about the row (seq, recorded_at, idempotency_key) is outside the chain on purpose:
it is system bookkeeping, not the legal record.
"""

import hashlib
import json
from typing import Any, Iterable

CANONICAL_FIELDS: tuple[str, ...] = (
    "id",
    "case_id",
    "type",
    "occurred_at",
    "actor_id",
    "payload",
    "document_id",
)


def canonical_json(event: dict) -> bytes:
    """Canonical byte form of an event. `default=str` renders uuid/date deterministically."""
    return json.dumps(
        {k: event[k] for k in CANONICAL_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()


def compute_hash(prev_hash: bytes | None, event: dict) -> bytes:
    return hashlib.sha256((prev_hash or b"") + canonical_json(event)).digest()


def event_fields(ev: Any) -> dict:
    """Extract the seven chained fields from an Event ORM row (or anything with them)."""
    return {
        "id": ev.id,
        "case_id": ev.case_id,
        "type": ev.type,
        "occurred_at": ev.occurred_at,
        "actor_id": ev.actor_id,
        "payload": ev.payload,
        "document_id": ev.document_id,
    }


def verify_chain(events: Iterable[Any]) -> dict:
    """Recompute a case chain from stored rows, in seq order.

    Returns {verified, head_hash (hex|None), events_checked, first_bad_seq, reason}.
    """
    prev: bytes | None = None
    head: bytes | None = None
    checked = 0
    for ev in events:
        expected = compute_hash(prev, event_fields(ev))
        stored_prev = ev.prev_hash or None
        if (stored_prev or None) != (prev or None):
            return {
                "verified": False,
                "head_hash": head.hex() if head else None,
                "events_checked": checked,
                "first_bad_seq": ev.seq,
                "reason": "prev_hash does not match the previous event's hash",
            }
        if bytes(ev.hash) != expected:
            return {
                "verified": False,
                "head_hash": head.hex() if head else None,
                "events_checked": checked,
                "first_bad_seq": ev.seq,
                "reason": "recomputed hash does not match the stored hash",
            }
        prev = bytes(ev.hash)
        head = prev
        checked += 1
    return {
        "verified": True,
        "head_hash": head.hex() if head else None,
        "events_checked": checked,
        "first_bad_seq": None,
        "reason": None,
    }


def to_hex(b: bytes | None) -> str | None:
    return bytes(b).hex() if b else None
