# ADR-001 — Migrate from legacy Drive/service runtime to a reproducible deployment line

- **Status:** Accepted
- **Date:** 2026-08-14
- **Decision owners:** Project Author + execution/review flow captured in the active reproducibility plan

## Context

The project reached a point where the analytical and operational value of the Phase 7 dashboard/review system could no longer rely on a non-reproducible runtime shape based on a manually maintained Drive copy plus ad-hoc service startup. The plan records the target explicitly: replace the legacy execution path with a versioned, reproducible package aligned with the DYSON RAG-style release discipline.

The documented legacy risks included:

- manual copy drift between workspace, Drive, and runtime;
- unclear provenance of the exact code serving the public/product routes;
- weak release traceability without a reproducible compose-based contract;
- difficulty proving BYOK and secret-handling boundaries cleanly;
- inability to treat packaging, clean-room verification, and future cutover as explicit checkpoints.

## Decision

Adopt a reproducible deployment line with these core properties. The canonical publication/transition flow itself is maintained only in `_private/PLAN_ACCION_REPRODUCIBILIDAD_CHURN_V12.md`, section `2.1`:

1. repository-based `api + web` runtime contract;
2. FastAPI/Uvicorn backend for the active Phase 7 routes;
3. Nginx web layer for the packaged frontend surface;
4. `.env.example` as template only, with real secrets written only to `.env` outside Git;
5. public synthetic dashboard that works without an OpenAI key;
6. BYOK-only operator AI functions;
7. reproducibility verified by checkpoint evidence (CP0–CP5), not by wording alone.

## Why this decision was taken

### 1. Reproducibility had to become executable

The project already had real business/UI value, but not yet a strong enough packaging/release story. The migration makes reproducibility testable through:

- smoke scripts
- health checks
- external Docker validation
- synthetic artifact manifests and hashes
- explicit deployment gates

### 2. BYOK and secret boundaries had to be enforceable

A reproducible public demo should not depend on hidden owner credentials. The chosen architecture allows the public synthetic dashboard to run keyless while keeping operator AI flows server-side and BYOK-only.

### 3. The project needed a cleaner portfolio story

The repository should present a reader with a credible `git clone -> cp .env.example .env -> docker compose up --build` narrative for the public demo line, backed by real evidence. That reader-facing startup story must not be confused with the separate publication transition governed canonically by plan section `2.1`.

### 4. The migration supports later production hardening without pretending it is done

The same line can later absorb:

- digest-pinned production images
- release manifests
- controlled cutover / rollback
- Traefik handoff under the final production gates

without falsely claiming that those steps are already complete.

## Alternatives considered implicitly by the evidence trail

### Keep the legacy runtime as the main published path

Rejected because it preserves manual drift and weak release traceability.

### Document the legacy runtime better but avoid packaging migration

Rejected because documentation alone would not provide reproducible startup, clean-room validation, or enforceable BYOK boundaries.

### Publish a Docker story without evidence

Rejected by the plan’s checkpoint discipline. The project required actual packaging evidence and external validation before claiming a reproducible deployment line.

## Consequences

### Positive

- clearer reproducibility story
- cleaner secret-handling policy
- easier external validation
- stronger portfolio documentation surface
- explicit separation between public synthetic demo and operator BYOK flows

### Negative / remaining work

- the final production release-manifest/digest layer still remains pending;
- the Ubuntu clean-room Docker row was formally discarded by Project Author decision on 2026-08-14, so it is no longer treated as an execution pending item;
- CP4 still remains open, but not because the CI workflow is missing: the Phase 8 chain is already implemented and versioned in the repository (`.github/workflows/ci-reproducibility.yml`) and has local-equivalent validation. Its real execution in GitHub Actions remains pending only as a consequence of the final GitHub publication step defined in section `2.1`;
- CP4 also still lacks documentary proof of the required limited live LLM call with the operator's own key;
- deployment documentation must continue to distinguish validated packaging from future production cutover;
- no image build or digest generation is considered part of the pre-GitHub workspace/Drive phase, per plan section `2.1`.

## Evidence supporting this ADR

- `reports/reproducibility/02_cp2_packaging_runtime_audit.md`
- `reports/reproducibility/03_cp3_fastapi_byok_audit.md`
- `reports/reproducibility/04_cp4_cleanroom_attempt_20260811.md`
- `reports/reproducibility/CP5_EXTERNAL_VALIDATION_EVIDENCE.txt`
- `reports/reproducibility/CP5_EXTERNAL_VALIDATION_STATUS.md`
- `_private/PLAN_ACCION_REPRODUCIBILIDAD_CHURN_V12.md`
