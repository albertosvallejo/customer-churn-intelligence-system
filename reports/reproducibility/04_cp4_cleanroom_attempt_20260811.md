# 04 CP4 Clean-Room Attempt — 2026-08-11

## Scope

CP4 was attempted locally from an isolated clean-room copy, without touching production, Drive, Traefik, systemd, firewall, or shared services.

## What was verified successfully

A fresh copy was created outside the working project tree at:

- `/tmp/churn_cp4_cleanroom`

The copy excluded runtime-local clutter such as `.env`, caches, logs, and temp outputs. Inside that clean-room copy:

1. `.env` was created from `.env.example`.
2. Only the local review token was changed for the isolated run.
3. The API was started from the clean-room copy on `127.0.0.1:62931`.
4. `scripts/demo_verify.sh` passed against the clean-room runtime.
5. The full local test suite passed from the clean-room copy.

## Clean-room evidence

### Clean-room smoke result

`demo_verify.sh OK`

Returned statuses:

- `200 /health`
- `200 /customer-churn/dashboard?run_date=20260727`
- `200 /customer-churn/dashboard/data?run_date=20260727`
- `401 /customer-churn/tested-actions-approval?run_date=20260727`
- `401 /customer-churn/new-actions-testing?run_date=20260727`
- `200 /customer-churn/tested-actions-approval?run_date=20260727&token=cp4-cleanroom-token`
- `200 /customer-churn/new-actions-testing?run_date=20260727&token=cp4-cleanroom-token`
- `200 /customer-churn/tested-actions-approval/data?run_date=20260727&token=cp4-cleanroom-token`
- `200 /customer-churn/new-actions-testing/data?run_date=20260727&token=cp4-cleanroom-token`

### Full suite from clean-room copy

- `158 passed in 14.60s`

## Real blocker found

The runtime available to this agent does not include Docker:

- `docker: not found`

Because of that, the required CP4 clean-room proof defined by plan V9 could not be completed from this session:

- no literal `docker compose up --build` validation could be executed here;
- no Docker-based cold-start/restart proof could be executed here;
- no Ubuntu/Windows Docker clean-room matrix could be closed from this runtime alone.

## Honest conclusion

CP4 is **not yet formally complete** from this session.

What is already proven:

- the current repo works from a fresh isolated copy with `.env.example`-derived configuration;
- the synthetic-demo/read-path and token-gated operator read surfaces pass in clean-room local execution;
- the full suite is green from that clean-room copy.

What remains blocked:

- the Docker-capable clean-room validation required by CP4 plan V9.
