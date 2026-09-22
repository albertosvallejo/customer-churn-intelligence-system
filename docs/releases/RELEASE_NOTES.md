# RELEASE NOTES

## Public reproducible portfolio release — 2026-08-21

### Summary

This entry defines the current public release line of the **Customer Churn Intelligence System**. The repository now exposes the validated FastAPI/Uvicorn + Nginx runtime, the synthetic-demo quick start, the curated public evidence set, and the public documentation needed to evaluate the project without any `_private` material.

### What is included in the public release contract

- `Dockerfile.api`, `Dockerfile.web`, and `docker-compose.yml` as the real application runtime contract
- synthetic-demo quick start from `.env.example` without requiring an OpenAI key
- BYOK-only operator AI posture
- curated public evidence for reproducibility, synthetic demo, dashboard surfaces, Tested Actions, New Actions, business summary, and technical lineage
- public CI and GHCR workflow definitions aligned with the current runtime contract

### What is explicitly excluded from the public release contract

- `_private/**` operational traceability
- Drive/systemd/staging/cutover choreography
- digest-pinned production cutover manifests
- historical private packages and dated n8n snapshots excluded by release curation

### Current final state reflected by this release

- FastAPI/Uvicorn is the real HTTP runtime for the application line
- `Dockerfile.api` + `Dockerfile.web` are the canonical container build files
- `docker-compose.yml` is the active local/public runtime contract
- synthetic demo is keyless by default
- BYOK is optional and operator-scoped
- RH is closed
- `dashboard_review_2` is closed
- reproducibility is validated through curated evidence

---

## Phase 6 — Dynamic Evidence System — 2026-07-24

### Summary

This entry closes **Phase 6** at documentary/project scope: a move from a single static intervention-recommendation document (Phase 5B) to a reproducible evidence-refresh system — versioned evidence catalog snapshots, recommendation reprioritization, approval-ready proposals, append-only decision history, a simulated A/B launch flow reusing the real Phase 5 framework, and a dated KPI-status surface. Like Phase 5, this is documented as a dated closure note rather than a version bump, since it does not modify the canonical V2C scoring pipeline, the API, or the n8n orchestration layer.

The purpose is operational and documentary, not causal. This closure does not claim that any specific intervention has already improved churn or customer value against real VivaMarket customers.

### What was delivered

- Formal spec and governed source baseline for the dynamic evidence system (`docs/phase6_spec_dynamic_evidence_system.md`).
- Immutable evidence catalog snapshots with dated outputs (`data/processed/evidence_catalog_20260721.json`, `..._20260724.json`, `..._20260725.json`; summarized in `reports/phase6_evidence_catalog_summary_*.md`).
- Recommendation reprioritization from the latest available catalog snapshot (`reports/phase6_dynamic_evidence_recommendations_20260721/24/25.md`).
- Approval proposal generation for eligible interventions (`data/processed/phase6_action_proposals_20260724/25.json`, summarized in `reports/phase6_action_proposals_summary_20260724/25.md`).
- Append-only action-history logging (`data/processed/action_history_log.parquet`).
- Simulated A/B launch flow reusing the real Phase 5 framework (`scripts/launch_phase6_ab_test.py`, `data/processed/phase6_ab_test_runs.parquet`).
- Dated KPI-status reporting per run (`data/processed/phase6_kpi_status_20260724.json`, `reports/phase6_kpi_status_20260724.md`).
- n8n-ready payload generation for orchestration handoff (`scripts/build_phase6_n8n_payload.py`, `data/processed/phase6_n8n_payload_20260725.json`).
- Documentary closure in the README (`Phase 6 — Dynamic Evidence System` section) and dated sign-off (`reports/phase6_case_study_signoff_20260724.md`).

### Historical naming correction applied at closure

The artifact previously named `reports/phase6_intervention_recommendations_20260718.md` was clarified and renamed to `reports/phase5_step6_intervention_recommendations_20260718.md`. This was a nomenclature fix only — the content remains the Phase 5 step-6 recommendations deliverable and is not reinterpreted as a new Phase 6 output.

### Key decisions behind the closure

- **Scope boundary:** Phase 6 materially mitigates the earlier limitation where intervention prioritization lived only in a fixed historical report, by connecting approvals, action history, simulated launch, and KPI-status reporting end-to-end at project level. It does not claim the evidence layer is live, autonomous, or fed by production experimentation, and does not claim the simulated A/B launch path is equivalent to a completed real pilot.
- **Accepted limitation carried forward:** the pre-restoration behavior of `phase5_shadow_monitor.py` and `phase5_daily_status.py`, prior to the baseline used during the 6.4 audit, is not verifiable — no clean pre-edit evidence exists. The current restored state is accepted as the new operational baseline, without a claim of strict equivalence to the unknown pre-restoration state.

### Validation evidence

- `python3 -m unittest tests.test_phase6_catalog_builder tests.test_evidence_sourcing tests.test_phase6_integration -v` → `[fill in latest local pass/fail count before publishing]`
- Sub-phases 6.1 to 6.5 completed at documentary/project scope; README closure completed; historical naming collision resolved; dated sign-off artifact published.
- **Note:** unlike the Phase 5 entry above (independently re-verified in this project's own review process), the Phase 6 test-suite results have not been independently re-executed as part of that same review — confirm the current pass count locally before treating this line as verified.

### Known boundaries in this release

- No intervention has been validated on real VivaMarket customers through this system.
- The evidence layer is not live, autonomous, or fed by production experimentation.
- The simulated A/B launch path is not equivalent to a completed real pilot.
- This entry does not supersede or modify the `v4.0.0-phase4-demo` scoring/production baseline, nor the Phase 5 validation framework below.

### Recommended next step after this closure

Run the first real pilot (`INT-02`, personalization) per the Tier 1 test design in `reports/phase5_step6_intervention_recommendations_20260718.md`, once authorized, and feed its real result back through the Phase 6 evidence catalog on the next dated snapshot — a new workstream, not a Phase 6 pending item.

---

## Phase 5 — Retention Intervention Validation Framework — 2026-07-18

### Summary

This entry closes **Phase 5**, a proposal-and-validation framework for retention interventions (copy, timing, channel, incentive). It does not modify the canonical V2C scoring pipeline, the API, or the n8n orchestration layer, so it is documented as a dated closure note rather than a version bump — the same pattern used for the Phase 2 operational completion note under `v1.0.0`.

Phase 5 generates intervention proposals grounded in real sector literature, runs a statistically rigorous A/B test on them, and validates itself blind against 16 synthetic known-ground-truth scenarios generated by a process isolated from the evaluator. It can claim that the framework detects real conversion differences, avoids manufacturing false positives, and recognizes when it lacks signal. It cannot claim that any specific copy performs better with real VivaMarket customers — that requires the real pilot, explicitly out of scope here.

### What was delivered

- **A/B testing engine** (`src/pipeline/ab_testing_framework.py`), implemented and validated (53/53 unit tests), including a Power Guardrail (Cochran power check ahead of the point-estimate guardrail trigger) and a merged multi-arm verdict evaluator (`evaluate_multi_arm_test`).
- **16 synthetic ground-truth scenarios**, opaquely named, sealed ground truth.
- **Blind validation (Step 4): 13/16 correct** — all 8 "obvious"-effect scenarios and 6 of 8 "threshold" scenarios. All 16 underlying statistical computations were independently re-verified as numerically correct; the 3 misses were communication-layer failures (declaring a verdict near a threshold or on an underpowered sample), not arithmetic errors.
- **Sensitivity-limit mapping**, closed with Closure Criterion #4 met at 100%.
- **Final intervention recommendations**: `reports/phase5_step6_intervention_recommendations_20260718.md`.
- **Case study and sign-off**: `reports/phase5b_case_study_signoff_20260718.md`, explicitly confirmed by the project author on 2026-07-18.

### Key decisions behind the closure

- **Decision A — accepted residual:** two scenarios (`01_obvio`, `03_umbral`) cross the 2.0% opt-out threshold on pure sampling noise despite a true rate below it. Seven alternative designs were tested (fixed minimum-N, Wilson-CI/non-inferiority, mSPRT, Bayesian); all reopened a separate safety false negative instead. Accepted as a permanent, documented limitation, not a pending fix.
- **Decision B — ground-truth integrity (ALCOA+):** the 16-scenario ground-truth file is a reconstruction from documented spec parameters (the original was not found), so it is permanently labeled an accepted reconstruction rather than "sealed" or "original" data.
- **Decision C — partial guardrail coverage:** only 3 of 8 researched interventions (`INT-01`, `INT-02`, `INT-04`) have a guardrail measurable with the current opt-out-only framework. The other 5 require a mandatory manual-review gate before any real pilot.

### Validation evidence

- `python3 -m unittest tests.test_ab_testing_framework -v` → 53/53 passed
- Blind validation against all 16 sealed scenarios → 13/16 correct
- Case study and dated sign-off published at `reports/phase5b_case_study_signoff_20260718.md`

### Known boundaries in this release

- No real customer pilot has been run; all evidence is against synthetic ground-truth scenarios.
- The accepted noise-driven guardrail residual (Decision A) is a permanent limitation, not scheduled for a future fix.
- 5 of 8 candidate interventions still require manual review before any real pilot (Decision C).
- This entry does not supersede or modify the `v4.0.0-phase4-demo` scoring/production baseline below.

### Recommended next step after this closure

Run the first real pilot (`INT-02`, personalization) using the Tier 1 test design from `reports/phase5_step6_intervention_recommendations_20260718.md`, once authorized — a new workstream, not a Phase 5 pending item.

---

## v4.0.0-phase4-demo — 2026-05-31

### Summary

`v4.0.0-phase4-demo` marks the closure of the current **Phase 4 portfolio/demo baseline** for the Daily Customer Churn Predictor project.

This release preserves explicit comparability with both the historical **v1.0.0** public baseline and the later **v3.0.0-phase3b** internal-pilot baseline while adding a properly documented synthetic-measurement layer, governance reporting, benchmark-based redesign evidence, calibration evidence, and a cleaner stakeholder-facing publication narrative.

### What changed since `v3.0.0-phase3b`

#### Phase 4 demo measurement and governance
- Synthetic/historical-synthetic campaign measurement was formalized as the accepted Phase 4 evidence layer for portfolio scope.
- Stakeholder-facing BI surfaces were tightened so internal honesty labels remain in technical monitors while stakeholder views keep cleaner executive framing.
- A governance/drift monitor was added with feature drift, score drift, tier stability, and trigger-rule evaluation.
- A Phase 4 demo Model Card v3-equivalent narrative was generated to document governance interpretation.

#### Population-redesign benchmark and decision layer
- A benchmark/decision workflow was added to compare a retainable-customer redesign hypothesis against the current canonical V2C baseline using the synthetic closed-evaluation history.
- The benchmark supported the redesign hypothesis at portfolio level without silently authorizing an automatic retraining/redeployment line.

#### Senior-uplift hardening pass
- n8n routing was hardened to consume canonical emitted `risk_tier` instead of recomputing HIGH/MEDIUM branches from stale fixed thresholds.
- The API now exposes active `risk_thresholds` through `/health` and `GET /thresholds/latest`.
- Phase 4 HTML reports were restyled with stronger analytics UX hierarchy, branding, executive summaries, visible demo labeling, and clearer decision framing.
- `NB05` diagnostics were re-hardened to consume the current scoring-package artifact line and now export explicit raw vs sigmoid vs isotonic calibration evidence.
- Public documentation was tightened so the release narrative now separates ranking strength, calibration behavior, synthetic demo evidence, and deferred real-world validation more honestly.

### Key evidence and decisions in this release
- **Phase 4 demo closure accepted:** KPI / BI / governance / benchmark layers are now all documented and aligned with the portfolio/demo scope.
- **Calibration evidence made explicit:**
  - raw: `ROC AUC 0.8016`, `AP 0.9937`, `Brier 0.0572`, mean gap `0.1066`
  - sigmoid: `ROC AUC 0.8016`, `AP 0.9937`, `Brier 0.0224`, mean gap `0.0109`
  - isotonic: `ROC AUC 0.7919`, `AP 0.9920`, `Brier 0.0229`, mean gap `0.0082`
- **Population-redesign benchmark result:** retainable segment share ~`34.8%` (`1163 / 3346`) with aggregate holdout lift ~`2.81 pp` vs ~`0.94 pp` for the structural segment.
- **No automatic `v4.0.0` retraining release beyond this demo scope:** the redesign remains benchmark-supported, not silently operationalized.

### Validation evidence
- `python3 -m unittest tests.test_churn_service -v` → passed
- `python3 -m unittest tests.test_phase4_governance_monitor tests.test_phase4_population_redesign_benchmark -v` → passed
- `cd notebooks && jupyter nbconvert --to notebook --execute --inplace 05_model_evaluation_diagnostics.ipynb` → passed
- Phase 4 pipeline scripts were executed directly to regenerate the refreshed HTML/JSON artifacts.
- Local and Drive copies of the refreshed notebook, diagnostics, release-facing docs, and Phase 4 artifact set were synchronized and byte-verified.

### Known boundaries in this release
- This is still a **portfolio/demo** release, not a live customer-outcome production deployment.
- Campaign-response evidence remains synthetic/simulated wherever Phase 4 measurement depends on `retention_events` and holdout-lift evaluation.
- The canonical V2C line should still be framed as a ranking-first system rather than as a fully business-calibrated production risk engine.
- ROI remains scenario-based rather than causal or experimentally validated.
- A real retraining/redeployment line from the benchmark remains deferred unless explicitly approved later.

### Recommended next step after this release
1. Prepare a public GitHub/portfolio publication pass that presents `v4.0.0-phase4-demo` as the current portfolio baseline while preserving comparability with `v1.0.0`.
2. If desired later, open a separately approved workstream either for real-world validation instrumentation or for a true redesign implementation/retraining line.

---

## v3.0.0-phase3b — 2026-05-26

### Summary

`v3.0.0-phase3b` marks the operational closure of the current **Phase 3B internal-pilot baseline** for the Daily Customer Churn Predictor project.

This release preserves explicit comparability with the historical **v1.0.0** public baseline while presenting the stronger synchronized **canonical V2C artifact line** with:

- complete NB01–NB09 canonical notebook chain;
- improved V2C modeling / diagnostics / explainability stack;
- synchronized Docker/runtime baseline;
- tested scoring API and scoring package behavior;
- executed n8n V9 orchestration in a real production environment;
- publication-layer Model Card and scenario-based ROI framing;
- hardened workflow closure for LOW-tier governance and full eligible-record processing.

### What changed since the v1 baseline

#### Analytical and reporting layer
- Canonical V2C redesign established as the synchronized working line.
- Stronger diagnostics, explainability, monitoring dashboard, Model Card, and scenario-based ROI artifacts.
- Repository narrative aligned around explicit comparability between the published v1 baseline and the stronger V2C redesign.

#### Operational orchestration layer
- Phase 2 n8n V9 two-workflow architecture executed end-to-end in a real production environment.
- Coupon generation, email dispatch, push-path integration points, and action logging validated in the live stack.
- Internal orchestration remains framed as an internal-pilot-first baseline rather than a claim of fully hardened customer-facing production delivery.

#### Phase 3B closure hardening
- `Read Predictions` no longer uses `LIMIT 10`; the workflow now targets all eligible records with `send_action_flag = TRUE`.
- `Risk Switch` now includes an explicit LOW-risk branch.
- LOW-tier records are not dispatched yet; they are logged to `retention_actions_skipped` with reason code `low_tier_dispatch_deferred_td12` for governance-safe traceability.
- `docker-compose.yml` no longer exposes inline Postgres credentials and now reads them from `.env`.
- `.env.example` was corrected from legacy `churn_ops` wording to the current `vivamarket` baseline.
- Public README workflow narrative updated to match the final post-TD-15 / TD-16 state.

### Validation evidence

- `python3 -m unittest tests.test_churn_scoring -v` → passed
- `python3 -m unittest tests.test_churn_service -v` → passed
- `python3 -m py_compile src/models/churn_scoring.py src/api/churn_service.py src/pipeline/load_predictions.py` → passed
- Local and Drive copies of the final workflow/config/publication files were synchronized and byte-verified.

### Known boundaries in this release

- The churn target remains positive-heavy and should still be interpreted cautiously.
- The ROI layer is still scenario-based, not causal or experimentally validated.
- LOW-tier dispatch is intentionally deferred pending later channel-governance closure.
- OneSignal remains an integration boundary rather than a fully validated production-owned outbound channel in this release.

### Recommended next step after this release

This release is now historical context only. The Phase 4 portfolio/demo baseline has since been closed in `v4.0.0-phase4-demo`.

---

## v1.0.0

### Summary

Version 1.0.0 is the first complete end-to-end baseline of the Daily Customer Churn Predictor for VivaMarket Brasil.

This version was developed under an **ad hoc Spec-Driven Data Science framework** supported by **OpenClaw agents**, with explicit workflow control, notebook execution QA, and operational traceability across the project lifecycle.

It includes:

- full notebook flow from NB01 to NB09;
- temporal churn modeling;
- diagnostics and explainability;
- deployment-preparation code;
- retention-action orchestration artifacts;
- reporting/dashboard outputs;
- a README positioned around the Spec-Driven/OpenClaw/human-supervision methodology;
- expanded documentation of the current modeling approach, model families, feature blocks, and diagnostic logic;
- documented project limitations and a clear path toward v2.

### Delivered scope

- Data cleaning and analytical base creation
- Exploratory churn-oriented analysis
- Snapshot-based feature engineering
- Temporal model training and benchmark comparison
- Evaluation diagnostics
- Churn explainability outputs
- Scoring package preparation
- n8n retention orchestration design
- Reporting/dashboard generation

### Known limitation in v1

The current 90-day churn definition is extremely positive-heavy because the dataset is dominated by one-time buyers. This limits business separability and should be refined in v2.

### Why the version is still valid

Despite the analytical limitation, v1 is a valid baseline because it demonstrates a complete professional workflow, explicit traceability, operational outputs, and clear awareness of the next analytical improvements required.

### Recommended next version

Target the next analytical refinement as **v2** if the churn target definition and eligible population are materially redefined.

Recommended follow-up improvements after the v1 publication baseline:

- probability calibration;
- ROI-aware threshold optimization;
- uplift / incremental-response modeling;
- uncertainty-aware predictions;
- drift and data-quality monitoring;
- model card / decision card documentation;
- experiment tracking / lightweight model registry.

### Local post-v1 hardening note

After the published v1 baseline, the repository was further hardened around the canonical **V2C** candidate line and then synchronized to Drive as a verified backup/publication-ready workspace state.

That local hardening includes:

- completed downstream notebook chain through `NB09` on the canonical V2C formulation;
- deployment packaging aligned with percentile-based V2 operational tiers;
- orchestration payloads aligned with the confirmed retention strategy;
- monitoring dashboard aligned with the canonical V2C outputs;
- dependency hardening in `requirements.txt` including `psycopg2-binary`;
- Docker support via `Dockerfile` and `.dockerignore`;
- lightweight contract tests for `src/models/churn_scoring.py`;
- brand asset cleanup with `assets/images/logo.gif` replacing the previous `logo.png` reference set;
- verified Drive replication of the current project state.

This note is intentionally kept separate from the formal v1 baseline scope so the published baseline remains historically clear while the next release can present the V2C redesign explicitly.

### Phase 2 operational completion note — 2026-05-18

After the V2C analytical hardening, Phase 2 was closed with the successful end-to-end execution of the **n8n workflow V9** in a real production environment, using a two-workflow architecture.

The workflows (`n8n/n8n_workflow_daily_churn_retention_workflow.json` and `n8n/n8n_workflow_error_handler_workflow.json`) were executed and validated on 2026-05-18 against the following production stack:

- VPS: Hostinger, Ubuntu 24.04, IP 187.127.225.147
- Containers: `openclaw-opvz-openclaw-1` (scoring API, port 62881) + `n8n` (orchestration)
- Database: Postgres, `vivamarket` DB, `churn_predictions` table (3,346 rows loaded from `retention_actions_20260506.parquet`)
- Network: n8n connected to `openclaw-opvz_default` Docker network for internal API access

**Main pipeline (Daily Churn Retention Actions - V9) — all 12 nodes executed successfully:**

> Cron Trigger → Read Predictions (10 items) → Read SHAP Explainability → Merge Data → Risk Switch → Merge Risks → Generate Coupon → Validate Pre-Send → Send Email + Send Push → Log Actions + Log Skipped → [Error Workflow via Settings]

**Error Handler (VivaMarket Error Handler) — 2 nodes:**

> Error Trigger → Send Error Email

The two-workflow architecture was adopted after resolving a known n8n issue: the single-workflow pattern with an inline Error Handler node caused the n8n canvas engine to incorrectly auto-wire error connections as main connections. The solution was to move to n8n's native Error Workflow mechanism, connecting a fully independent error handler workflow through the Settings panel of the main V9 workflow.

Key fixes implemented between V5 and V9:
- **OneSignal credentials:** migrated from unsupported `$credentials.x` syntax to n8n Variables (`ONE_SIGNAL_API_KEY`, `ONE_SIGNAL_APP_ID`)
- **Postgres bindings:** parameterized `queryReplacement` added to Log Actions and Log Skipped nodes to properly bind `$1`, `$2`... parameters
- **Error handling:** moved from inline Error Handler node to dedicated `VivaMarket Error Handler` workflow via n8n native Error Workflow setting

**n8n is the internal orchestration platform for Phase 2.** It validates end-to-end operational readiness of the retention pipeline before the customer-facing delivery layer is implemented in Phase 3. The architecture deliberately separates internal pipeline orchestration (Layer 2, n8n) from customer-facing delivery (Layer 3, Phase 3), with the retention payload as the explicit contract between them.

Infrastructure notes documented in `_private/tech_doc.md`.
