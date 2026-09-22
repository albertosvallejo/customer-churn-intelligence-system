# REPRODUCIBILITY

## Purpose

This document explains the final public reproducibility contract of the project and the evidence that supports it.

## Public reproducibility contract

For the current public release line, reproducibility means:

1. the same repository can start the public synthetic dashboard and token-gated operator review surfaces with a documented runtime contract;
2. the public demo can run without an OpenAI key;
3. operator-side LLM behavior remains BYOK-only;
4. synthetic demo artifacts are versioned and deterministic where required;
5. verification is supported by executable evidence, not by documentation claims alone.

## Runtime contract used by the public release

The public runtime contract is:

- `Dockerfile.api`
- `Dockerfile.web`
- `docker-compose.yml`
- `.env.example`
- `scripts/demo_verify.sh`
- `scripts/http_healthcheck.py`

This contract starts:

- the public dashboard at `/customer-churn/dashboard`;
- the protected review surfaces at `/customer-churn/new-actions-testing` and `/customer-churn/tested-actions-approval`;
- a FastAPI/Uvicorn application runtime behind the packaged web layer.

## Evidence chain included in the repository

### CP2 — local packaging/runtime closure

Evidence file:

- `reports/reproducibility/02_cp2_packaging_runtime_audit.md`

What this proves:

- explicit `api + web` packaging files exist;
- `.env.example` matches the synthetic-demo baseline;
- `scripts/demo_verify.sh` passed against the live local runtime;
- the public dashboard and protected review routes responded with the expected status codes.

### CP3 — FastAPI + BYOK closure

Evidence file:

- `reports/reproducibility/03_cp3_fastapi_byok_audit.md`

What this proves:

- the reproducible API line runs through FastAPI/Uvicorn;
- the token gate and BYOK posture were preserved;
- synthetic-demo mode still works without an OpenAI key.

### Clean-room local copy

Evidence file:

- `reports/reproducibility/04_cp4_cleanroom_attempt_20260811.md`

What this proves:

- a fresh copy outside the working tree was bootstrapped from `.env.example` and validated;
- `demo_verify.sh` passed from that isolated copy;
- the full local suite passed from that clean-room copy.

### External Docker validation

Evidence files:

- `reports/reproducibility/CP5_EXTERNAL_VALIDATION_EVIDENCE.txt`
- `reports/reproducibility/CP5_EXTERNAL_VALIDATION_STATUS.md`

What this proves:

- `docker compose up --build` succeeded on an external Docker-capable machine;
- `api` and `web` became healthy;
- public routes returned `200` and protected routes enforced `401/200` behavior correctly.

## Deterministic synthetic bundle

The canonical public synthetic bundle is part of the reproducibility contract.

Canonical hashes:

- `data/synthetic_demo/synthetic_demo__phase7_integrated_actions_20260727.json`
  - `f34b6544447eaae1de358ef7c9e1bd6453e7d471a10ce900a39693b1c1e8d264`
- `data/synthetic_demo/synthetic_demo__phase7_manifest_20260727.json`
  - `580e54e8829c7860b11ab4cb6d520e96269d240c17824c8706252126cff6a336`

## What is reproducible today

- local repo-root startup for the synthetic dashboard/review surfaces;
- FastAPI/Uvicorn API runtime for the public release line;
- external Docker validation of `docker compose up --build`;
- public synthetic dashboard without an OpenAI key;
- token-gated operator review routes;
- deterministic regeneration of the canonical Phase 7 synthetic bundle.

## Explicitly out of scope for this public contract

- production cutover manifests with pinned digests;
- staging, systemd, or Drive-managed runtime choreography;
- `_private` operational planning and internal checkpoints;
- GitHub/GHCR publication status.

## How to verify this yourself

1. Read `docs/reproducibility/CLEANROOM_EVIDENCE_TABLE.md` for the consolidated evidence map.
2. Run the public quick start from the README.
3. Review CP5 external evidence for the literal Docker validation transcript.
4. Compare the canonical synthetic hashes listed above against the current files.
