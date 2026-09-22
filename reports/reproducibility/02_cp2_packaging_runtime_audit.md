# 02 CP2 Packaging / Runtime Audit

## Scope

First CP2 proof-of-start on the local workspace only, without touching production, Drive, Traefik, systemd, firewall, or shared services.

## What was checked

1. Current packaging files:
   - `Dockerfile`
   - `docker-compose.yml`
   - `docker-compose.7.2.5a.local.yml`
   - `.env.example`
   - `requirements.txt`
2. Presence/absence of the first CP2 target artifacts:
   - `scripts/demo_verify.sh`
   - `Dockerfile.api`
   - `Dockerfile.web`
   - `web/nginx.conf`
   - `web/dist`
   - `src/api/app.py`
3. Real local runtime start outside Docker using the current HTTP server:
   - `python3 -m api.churn_service`
   - host `127.0.0.1`
   - port `62901`
   - local review token configured
   - SQLite DB path pinned locally
4. Real local verification via `scripts/demo_verify.sh` against that running instance.

## Literal findings

### A. Current packaging is not yet CP2-ready as a reproducible repo contract

- `Dockerfile` still defaults to **Jupyter Lab**, not the API runtime.
- `docker-compose.yml` overrides the image command to `python3 -m api.churn_service`.
- `docker-compose.yml` still mounts the whole repo as a bind mount (`./:/app`), which is a dev/runtime coupling rather than the final reproducible release contract.
- `.env.example` still reflects a Phase 3 / Postgres-oriented baseline, not the finalized CP2 minimal public-demo baseline.
- `requirements.txt` does **not** currently list the target-stack packages expected for the later FastAPI cut (`fastapi`, `uvicorn`, `pydantic`, `python-dotenv`, etc.).
- This runtime cannot run `docker compose` directly because `docker` is not installed in the current container session, so Compose validation remains a separate environment requirement.

### B. Missing first-cut CP2 target artifacts at start of this pass

Before this pass:

- `scripts/demo_verify.sh` → missing
- `Dockerfile.api` → missing
- `Dockerfile.web` → missing
- `web/nginx.conf` → missing
- `web/dist` → missing
- `src/api/app.py` → missing

### C. Current implementation can already start locally outside Docker

A real local start of the current implementation succeeded with:

```bash
python3 -m api.churn_service
```

using:

- `CHURN_API_HOST=127.0.0.1`
- `CHURN_API_PORT=62901`
- `PHASE7_REVIEW_TOKEN=cp2-local-token`
- `CHURN_DB_URL=sqlite:////data/.openclaw/workspace/projects/TFM/daily-customer-churn-predictor/data/raw/churn_sqlite_db.sqlite`

Observed startup log:

```text
2026-08-10 10:10:09,171 INFO __main__ - Starting churn service on 127.0.0.1:62901
```

### D. `.env.example` normalized toward the CP2 baseline

In the same pass, `.env.example` was updated away from the old Postgres-first framing and toward the approved CP2 baseline:

- `MODE=synthetic_demo`
- `LLM_MODE=disabled`
- `OPENAI_API_KEY=` placeholder only
- `PHASE7_REVIEW_TOKEN=change-this-local-demo-token`
- SQLite-backed `CHURN_DB_URL` / `SOURCE_DB_URL`
- legacy Postgres variables kept only as optional compatibility context, not as the primary demo contract

A real local restart with that CP2-style baseline also succeeded, but it exposed one useful nuance: in `MODE=synthetic_demo`, the currently available seeded operator/demo artifact line is `20260727`, not `20260726`.

### E. First reusable CP2 verification script created and executed

New file created in this pass:

- `scripts/demo_verify.sh`

Real execution against the live local instance:

```bash
BASE_URL=http://127.0.0.1:62901 RUN_DATE=20260726 PHASE7_TOKEN=cp2-local-token ./scripts/demo_verify.sh
```

Result on the first local isolated run (default local/real-style baseline):

```text
demo_verify.sh OK
200 /health
200 /customer-churn/dashboard?run_date=20260726
200 /customer-churn/dashboard/data?run_date=20260726
401 /customer-churn/tested-actions-approval?run_date=20260726
401 /customer-churn/new-actions-testing?run_date=20260726
200 /customer-churn/tested-actions-approval?run_date=20260726&token=cp2-local-token
200 /customer-churn/new-actions-testing?run_date=20260726&token=cp2-local-token
200 /customer-churn/tested-actions-approval/data?run_date=20260726&token=cp2-local-token
200 /customer-churn/new-actions-testing/data?run_date=20260726&token=cp2-local-token
```

Then, after normalizing `.env.example` toward `MODE=synthetic_demo`, the same verifier initially failed on protected operator pages for `RUN_DATE=20260726` because the seeded synthetic-demo package for operator flows currently exists on `20260727`. Re-running with `RUN_DATE=20260727` passed cleanly:

```text
demo_verify.sh OK
200 /health
200 /customer-churn/dashboard?run_date=20260727
200 /customer-churn/dashboard/data?run_date=20260727
401 /customer-churn/tested-actions-approval?run_date=20260727
401 /customer-churn/new-actions-testing?run_date=20260727
200 /customer-churn/tested-actions-approval?run_date=20260727&token=cp2-local-token
200 /customer-churn/new-actions-testing?run_date=20260727&token=cp2-local-token
200 /customer-churn/tested-actions-approval/data?run_date=20260727&token=cp2-local-token
200 /customer-churn/new-actions-testing/data?run_date=20260727&token=cp2-local-token
```

`demo_verify.sh` was therefore updated to default to `RUN_DATE=20260727`, matching the currently seeded synthetic-demo line.

## Interpretation

This is a useful CP2 baseline split:

- the **application/runtime contract** is already locally startable with the current server;
- the **packaging/release contract** is still incomplete for the target reproducible `docker compose up --build` path.

So the next CP2 work should focus on packaging normalization, not on debugging the business HTTP surface first.

## Second packaging cut completed locally

A second CP2 packaging pass then moved the repo one step closer to a reproducible release contract:

- `Dockerfile.api` created as the explicit API runtime image, targeting `python3 -m api.app` on port `62881`.
- `src/api/app.py` created as a bridge entrypoint so packaging no longer points directly at the monolithic `api.churn_service` command.
- `Dockerfile.web` created as the first explicit web container image.
- `web/nginx.conf` created as the first compatibility web gateway:
  - `/customer-churn/*` → proxied to `api:62881`
  - `/phase7/*` → proxied to `api:62881`
  - `/health` → proxied to `api:62881`
  - `/mockup/` → serves the approved dashboard mockup source tree for packaging continuity
- `docker-compose.yml` was rewritten from the old `scoring-api + postgres` shape into an explicit `api + web` default contract, with `postgres` retained only as an optional `ops-db` profile rather than the baseline demo requirement.
- `.dockerignore` was tightened to reduce non-public / non-runtime context (temporary outputs, caches, local runtime artifacts, notebook/site build leftovers, etc.).
- `web/README.md` now documents that the current web image is a CP2 compatibility layer, not yet the final static-frontend parity cut.

## Current local validation after packaging cuts

- `python3 -m api.app` still starts successfully on an isolated local port.
- `scripts/demo_verify.sh` still passes against that bridge entrypoint with the CP2 synthetic-demo baseline.
- Docker image/build validation itself remains deferred because `docker` is unavailable in this OpenClaw container.

## Third packaging cut completed locally

A third CP2 packaging pass then clarified how the new `api + web` contract should be exercised later from a Docker-capable environment:

- `docker-compose.cp2.local.yml` was added as the first dedicated CP2 local override.
  - `api` -> `62882:62881`
  - `web` -> `8081:80`
  - `postgres` -> no published port
- `docs/cp2_packaging_runbook.md` was added to document:
  - default compose contract
  - local override usage
  - optional `ops-db` profile usage
  - the current honest limits of this cut (compatibility web layer, bridge API entrypoint, Docker validation still deferred from this runtime)

## Fourth packaging cut completed locally

A fourth CP2 packaging pass then added explicit readiness semantics to the new compose contract:

- `scripts/http_healthcheck.py` created as a reusable HTTP 200 probe helper.
- `docker-compose.yml` now defines:
  - `api` healthcheck -> `python3 /app/scripts/http_healthcheck.py http://127.0.0.1:62881/health`
  - `web` healthcheck -> `wget -qO- http://127.0.0.1/health`
  - `web.depends_on.api.condition = service_healthy`
- `docs/cp2_packaging_runbook.md` updated so the runbook now documents the readiness model as part of the compose contract.

## Fifth validation cut completed locally

A fifth CP2 closure pass then confirmed the local packaging/runtime baseline is complete enough to close CP2 from the workspace side:

- `docs/cp2_packaging_runbook.md` now records the exact non-Docker smoke path actually available in this runtime (`PYTHONPATH=src python3 -m api.app` + `scripts/demo_verify.sh` + `scripts/http_healthcheck.py`).
- A fresh isolated local verification was executed against `api.app` on port `62911` with the CP2 synthetic-demo baseline.
- Result:
  - `demo_verify.sh OK`
  - `200 /health`
  - `200 /customer-churn/dashboard?run_date=20260727`
  - `200 /customer-churn/dashboard/data?run_date=20260727`
  - `401` on both protected approval pages without token
  - `200` on both protected approval pages and both protected data endpoints with a valid token
- This additionally proves the new CP2 bridge entrypoint is runnable from the repo-root workflow expected by the runbook when `PYTHONPATH=src` is set, not only from an ad-hoc `cd src` shell position.

## CP2 local closure decision

CP2 is now treated as **formally complete from the local workspace side** because the agreed local packaging scope is satisfied:

- explicit API image file exists (`Dockerfile.api`)
- explicit web image file exists (`Dockerfile.web`)
- explicit web gateway config exists (`web/nginx.conf`)
- explicit bridge API entrypoint exists (`src/api/app.py`)
- default compose contract exists for `api + web` (`docker-compose.yml`)
- dedicated local compose override exists (`docker-compose.cp2.local.yml`)
- explicit readiness probes exist (`scripts/http_healthcheck.py`, compose healthchecks)
- explicit reusable smoke verifier exists (`scripts/demo_verify.sh`)
- local non-Docker runtime evidence is green against the CP2 synthetic-demo baseline
- operator notes for later Docker execution are captured in `docs/cp2_packaging_runbook.md`

The remaining Docker image/build execution check is therefore **not** kept inside CP2. It remains a later external-environment validation task and should be treated as deferred to the next Docker-capable gate rather than as an open local CP2 blocker.
