# 03 CP3 FastAPI + BYOK Audit

## Scope

CP3 was executed locally only, without touching production, Drive, Traefik, systemd, firewall, or shared services.

## Goal

Replace the legacy `BaseHTTPRequestHandler` runtime entrypoint with a FastAPI/Uvicorn backend while preserving:

- current route topology
- token-gated operator routes
- deprecated `410 Gone` launch behavior
- synthetic demo operation without an OpenAI key
- BYOK posture for LLM-capable paths

## What changed

### New FastAPI runtime

- `src/api/fastapi_app.py` created as the new CP3 HTTP application.
- `src/api/app.py` now starts the service through Uvicorn instead of the legacy threaded HTTP server.
- `requirements.txt` now declares:
  - `fastapi`
  - `uvicorn`
  - `python-dotenv`

### Contract preservation

The FastAPI layer preserves the current repo-side HTTP contract for the active CP scope, including:

- `GET /health`
- `GET /customer-churn/dashboard`
- `GET /customer-churn/dashboard/data`
- token-gated operator pages and data endpoints under:
  - `/customer-churn/tested-actions-approval`
  - `/customer-churn/new-actions-testing`
- protected write paths under `/phase7/...`
- deprecated `POST /phase7/stat-tests/launch` returning `410 Gone`

### Auth / BYOK posture

- The Phase 7 review-token model is preserved in FastAPI with the same header/query-token compatibility:
  - `X-Phase7-Token`
  - `?token=`
- `MODE=synthetic_demo` + `LLM_MODE=disabled` still works without an OpenAI key.
- Existing BYOK-sensitive code remains server-side; CP3 does not introduce any frontend key exposure.

## Local validation executed

The new FastAPI/Uvicorn service was started locally with:

```bash
PYTHONPATH=src CHURN_API_HOST=127.0.0.1 CHURN_API_PORT=62921 \
PHASE7_REVIEW_TOKEN=cp3-local-token MODE=synthetic_demo LLM_MODE=disabled \
CHURN_DB_URL=sqlite:////data/.openclaw/workspace/projects/TFM/daily-customer-churn-predictor/data/raw/churn_sqlite_db.sqlite \
SOURCE_DB_URL=sqlite:////data/.openclaw/workspace/projects/TFM/daily-customer-churn-predictor/data/raw/churn_sqlite_db.sqlite \
python3 -m api.app
```

Validation results:

- `demo_verify.sh OK`
- `200 /health`
- `200 /customer-churn/dashboard?run_date=20260727`
- `200 /customer-churn/dashboard/data?run_date=20260727`
- `401` on both protected approval pages without token
- `200` on both protected approval pages and both protected data endpoints with a valid token
- `410 /phase7/stat-tests/launch`

## CP3 local closure decision

CP3 is now treated as formally complete from the local workspace side because:

- the active API runtime has been switched to FastAPI/Uvicorn;
- the approved route/token contract is preserved locally;
- synthetic demo still runs without an OpenAI key;
- BYOK posture remains server-side and unchanged in principle;
- local smoke verification is green on the CP3 runtime.

## Remaining boundary

- No production rollout is claimed from this runtime.
- No Docker-capable deployment validation is claimed here beyond the already deferred external packaging gate.
