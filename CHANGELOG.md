# CHANGELOG

> Editorial reconstruction from `docs/releases/RELEASE_NOTES.md`, `_private/_docs/tech_doc.md`, and reproducibility evidence files.
>
> This file is intentionally honest about gaps: where exact public-release boundaries are not documented with enough precision to claim a canonical semantic version, the entry says so explicitly instead of inventing one.

## [Public release curation executed] - 2026-08-21

### Updated
- public documentation aligned to the final reproducible release contract
- workflow definitions aligned with `Dockerfile.api`, `Dockerfile.web`, and `docker-compose.yml`
- `.gitignore` and `.dockerignore` aligned with curated exclusions
- public/private boundaries aligned with the approved release-curation specification

### Curated
- `_private/**` and other non-public historical artifacts excluded from the public release set
- canonical Drive branding assets reconciled into the workspace before release-copy generation
- final public evidence set frozen for the GitHub candidate copy

### Not part of this change
- GitHub upload
- GHCR publication
- staging / deploy / cutover execution

## [Unreleased Phase 7 reproducibility hardening] - 2026-08-14

### Fixed
- Synthetic bundle builder determinism defect in Phase 7.
- Synthetic bundle manifest regeneration when missing.
- Three inherited auth tests realigned to `X-Phase7-Token` header expectations.

### Verified
- strict two-copy rebuild parity for the canonical synthetic bundle;
- focused Phase 7 suite green after the test realignment.

## [CP5 external validation closure] - 2026-08-11

### Verified
- external Docker validation package succeeded on a Docker-capable machine;
- `docker compose up --build` completed successfully;
- `api` and `web` were healthy;
- smoke/API checks passed;
- clean shutdown completed.

### Evidence
- `reports/reproducibility/CP5_EXTERNAL_VALIDATION_EVIDENCE.txt`
- `reports/reproducibility/CP5_EXTERNAL_VALIDATION_STATUS.md`

## [Reproducibility migration working line] - 2026-08-08 to 2026-08-12

### Added / changed
- CP0 baseline capture and SHA-256 manifest
- CP1 endpoint/contracts/migration evidence package
- CP2 packaging/runtime normalization (`Dockerfile.api`, `Dockerfile.web`, compose contract, health checks, verifier scripts)
- CP3 FastAPI/Uvicorn runtime migration with BYOK posture preserved
- clean-room attempt from isolated copy
- frontend integration fixes validated in real browser-backed checks

## [Phase 6 dynamic evidence system closure] - 2026-07-24

### Closed
- dynamic evidence catalog
- recommendation reprioritization
- approval/action-history chain
- simulated A/B launch flow
- KPI status surface
- dated documentary closure and sign-off

## [Phase 5 retention intervention validation closure] - 2026-07-18

### Closed
- proposal-and-validation framework for retention interventions
- blind validation and guardrail hardening
- case study publication and sign-off

## [v4.0.0-phase4-demo] - 2026-05-31

### Summary
Portfolio/demo baseline closure for the Phase 4 line.

## [v3.0.0-phase3b] - 2026-05-26

### Summary
Operational closure of the internal-pilot Phase 3B baseline.

## [v1.0.0] - historical public baseline

### Summary
First public analytical baseline before the later canonical V2C + Phase 3B + Phase 4 closure line.
