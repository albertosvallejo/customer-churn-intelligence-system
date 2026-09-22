# PHASE 6 — LOCAL HISTORY SYSTEM

## Objective
This document explains in detail how the currently implemented local history system works in Phase 6 of the project and which files it reads from or writes to.

## Functional summary
The local history system is the traceability layer for the simulated approval-and-launch flow of Phase 6. Its purpose is to preserve, in local artifacts, the lifecycle of each actionable proposal:

1. a proposal is generated from the latest evidence catalog;
2. a human decision is recorded on that proposal;
3. if approved, a simulated A/B test can be launched;
4. the launch result is appended to local history;
5. derivative views such as KPI status and n8n-ready payloads are rebuilt from those local artifacts.

The system is local-first and file-backed. It does **not** depend on a remote service to preserve this history.

---

## Main implementation files

### Core logic
- `src/evidence/phase6_integration.py`
- `src/api/churn_service.py`

### CLI entrypoints
- `scripts/build_phase6_action_proposals.py`
- `scripts/build_phase6_kpi_status.py`
- `scripts/build_phase6_n8n_payload.py`
- `scripts/launch_phase6_ab_test.py`

### Validation
- `tests/test_phase6_integration.py`

---

## Files the history system works with

## 1) Upstream input files
These files are not the history itself, but they are the inputs used to generate the objects that later feed history.

- `data/processed/evidence_catalog_<YYYYMMDD>.json`
  - Immutable dated evidence catalog.
  - Used as the source to derive recommendation candidates.

- `data/processed/phase6_action_proposals_<YYYYMMDD>.json`
  - Proposal artifact generated from the latest eligible evidence.
  - This file is later updated when a decision is recorded.

## 2) Main local history file
- `data/processed/action_history_log.parquet`
  - This is the **main append-only local history log**.
  - It stores lifecycle events for proposals.
  - Currently it records at least two event types:
    - `decision`
    - `ab_test_result`

Observed fields in the current implementation include:
- `event_id`
- `event_type`
- `proposal_id`
- `proposal_run_date`
- `decision_status`
- `decision_reason`
- `decided_by`
- `decision_ts`
- `deployment_mode`
- `intervention_id`
- `source_name`
- `ref_id`
- `recommendation_tier`
- `priority_score`
- `ab_test_status`
- `kpi_status`
- `ab_test_run_id`
- `launch_ts`
- `launched_by`
- `verdict`
- `p_value`
- `power_achieved`
- `guardrail_breach`
- `control_conversion_rate`
- `variant_conversion_rate`
- `control_opt_out_rate`
- `variant_opt_out_rate`

Important behavior:
- history is appended, not replaced;
- each decision creates a new row;
- each simulated A/B result creates another new row;
- the file acts as the operational audit trail for Phase 6 actions.

## 3) Complementary local run-history file
- `data/processed/phase6_ab_test_runs.parquet`
  - Stores one row per simulated A/B launch.
  - It is the structured run registry used to build KPI views and downstream payloads.

Observed fields in the current implementation include:
- `ab_test_run_id`
- `proposal_id`
- `proposal_run_date`
- `intervention_id`
- `deployment_mode`
- `launched_by`
- `launch_ts`
- `status`
- `primary_kpi`
- `guardrail_kpi`
- `control_n`
- `variant_n`
- `control_conversion_rate`
- `variant_conversion_rate`
- `control_opt_out_rate`
- `variant_opt_out_rate`
- `verdict`
- `p_value`
- `power_achieved`
- `guardrail_breach`
- `guardrail_ci_low`
- `guardrail_ci_high`
- `test_used`

## 4) Derived status and integration outputs
These are not the primary history store, but they are generated from it.

- `data/processed/phase6_kpi_status_<YYYYMMDD>.json`
- `reports/phase6_kpi_status_<YYYYMMDD>.md`
- `data/processed/phase6_n8n_payload_<YYYYMMDD>.json`
- `reports/phase6_action_proposals_summary_<YYYYMMDD>.md`

---

## Detailed operating flow

## Step 1 — Proposal generation
Function:
- `build_action_proposals()` in `src/evidence/phase6_integration.py`

Reads:
- `data/processed/evidence_catalog_<YYYYMMDD>.json`

Writes:
- `data/processed/phase6_action_proposals_<YYYYMMDD>.json`
- `reports/phase6_action_proposals_summary_<YYYYMMDD>.md`

What it does:
- loads the dated evidence catalog;
- builds recommendation rows;
- filters to approval-gate-eligible candidates;
- restricts scope to `INT-01`, `INT-02`, and `INT-04`;
- creates proposal objects with `decision_status = pending`.

At this point, no historical event has been appended yet. The proposals file becomes the working artifact that later receives the decision outcome.

## Step 2 — Decision recording
Function:
- `record_action_decision()` in `src/evidence/phase6_integration.py`

API endpoint:
- `POST /phase6/proposals/decision`

Reads:
- `data/processed/phase6_action_proposals_<YYYYMMDD>.json`

Writes:
- `data/processed/phase6_action_proposals_<YYYYMMDD>.json` (updated in place)
- `reports/phase6_action_proposals_summary_<YYYYMMDD>.md` (regenerated)
- `data/processed/action_history_log.parquet` (append)

What it does:
- validates `proposal_id`, `decision_status`, `decision_reason`, and `decided_by`;
- locates the matching proposal;
- prevents re-deciding a proposal that is no longer `pending`;
- updates the proposal artifact with the final decision fields;
- appends a `decision` event row to `action_history_log.parquet`.

This is the first moment where the local history log is written.

## Step 3 — Simulated A/B launch
Function:
- `launch_ab_test()` in `src/evidence/phase6_integration.py`

API endpoint:
- `POST /phase6/ab-tests/launch`

Reads:
- `data/processed/phase6_action_proposals_<YYYYMMDD>.json`
- `data/processed/phase6_ab_test_runs.parquet` (if it already exists)

Writes:
- `data/processed/phase6_ab_test_runs.parquet` (append)
- `data/processed/action_history_log.parquet` (append)

What it does:
- checks that the proposal exists;
- requires the proposal decision to be `approved`;
- enforces `deployment_mode = simulated`;
- prevents duplicate launch for the same `proposal_id`;
- runs the simulated A/B scenario;
- stores the structured run in `phase6_ab_test_runs.parquet`;
- appends an `ab_test_result` event into `action_history_log.parquet`.

This means the system keeps **two complementary local histories**:
- a run-oriented history in `phase6_ab_test_runs.parquet`;
- an event-oriented audit trail in `action_history_log.parquet`.

## Step 4 — KPI status rebuild
Function:
- `build_kpi_status_view()` in `src/evidence/phase6_integration.py`

API endpoint:
- `GET /phase6/kpis/latest?refresh=true`

Reads:
- `data/processed/phase6_ab_test_runs.parquet`

Writes:
- `data/processed/phase6_kpi_status_<YYYYMMDD>.json`
- `reports/phase6_kpi_status_<YYYYMMDD>.md`

What it does:
- loads the local registry of simulated A/B runs;
- derives latest KPI-facing records;
- computes lift and exposes verdict-level status.

Important note:
- this KPI file is a **derived view**, not the authoritative raw history.
- the authoritative run-level input is `phase6_ab_test_runs.parquet`.

## Step 5 — n8n payload rebuild
Function:
- `build_n8n_action_payload()` in `src/evidence/phase6_integration.py`

API endpoint:
- `GET /phase6/n8n-payload/latest?refresh=true`

Reads:
- `data/processed/phase6_action_proposals_<YYYYMMDD>.json`
- `data/processed/phase6_ab_test_runs.parquet` (if available)

Writes:
- `data/processed/phase6_n8n_payload_<YYYYMMDD>.json`

What it does:
- extracts approved proposals;
- enriches them with the latest known A/B status if one exists;
- emits a versioned payload ready for orchestration/integration.

---

## How the API exposes the local history

Defined in `src/api/churn_service.py`.

### Read endpoints
- `GET /phase6/proposals/latest`
  - returns latest or requested proposal artifact.

- `GET /phase6/action-history/latest`
  - reads `action_history_log.parquet` through `load_action_history()`.
  - returns the append-only event history.

- `GET /phase6/kpis/latest`
  - returns the latest KPI status snapshot.

- `GET /phase6/n8n-payload/latest`
  - returns the latest integration payload.

### Write endpoints
- `POST /phase6/proposals/decision`
  - records a human decision and appends a history event.

- `POST /phase6/ab-tests/launch`
  - launches a simulated A/B test and appends run/history records.

---

## Data model interpretation

## Authoritative files by responsibility
- **Evidence baseline:** `data/processed/evidence_catalog_<YYYYMMDD>.json`
- **Working proposal state:** `data/processed/phase6_action_proposals_<YYYYMMDD>.json`
- **Event audit trail:** `data/processed/action_history_log.parquet`
- **A/B run registry:** `data/processed/phase6_ab_test_runs.parquet`
- **KPI-derived projection:** `data/processed/phase6_kpi_status_<YYYYMMDD>.json`
- **Integration projection:** `data/processed/phase6_n8n_payload_<YYYYMMDD>.json`

## Practical distinction
- If the question is **"what happened over time?"**, the main file is `action_history_log.parquet`.
- If the question is **"what simulated tests were run and with which metrics?"**, the main file is `phase6_ab_test_runs.parquet`.
- If the question is **"what is the current proposal state?"**, the file is `phase6_action_proposals_<YYYYMMDD>.json`.

---

## Current design characteristics

### Strengths
- local and reproducible;
- append-oriented auditability;
- easy rebuild of derivative artifacts;
- simple separation between proposal state, event history, and A/B run history;
- test coverage exists in `tests/test_phase6_integration.py`.

### Current limitations
- history is file-backed, not yet a relational event store;
- there is no cross-file transaction layer;
- proposal JSON is updated in place, while history parquet files are append-based;
- the current implementation is explicitly for simulated deployment mode only.

---

## Minimal mental model
The implemented local history system can be understood as follows:

- **proposal JSON** = current decisionable object;
- **action_history_log.parquet** = append-only audit log of decisions and outcomes;
- **phase6_ab_test_runs.parquet** = structured registry of simulated launches;
- **KPI / n8n artifacts** = downstream materializations built from those local records.

That is the effective local history architecture currently implemented in Phase 6.
