# CP2 Packaging Runbook

## Purpose

Minimal operator notes for the CP2 packaging cut while Docker validation is still deferred to a Docker-capable environment.

## Default compose contract

Base file:
- `docker-compose.yml`

Services:
- `api`
- `web`
- optional `postgres` under profile `ops-db`

Health/readiness now defined:
- `api` -> `GET /health` via `scripts/http_healthcheck.py`
- `web` -> `GET /health` through nginx proxy

## Local non-default port mapping

Override file:
- `docker-compose.cp2.local.yml`

Local override ports:
- `api` -> `62882:62881`
- `web` -> `8081:80`
- `postgres` -> not published

## Local non-Docker smoke path used in this runtime

Because this OpenClaw container does not ship with Docker, the honest local smoke path for CP2 is:

```bash
PYTHONPATH=src CHURN_API_HOST=127.0.0.1 CHURN_API_PORT=62911 \
PHASE7_REVIEW_TOKEN=cp2-local-token MODE=synthetic_demo LLM_MODE=disabled \
CHURN_DB_URL=sqlite:////data/.openclaw/workspace/projects/TFM/daily-customer-churn-predictor/data/raw/churn_sqlite_db.sqlite \
SOURCE_DB_URL=sqlite:////data/.openclaw/workspace/projects/TFM/daily-customer-churn-predictor/data/raw/churn_sqlite_db.sqlite \
python3 -m api.app
```

Then verify with:

```bash
BASE_URL=http://127.0.0.1:62911 RUN_DATE=20260727 PHASE7_TOKEN=cp2-local-token ./scripts/demo_verify.sh
python3 scripts/http_healthcheck.py http://127.0.0.1:62911/health
```

## Expected use later in a Docker-capable environment

Default:
```bash
docker compose up --build
```

Local override:
```bash
docker compose -f docker-compose.yml -f docker-compose.cp2.local.yml up --build
```

With optional Postgres profile:
```bash
docker compose --profile ops-db up --build
```

## Important current truth

- The current `web` image is still a compatibility proxy layer.
- The current `api` image starts the canonical FastAPI/Uvicorn runtime through `src/api/app.py`.
- Compose now includes explicit healthchecks and waits for `api` health before bringing `web` up as healthy.
- Final Docker validation is not claimed from this OpenClaw container because `docker` is unavailable here.
