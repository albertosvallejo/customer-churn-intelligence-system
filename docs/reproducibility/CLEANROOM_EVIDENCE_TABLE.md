# CLEANROOM EVIDENCE TABLE

## Scope

This table consolidates the clean-room and reproducibility evidence included in the final public release package.

| Environment / gate | Claimed target | Real evidence available | Result | Note |
|:-------------------|:---------------|:------------------------|:-------|:-----|
| Workspace baseline | Baseline capture before migration | `00_current_state_baseline.md`, `00_full_test_transcript.txt`, `00_functional_matrix_transcript.txt`, `00_sha256_manifest.txt` | ✅ Verified | Workspace baseline only |
| Contracts freeze | Endpoint/contracts freeze | `01_endpoint_inventory.md`, `01_contracts_summary.md`, `01_cp1_gate_checklist.md` | ✅ Verified | Planning/contract evidence |
| Local packaging/runtime | Local reproducible runtime contract | `02_cp2_packaging_runtime_audit.md`, `docs/cp2_packaging_runbook.md` | ✅ Verified | Public runtime contract documented |
| FastAPI + BYOK | Reproducible API line | `03_cp3_fastapi_byok_audit.md` | ✅ Verified | Public HTTP runtime and BYOK posture validated |
| Clean-room isolated local copy | Clean-room repo copy using `.env.example` | `04_cp4_cleanroom_attempt_20260811.md` | ✅ Verified | Fresh isolated copy passed smoke + full suite |
| External Docker validation | Real `docker compose up --build` outside workspace runtime | `CP5_EXTERNAL_VALIDATION_EVIDENCE.txt`, `CP5_EXTERNAL_VALIDATION_STATUS.md` | ✅ Verified | Strongest external package proof currently available |
| Public CI workflow contract | Repo-level tests, secret scan, synthetic demo, compose smoke | `.github/workflows/ci-reproducibility.yml` | ✅ Included | Curated to match the public repository contents |
| Phase 7 deterministic synthetic rebuild | Deterministic artifact regeneration | `PHASE7_SYNTHETIC_DEMO_MANIFEST_20260727.json`, synthetic demo bundle files | ✅ Verified | Critical reproducibility sub-proof |

## Honest conclusion

What is already demonstrated with real evidence:

- the repo works from a fresh isolated copy;
- the public dashboard and protected review routes pass smoke checks;
- the FastAPI/Nginx reproducible line has passed external Docker validation;
- the canonical Phase 7 synthetic bundle is deterministically reproducible.

What is intentionally outside the public package:

- final production cutover manifests with image digests;
- staging / Drive / systemd operational choreography;
- `_private` planning and checkpoint material.
