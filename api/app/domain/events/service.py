"""Event append service — THE core write. Interface frozen; implementation by build lane B1.

Contract (Docs/Backend.md §4, Docs/APIs.md §3.4):
- One transaction: lock last event hash per case FOR UPDATE → validate transition
  against the pinned ruleset (stage, requires, guard) → insert with prev_hash/hash →
  update case_state projection → evaluate clocks (close/start/extend/suspend) →
  return AppendResult. Idempotency-Key replay returns the original result.
- Raises app.core.problems Problems: transition_not_allowed, precondition_failed,
  guard_failed, document_required, stale_state.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models import Case


@dataclass
class AppendResult:
    seq: int
    id: uuid.UUID
    hash: str  # hex
    prev_hash: str | None  # hex
    stage: str
    clocks_changed: list[dict] = field(default_factory=list)
    duplicate: bool = False  # idempotent replay


def append_event(
    db: Session,
    case: Case,
    event_type: str,
    occurred_at: date,
    actor_id: uuid.UUID,
    payload: dict,
    document_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    if_match: int | None = None,
    today: date | None = None,
    system: bool = False,  # consequence events emitted by the clock engine
) -> AppendResult:
    raise NotImplementedError("build lane B1")
