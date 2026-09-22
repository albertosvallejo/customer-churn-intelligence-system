from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evidence.phase7_artifacts import (
    SYNTHETIC_DEMO_MODE,
    SYNTHETIC_FILENAME_PREFIX,
    phase7_namespace_dir,
)
from evidence.phase7_integration import (
    build_integrated_actions,
    build_phase7_kpi_status_view,
    build_phase7_n8n_payload,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_manifest(namespace_dir: Path, run_date: str, bundle_version: str) -> dict:
    artifact_names = {
        "phase7_source_snapshot": f"{SYNTHETIC_FILENAME_PREFIX}phase7_source_snapshot_{run_date}.json",
        "phase7_action_drafts": f"{SYNTHETIC_FILENAME_PREFIX}phase7_action_drafts_{run_date}.json",
        "phase6_kpi_status": f"{SYNTHETIC_FILENAME_PREFIX}phase6_kpi_status_{run_date}.json",
        "phase7_integrated_actions": f"{SYNTHETIC_FILENAME_PREFIX}phase7_integrated_actions_{run_date}.json",
        "phase7_kpi_status": f"{SYNTHETIC_FILENAME_PREFIX}phase7_kpi_status_{run_date}.json",
        "phase7_n8n_payload": f"{SYNTHETIC_FILENAME_PREFIX}phase7_n8n_payload_{run_date}.json",
        "phase7_stat_test_runs": f"{SYNTHETIC_FILENAME_PREFIX}phase7_stat_test_runs.parquet",
        "phase7_action_history_log": f"{SYNTHETIC_FILENAME_PREFIX}phase7_action_history_log.parquet",
        "phase7_stat_launch_requests": f"{SYNTHETIC_FILENAME_PREFIX}phase7_stat_launch_requests.parquet",
    }
    logical_date = f"{run_date[:4]}-{run_date[4:6]}-{run_date[6:8]}"
    return {
        "manifest_version": "phase7_synthetic_demo_v1",
        "bundle_version": bundle_version,
        "mode": SYNTHETIC_DEMO_MODE,
        "run_date": run_date,
        "logical_date": logical_date,
        "seed_version": f"synthetic_demo_seed_{run_date}",
        "generator_script": "scripts/build_phase7_synthetic_demo_bundle.py",
        "validation_script": "scripts/validate_phase7_synthetic_demo_manifest.py",
        "schema": {
            "phase7_source_snapshot": "json",
            "phase7_action_drafts": "json",
            "phase6_kpi_status": "json",
            "phase7_integrated_actions": "json",
            "phase7_kpi_status": "json",
            "phase7_n8n_payload": "json",
            "phase7_stat_test_runs": "parquet",
            "phase7_action_history_log": "parquet",
            "phase7_stat_launch_requests": "parquet",
        },
        "artifacts": {
            logical_name: {
                "name": file_name,
                "path": f"data/synthetic_demo/{file_name}",
                "sha256": _sha256_file(namespace_dir / file_name),
                "size_bytes": (namespace_dir / file_name).stat().st_size,
            }
            for logical_name, file_name in artifact_names.items()
        },
    }


def _prefix_existing_seed_files(namespace_dir: Path, run_date: str) -> None:
    for base_name in [
        f"phase7_source_snapshot_{run_date}.json",
        f"phase7_action_drafts_{run_date}.json",
        f"phase6_kpi_status_{run_date}.json",
    ]:
        src = namespace_dir / base_name
        dst = namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}{base_name}"
        if src.exists() and not dst.exists():
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def _remove_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def main() -> int:
    namespace_dir = phase7_namespace_dir(PROJECT_ROOT, SYNTHETIC_DEMO_MODE)
    draft_candidates = sorted(namespace_dir.glob("phase7_action_drafts_*.json"))
    prefixed_candidates = sorted(namespace_dir.glob(f"{SYNTHETIC_FILENAME_PREFIX}phase7_action_drafts_*.json"))
    seed_path = prefixed_candidates[-1] if prefixed_candidates else draft_candidates[-1]
    run_date = seed_path.name.removeprefix(SYNTHETIC_FILENAME_PREFIX).removeprefix("phase7_action_drafts_").removesuffix(".json")

    _prefix_existing_seed_files(namespace_dir, run_date)

    for generated_path in [
        namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_integrated_actions_{run_date}.json",
        namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_kpi_status_{run_date}.json",
        namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_n8n_payload_{run_date}.json",
        namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_stat_test_runs.parquet",
        namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_action_history_log.parquet",
        namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_stat_launch_requests.parquet",
        namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_manifest_{run_date}.json",
    ]:
        _remove_if_exists(generated_path)

    drafts_payload = _read_json(namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_action_drafts_{run_date}.json")
    kpi_payload = _read_json(namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase6_kpi_status_{run_date}.json")

    build_integrated_actions(project_root=PROJECT_ROOT, run_date=run_date, mode=SYNTHETIC_DEMO_MODE)
    integrated_path = namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_integrated_actions_{run_date}.json"
    integrated = _read_json(integrated_path)
    actions = integrated.get("actions", [])
    actions_by_proposal = {action["proposal_id"]: action for action in actions}

    records = kpi_payload.get("records", [])
    history_rows = []
    stat_rows = []

    for action in actions:
        draft = next((row for row in drafts_payload.get("drafts", []) if row.get("proposal_id") == action["proposal_id"]), {})
        for field in [
            "recommended_action",
            "primary_kpi",
            "recommended_kpi",
            "guardrail_kpi",
            "business_context",
            "guardrails",
            "result_summary",
            "synthetic_previous_action",
        ]:
            if draft.get(field) is not None:
                action[field] = draft.get(field)
        if draft.get("discarded_without_test"):
            action["approval_status"] = "rejected"
            action["decision_reason"] = draft.get("discard_reason")
            action["decided_by"] = "synthetic_demo_seed"
            action["decision_ts"] = drafts_payload.get("generated_at")
            action["stat_test_status"] = "blocked"
            action["launch_status"] = "not_started"
            action["lifecycle_state"] = "rejected"
            action["block_reason"] = "synthetic_demo_superseded"
            history_rows.append({
                "event_id": f"seed-{action['action_id']}-reject",
                "event_type": "governance_decision",
                "action_id": action["action_id"],
                "proposal_id": action["proposal_id"],
                "proposal_run_date": run_date,
                "decision_status": "rejected",
                "decision_reason": draft.get("discard_reason"),
                "decided_by": "synthetic_demo_seed",
                "decision_ts": drafts_payload.get("generated_at"),
                "lifecycle_state": action["lifecycle_state"],
            })
        else:
            draft_status = str(draft.get("status") or "").strip().lower()
            if draft_status in {"pending_test", "draft_ready"}:
                action["approval_status"] = "pending_review"
                action["decision_reason"] = None
                action["decided_by"] = None
                action["decision_ts"] = None
                action["lifecycle_state"] = "draft_ready_for_review"
                action["block_reason"] = None
            else:
                action["approval_status"] = "approved"
                action["decision_reason"] = "Synthetic demo governance seed"
                action["decided_by"] = "synthetic_demo_seed"
                action["decision_ts"] = drafts_payload.get("generated_at")
                history_rows.append({
                    "event_id": f"seed-{action['action_id']}-approve",
                    "event_type": "governance_decision",
                    "action_id": action["action_id"],
                    "proposal_id": action["proposal_id"],
                    "proposal_run_date": run_date,
                    "decision_status": "approved",
                    "decision_reason": "Synthetic demo governance seed",
                    "decided_by": "synthetic_demo_seed",
                    "decision_ts": drafts_payload.get("generated_at"),
                    "lifecycle_state": "approved_for_stat_test",
                })
                action["lifecycle_state"] = "approved_for_stat_test"
                action["block_reason"] = None

    for row in records:
        action = actions_by_proposal.get(row.get("proposal_id"))
        if not action:
            continue
        action["latest_stat_run_id"] = row["ab_test_run_id"]
        canonical_verdict = "insufficient_sample" if row.get("verdict") == "insufficient_power" else row.get("verdict")
        action["latest_verdict"] = canonical_verdict
        action["latest_conversion_lift"] = row.get("conversion_lift")
        action["launch_ts"] = row.get("launch_ts")
        action["latest_launch_ts"] = row.get("launch_ts")
        action["latest_stat_completed_at"] = row.get("launch_ts")
        action["guardrail_breach"] = bool(row.get("guardrail_breach"))
        action["stat_test_status"] = "completed"
        action["launch_status"] = "completed"
        action["lifecycle_state"] = "stat_test_completed"
        action["lifecycle_updated_at"] = row.get("launch_ts")
        stat_rows.append({
            "stat_test_run_id": row["ab_test_run_id"],
            "action_id": action["action_id"],
            "proposal_id": action["proposal_id"],
            "proposal_run_date": run_date,
            "launched_by": "synthetic_demo_seed",
            "launch_ts": row.get("launch_ts"),
            "baseline_p0": 0.096,
            "guardrail_q_threshold": 0.020,
            "control_n": 1000,
            "control_converted": round(float(row.get("control_conversion_rate", 0.0)) * 1000),
            "control_opt_out": round(float(row.get("control_opt_out_rate", 0.0)) * 1000),
            "variant_n": 1000,
            "variant_converted": round(float(row.get("variant_conversion_rate", 0.0)) * 1000),
            "variant_opt_out": round(float(row.get("variant_opt_out_rate", 0.0)) * 1000),
            "test_used": "synthetic_seed",
            "guardrail_breach": row.get("guardrail_breach"),
            "p_value": row.get("p_value"),
            "power_achieved": row.get("power_achieved"),
            "verdict": canonical_verdict,
            "conversion_lift": row.get("conversion_lift"),
        })
        history_rows.append({
            "event_id": f"seed-{action['action_id']}-stat",
            "event_type": "stat_test_completed",
            "action_id": action["action_id"],
            "proposal_id": action["proposal_id"],
            "proposal_run_date": run_date,
            "stat_test_run_id": row["ab_test_run_id"],
            "verdict": canonical_verdict,
            "launched_by": "synthetic_demo_seed",
            "launch_ts": row.get("launch_ts"),
            "lifecycle_state": action["lifecycle_state"],
        })

    integrated["generated_at"] = drafts_payload.get("generated_at")
    _write_json(integrated_path, integrated)

    pd.DataFrame(stat_rows).to_parquet(namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_stat_test_runs.parquet", index=False)
    pd.DataFrame(history_rows).to_parquet(namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_action_history_log.parquet", index=False)
    pd.DataFrame([], columns=[
        "launch_request_id", "action_id", "proposal_id", "proposal_run_date", "requested_by", "request_ts",
        "request_status", "executed_ts", "executed_by", "stat_test_run_id", "baseline_p0", "guardrail_q_threshold",
        "control_n", "control_converted", "control_opt_out", "variant_n", "variant_converted", "variant_opt_out"
    ]).to_parquet(namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_stat_launch_requests.parquet", index=False)

    build_phase7_kpi_status_view(PROJECT_ROOT, run_date=run_date, mode=SYNTHETIC_DEMO_MODE)
    build_phase7_n8n_payload(PROJECT_ROOT, run_date=run_date, mode=SYNTHETIC_DEMO_MODE)

    manifest = _build_manifest(namespace_dir, run_date, bundle_version=f"rebuild-{run_date}")
    _write_json(namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_manifest_{run_date}.json", manifest)
    _write_json(PROJECT_ROOT / "reports" / "reproducibility" / f"PHASE7_SYNTHETIC_DEMO_MANIFEST_{run_date}.json", manifest)

    LOGGER.info("Synthetic demo bundle refreshed for run_date=%s", run_date)
    print(json.dumps({
        "run_date": run_date,
        "mode": SYNTHETIC_DEMO_MODE,
        "integrated_actions_path": str(integrated_path),
        "stat_runs_path": str(namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_stat_test_runs.parquet"),
        "history_path": str(namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_action_history_log.parquet"),
        "manifest_path": str(namespace_dir / f"{SYNTHETIC_FILENAME_PREFIX}phase7_manifest_{run_date}.json"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
