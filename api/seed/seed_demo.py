"""Demo seed — one real-shaped NH project walked from 3A to award-clock-running.
Filled in the integration phase; must stay idempotent (seed_if_empty)."""

import logging

log = logging.getLogger(__name__)


def seed_if_empty() -> None:
    from app.core.db import SessionLocal
    from app.models import Project

    with SessionLocal() as db:
        if db.query(Project).first() is not None:
            log.info("seed: projects exist, skipping")
            return
    seed()


def seed() -> None:
    log.warning("seed: not yet implemented (integration phase)")
