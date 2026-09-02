"""The `report_jobs` table.

Why a table of its own rather than a `documents` row with `kind='report'`: a report
is not a document in this system's sense. `documents` is the evidence store — it is
content-addressed *and deduplicated per (case, sha256)*, so two identical reports
generated an hour apart would collapse onto one row and one `uploaded_at`, and a
report would start appearing in a case's document list beside the gazette it is
supposed to summarise. A report job is a request with a result: a template, the
filters it ran under, the `as_of_seq` it is true at, and the hash of the bytes.
That is a different shape, so it gets its own three-index table.

The bytes themselves still go to MinIO through the same content-addressed
`storage.put_bytes`, so nothing about the object store changes.

Defined here rather than in `app/models.py` because this table belongs to one
module; `app.api.v1.reports` imports it, so it is registered on `Base.metadata`
before `main.lifespan` runs `create_all`. `ensure_tables()` covers the one caller
that never imports `app.main` — the test harness, which runs `create_all` itself
before any router is imported.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ReportJob(Base):
    __tablename__ = "report_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(Text)  # csv | geojson
    filters: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(Text, default="done")  # done | failed
    as_of_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_hash: Mapped[str | None] = mapped_column(Text, nullable=True)  # sha256 hex
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    mime: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


Index("ix_report_jobs_requested_by", ReportJob.requested_by, ReportJob.generated_at)


_tables_ready = False


def ensure_tables() -> None:
    """Create `report_jobs` in the *current* schema if it is not there yet.

    `checkfirst=True` would ask "does report_jobs exist?" and the test harness's
    `search_path=test_x,public` would answer yes from the demo schema — the exact
    trap `tests/conftest.py` documents. So: create unconditionally (which targets
    the first schema on the path) and treat "already exists" as success.
    """
    global _tables_ready
    if _tables_ready:
        return
    from sqlalchemy.exc import ProgrammingError

    from app.core.db import engine

    try:
        with engine.begin() as conn:
            ReportJob.__table__.create(conn, checkfirst=False)
    except ProgrammingError as exc:
        # "already exists" is the success case on every call after the first. Any
        # other failure — an unreachable database, a permissions problem — must
        # surface, and must not latch the flag as though the table were there.
        if "already exists" not in str(exc).lower():
            raise
    _tables_ready = True
