from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import Base, engine
from app.core.problems import Problem, problem_handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.models  # noqa: F401 — register tables

    Base.metadata.create_all(engine)

    from app.domain.rules.loader import load_all_rulesets

    load_all_rulesets()

    if settings.SEED_ON_START:
        from seed.seed_demo import seed_if_empty

        seed_if_empty()

    from app.domain.alerts.scheduler import start_scheduler

    scheduler = start_scheduler()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="BhuArjan API",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/api/v1/openapi.json",
    docs_url="/api/v1/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # demo; restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(Problem, problem_handler)

from app.api.v1 import (  # noqa: E402
    alerts,
    admin,
    auth,
    cases,
    compensation,
    dashboards,
    documents,
    parcels,
    projects,
    public,
    reports,
    rr,
)

PREFIX = "/api/v1"
app.include_router(auth.router, prefix=PREFIX, tags=["auth"])
app.include_router(projects.router, prefix=PREFIX, tags=["projects"])
app.include_router(cases.router, prefix=PREFIX, tags=["cases"])
app.include_router(documents.router, prefix=PREFIX, tags=["documents"])
app.include_router(parcels.router, prefix=PREFIX, tags=["parcels"])
app.include_router(compensation.router, prefix=PREFIX, tags=["compensation"])
app.include_router(alerts.router, prefix=PREFIX, tags=["alerts"])
app.include_router(dashboards.router, prefix=PREFIX, tags=["dashboards"])
app.include_router(rr.router, prefix=PREFIX, tags=["rr"])
app.include_router(reports.router, prefix=PREFIX, tags=["reports"])
app.include_router(public.router, prefix=PREFIX, tags=["public"])
app.include_router(admin.router, prefix=PREFIX, tags=["admin"])


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "demo_mode": settings.DEMO_MODE}
