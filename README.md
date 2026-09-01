# BhuArjan · भू-अर्जन

National Land Acquisition & Management System — SIH 26016 (Ministry of Rural Development, DoLR).

A national system of record for land acquisition under the RFCTLARR Act 2013 and Fourth Schedule acts: every stage, every statutory clock, every rupee — an append-only, hash-chained event ledger in which the documents themselves are the events.

Full product definition: [`Docs/final-product.md`](Docs/final-product.md).

## Run the demo

```
make demo
```

| Service | URL |
|---|---|
| Web | http://localhost:3016 |
| API docs | http://localhost:8016/api/v1/docs |
| MinIO console | http://localhost:9101 (bhuarjan / bhuarjan_dev) |

Docker Compose project name is `bhuarjan` — it appears as its own group in Docker Desktop. Ports (5433, 8016, 3016, 9100/9101) avoid other local stacks.

## Development

```
make dev-infra   # postgres+postgis (5433) and minio only
make api-dev     # uvicorn on 8016 (needs Python 3.12 venv: pip install -r api/requirements.txt)
make web-dev     # vite on 3016, proxies /api → 8016
make test        # statutory clock fixtures + hash-chain tests
```

## Layout

```
api/        FastAPI · SQLAlchemy · PostGIS · event ledger, rules engine, clocks
api/rulesets/  Statutory tracks as data (RFCTLARR 2013, NH Act 1956)
web/        React 18 + TS · Vite · Leaflet · Recharts
infra/      docker-compose.yml (project: bhuarjan)
seed/       demo project seed (real-shaped NH case)
Docs/       product definition, statute rules, API contract
```

Demo clock: send `X-Demo-Date: YYYY-MM-DD` (honoured only with `DEMO_MODE=true`) — the header the UI's demo-date picker sets.
