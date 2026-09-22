# DEPLOYMENT

## Scope

This document describes the public runtime contract that is actually supported by this repository today and the evidence that validates it.

## Current public runtime

### Local reproducible release line — operational

Runtime files:

- `docker-compose.yml`
- `Dockerfile.api`
- `Dockerfile.web`
- `.env.example`
- `scripts/demo_verify.sh`
- `scripts/http_healthcheck.py`

What this state supports:

- `api` service on port `62881`
- `web` service on port `8080`
- public dashboard at `/customer-churn/dashboard`
- protected review routes under `/customer-churn/new-actions-testing` and `/customer-churn/tested-actions-approval`

Evidence:

- `reports/reproducibility/02_cp2_packaging_runtime_audit.md`
- `reports/reproducibility/03_cp3_fastapi_byok_audit.md`
- `reports/reproducibility/CP5_EXTERNAL_VALIDATION_EVIDENCE.txt`

### External Docker validation — verified evidence

Primary evidence:

- `reports/reproducibility/CP5_EXTERNAL_VALIDATION_EVIDENCE.txt`
- `reports/reproducibility/CP5_EXTERNAL_VALIDATION_STATUS.md`

What this confirms:

- `docker compose up --build` succeeded on an external Docker-capable machine;
- `api` and `web` became healthy;
- the public runtime contract behaved as documented.

## Public quick start

```bash
cp .env.example .env
docker compose up --build
# Dashboard: http://localhost:8080/customer-churn/dashboard
# API docs:  http://localhost:8080/docs
```

## Environment variables that matter

Minimum documented runtime contract from `.env.example`:

- `APP_ENV`
- `CHURN_API_HOST`
- `CHURN_API_PORT`
- `MODE`
- `SOURCE_DB_URL`
- `CHURN_DB_URL`
- `LLM_MODE`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `PHASE7_REVIEW_TOKEN`

## Production posture deliberately excluded

This public release does not claim:

- staging deployment;
- systemd-managed runtime choreography;
- Drive-managed deployment flow;
- GHCR publication;
- final production cutover manifests.

## Related docs

- `docs/reproducibility/REPRODUCIBILITY.md`
- `SECURITY.md`
- `docs/reproducibility/CLEANROOM_EVIDENCE_TABLE.md`
- `docs/adr/ADR-001-reproducible-deployment.md`
