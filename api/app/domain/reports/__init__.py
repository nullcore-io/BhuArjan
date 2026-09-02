"""MIS reports (Docs/APIs.md §3.10, Docs/rules.md C7).

Three templates — `national_kpis`, `cases_register`, `compensation_register` — in
CSV, plus a GeoJSON parcels export of the cases register. Every export carries the
`as_of_seq` it is true at and the SHA-256 of its own bytes, which is what C7 means
by "exports embed the as-of sequence and a report hash".
"""

from app.domain.reports.models import ReportJob, ensure_tables  # noqa: F401
from app.domain.reports.service import (  # noqa: F401
    FORMATS,
    TEMPLATES,
    generate_report,
    job_payload,
)
