# Clean-Source Local Sandbox Validation — 2026-09-19

**Job ID:** `churn-clean-source-20260919-091935`
**Project:** `customer-churn-intelligence-system`
**Validation type:** clean-source (validates the source as it stood on the run date, with no new fixes applied during the run itself)
**Executed by:** Project Author, on a private local sandbox runner (independent of GitHub Actions)
**Result:** `CLEAN_SOURCE_REPRODUCIBILITY=PASS`

## What this evidence is — and is not

- This is the Project Author's own local run. It demonstrates that the source built, started and served correctly, end to end, in an isolated environment on 2026-09-19.
- It is **not** an independent third-party audit, and it is **not re-executable directly from this repository alone** — it ran against a private local sandbox runner outside of GitHub.
- A separate public, re-runnable complementary check is provided by the GitHub Actions fresh-checkout CI (`.github/workflows/ci-reproducibility.yml`); see the CI badge at the top of the README.
- This document summarizes the sandbox's own evidence pack. The full 14-file pack (job metadata, status, timeline, validation and remediation reports, raw runner logs, and a compose-security-guard record) is included in this repository at [`reports/reproducibility/sandbox-evidence/churn-clean-source-20260919-091935/`](sandbox-evidence/churn-clean-source-20260919-091935/); its SHA-256 manifest is reproduced below so it can be checked without re-downloading anything.

## Timeline

- Validation run (build → startup → readiness → smoke checks → cleanup): 2026-09-19, ~09:19–09:20 CEST, per the runner's own timestamped logs.
- Evidence pack recorded: 2026-09-19, 16:03 CEST, per the pack's manifest.
- Single attempt; no retries were needed.

## Stage results

Taken directly from the runner's own logs and validation report:

| Stage | Result |
|---|---|
| Isolated workspace copy | PASS |
| Compose security guard | PASS |
| Rootless Docker access / preflight | PASS |
| Docker build (api + web images) | PASS |
| Startup (containers up, api container healthy) | PASS |
| Readiness (api and web ports both responded on the first attempt) | PASS |
| Smoke verification (`/health` and the dashboard/API routes all returned HTTP 200) | PASS |
| Project verification | PASS |
| Workspace cleanup | PASS |
| **Overall result** | **PASS** |

## Fixes applied during this run

None. This run validates a source that had already incorporated the fixes promoted from an earlier remediation cycle (`churn-cycle-20260918-094729`); no further changes were made to reach PASS.

## Evidence pack integrity

All 14 files in the pack were verified against its own SHA-256 manifest (`sha256sum -c` returns OK for every entry):

```
054d6d96cdd81ff5b9661637c3f14178d415703a1172a67256c960d52838a39b  DRIVE_SYNC.txt
9fda39a2198c7d451083d7d5b112228aa5c1dc114b93f9388e32929731ae024b  attempts/LEGACY_ACCUMULATED_LOGS.md
40065c0ca2bdc90dca3f2e7729b94a0f5e3736810f29ba20df3d52096a1f17b7  attempts/legacy/stderr.log
dccc3e912e4a1a5596577a2a9c881675c60637dd999c189227e498e0d9ae304d  attempts/legacy/stdout.log
4645d586df623955fcd149f0ff28f0ce38cb373af024ba7efd4aa606e2d16ec8  compose_guard.txt
089b04bb56c5ae4bcb215a914bc80c92f0972d33dfac11551ab58831290ff9b8  job.json
40065c0ca2bdc90dca3f2e7729b94a0f5e3736810f29ba20df3d52096a1f17b7  logs/stderr.log
71f42b628635dc4d52929b509cac71ea4741b72881270da599714d2ccd06b5d3  logs/stdout.log
54b15e70a0c46480f81a36b91e7dba13a6a0da58f48e805b9ce94710b100caf1  manifest.json
6f43f92fe901fe1b9e437d880cc82cc43b2e3d8ad4d100ede669e3f5dc392fde  remediation_report.md
9dd20061141a4892b3e1589b1503e461e7f01b5c2ea3e54e5dd4828d2f52b6f2  status.json
beb67922df410a8fef915c936cba8bd408c9c70a009c4ed7d8955108f4569b5e  summary.txt
fef87cf498af1f0636b0cbc96678e63a446d92565b60ec14e4bfc54b64de2cc4  timeline.md
e288456a7fce0afb905ca1df1d1332380cb932f6ce843de0244193e7d28a11c1  validation_report.md
```

## Related evidence

- Prior remediation cycle whose fixes were promoted into this clean source: `churn-cycle-20260918-094729`

## Note on the raw pack

The raw files (`logs/stdout.log`, `job.json`, `status.json`, `DRIVE_SYNC.txt`) record the private runner's internal workspace paths, an internal bind IP, and a Drive sync path used for the Project Author's own infrastructure. These are operational details of the private sandbox runner, not of the published application, and do not affect the PASS result above.
