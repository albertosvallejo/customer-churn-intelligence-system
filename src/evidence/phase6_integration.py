from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from evidence.recommendation_builder import (
    _resolve_catalog_path_for_run_date,
    _resolve_latest_catalog_path,
    build_recommendation_rows,
    load_catalog,
)
from pipeline.ab_testing_framework import run_ab_test

LOGGER = logging.getLogger(__name__)

ALLOWED_AUTOMATION_INTERVENTIONS = {"INT-01", "INT-02", "INT-04"}
DEFAULT_DEPLOYMENT_MODE = "simulated"
DEFAULT_BASELINE_P0 = 0.096
DEFAULT_GUARDRAIL_Q_THRESHOLD = 0.020
SIMULATED_SCENARIO_DEFAULTS = {
    "INT-01": "positive_lift",
    "INT-02": "positive_lift",
    "INT-04": "positive_lift",
}
SIMULATED_SCENARIOS = {
    "positive_lift": {
        "INT-01": {"control": {"n": 900, "converted": 90, "opt_out": 12}, "variant": {"n": 900, "converted": 117, "opt_out": 14}},
        "INT-02": {"control": {"n": 1200, "converted": 108, "opt_out": 14}, "variant": {"n": 1200, "converted": 144, "opt_out": 18}},
        "INT-04": {"control": {"n": 1000, "converted": 100, "opt_out": 15}, "variant": {"n": 1000, "converted": 125, "opt_out": 16}},
    },
    "no_signal": {
        "INT-01": {"control": {"n": 1200, "converted": 108, "opt_out": 12}, "variant": {"n": 1200, "converted": 111, "opt_out": 12}},
        "INT-02": {"control": {"n": 1200, "converted": 108, "opt_out": 14}, "variant": {"n": 1200, "converted": 110, "opt_out": 14}},
        "INT-04": {"control": {"n": 1200, "converted": 120, "opt_out": 15}, "variant": {"n": 1200, "converted": 121, "opt_out": 15}},
    },
    "guardrail_breach": {
        "INT-01": {"control": {"n": 1200, "converted": 108, "opt_out": 12}, "variant": {"n": 1200, "converted": 144, "opt_out": 32}},
        "INT-02": {"control": {"n": 1200, "converted": 108, "opt_out": 14}, "variant": {"n": 1200, "converted": 150, "opt_out": 36}},
        "INT-04": {"control": {"n": 1200, "converted": 120, "opt_out": 15}, "variant": {"n": 1200, "converted": 150, "opt_out": 30}},
    },
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _proposals_path(root: Path, run_date: str) -> Path:
    return root / "data" / "processed" / f"phase6_action_proposals_{run_date}.json"


def _proposal_summary_path(root: Path, run_date: str) -> Path:
    return root / "reports" / f"phase6_action_proposals_summary_{run_date}.md"


def _action_history_path(root: Path) -> Path:
    return root / "data" / "processed" / "action_history_log.parquet"


def _ab_test_runs_path(root: Path) -> Path:
    return root / "data" / "processed" / "phase6_ab_test_runs.parquet"


def _kpi_status_json_path(root: Path, run_date: str) -> Path:
    return root / "data" / "processed" / f"phase6_kpi_status_{run_date}.json"


def _kpi_status_md_path(root: Path, run_date: str) -> Path:
    return root / "reports" / f"phase6_kpi_status_{run_date}.md"


def _n8n_payload_path(root: Path, run_date: str) -> Path:
    return root / "data" / "processed" / f"phase6_n8n_payload_{run_date}.json"


def _resolve_catalog_and_run_date(project_root: Path, run_date: str | None) -> tuple[Path, str]:
    catalog_path = _resolve_catalog_path_for_run_date(run_date, project_root) if run_date else _resolve_latest_catalog_path(project_root)
    effective_run_date = run_date or catalog_path.stem.removeprefix("evidence_catalog_")
    return catalog_path, effective_run_date


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _append_history_record(root: Path, record: dict[str, Any]) -> None:
    history_path = _action_history_path(root)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    if history_path.exists():
        history_df = pd.read_parquet(history_path)
        history_df = pd.concat([history_df, pd.DataFrame([record])], ignore_index=True)
    else:
        history_df = pd.DataFrame([record])
    history_df.to_parquet(history_path, index=False)


def _load_ab_test_runs_frame(root: Path) -> pd.DataFrame:
    path = _ab_test_runs_path(root)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _make_arm(n: int, converted: int, opt_out: int) -> pd.DataFrame:
    conv_col = [1] * converted + [0] * (n - converted)
    opt_col = [1] * opt_out + [0] * (n - opt_out)
    return pd.DataFrame({"converted": conv_col, "opt_out": opt_col})


def build_action_proposals(project_root: Path | None = None, run_date: str | None = None) -> dict[str, Any]:
    """Build the first Phase 6.4 approval-gate proposal artifact from the latest eligible recommendations."""
    root = project_root or _project_root()
    catalog_path, effective_run_date = _resolve_catalog_and_run_date(root, run_date)
    catalog = load_catalog(catalog_path)
    rows = build_recommendation_rows(catalog)

    proposals: list[dict[str, Any]] = []
    for row in rows:
        if row["readiness"] != "approval_gate_eligible":
            continue
        if row["intervention_id"] not in ALLOWED_AUTOMATION_INTERVENTIONS:
            continue
        proposals.append(
            {
                "proposal_id": f"p6-{effective_run_date}-{uuid.uuid4().hex[:8]}",
                "proposal_run_date": effective_run_date,
                "created_at": _utc_now_iso(),
                "intervention_id": row["intervention_id"],
                "source_name": row["source_name"],
                "ref_id": row["ref_id"],
                "recommendation_tier": row["recommendation_tier"],
                "readiness": row["readiness"],
                "priority_score": row["priority_score"],
                "approval_required": True,
                "deployment_mode": DEFAULT_DEPLOYMENT_MODE,
                "copy_hypothesis": row.get("copy_hypothesis"),
                "channel_hypothesis": row.get("channel_hypothesis"),
                "timing_hypothesis": row.get("timing_hypothesis"),
                "incentive_hypothesis": row.get("incentive_hypothesis"),
                "evidence_note": row.get("evidence_note"),
                "effect_size_text": row.get("effect_size_text"),
                "decision_status": "pending",
                "decision_reason": None,
                "decided_by": None,
                "decision_ts": None,
            }
        )

    proposals_path = _proposals_path(root, effective_run_date)
    summary_path = _proposal_summary_path(root, effective_run_date)
    _write_json(proposals_path, proposals)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(render_action_proposals_summary(proposals, effective_run_date), encoding="utf-8")
    LOGGER.info("Wrote Phase 6.4 approval proposals to %s", proposals_path)
    return {
        "proposals_path": str(proposals_path),
        "summary_path": str(summary_path),
        "run_date": effective_run_date,
        "proposal_count": len(proposals),
    }


def render_action_proposals_summary(proposals: list[dict[str, Any]], run_date: str) -> str:
    lines = [
        "# PHASE 6 ACTION PROPOSALS SUMMARY",
        "",
        f"- Run date: {run_date}",
        f"- Deployment mode: {DEFAULT_DEPLOYMENT_MODE}",
        f"- Proposals generated: {len(proposals)}",
        "- Scope: only approval-gate-eligible recommendations for INT-01 / INT-02 / INT-04.",
        "",
        "## Proposals",
    ]
    if not proposals:
        lines.append("- No approval-gate-eligible proposals were generated for this run.")
    for proposal in proposals:
        lines.extend(
            [
                f"### {proposal['proposal_id']} — {proposal['intervention_id']}",
                f"- Source: {proposal['source_name']} ({proposal['ref_id']})",
                f"- Tier: {proposal['recommendation_tier']}",
                f"- Priority score: {proposal['priority_score']}",
                f"- Decision status: {proposal['decision_status']}",
                f"- Copy hypothesis: {proposal['copy_hypothesis']}",
                f"- Channel hypothesis: {proposal['channel_hypothesis']}",
                f"- Timing hypothesis: {proposal['timing_hypothesis']}",
                f"- Incentive hypothesis: {proposal['incentive_hypothesis']}",
                f"- Evidence note: {proposal['evidence_note']}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def load_action_proposals(project_root: Path | None = None, run_date: str | None = None) -> list[dict[str, Any]]:
    root = project_root or _project_root()
    if run_date:
        path = _proposals_path(root, run_date)
        if not path.exists():
            raise FileNotFoundError(f"no Phase 6 action proposals found for run_date {run_date}: {path}")
    else:
        candidates = sorted((root / "data" / "processed").glob("phase6_action_proposals_*.json"))
        if not candidates:
            raise FileNotFoundError("no Phase 6 action proposals found under data/processed")
        path = candidates[-1]
    return _read_json(path)


def record_action_decision(payload: dict[str, Any], project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _project_root()
    proposal_id = str(payload.get("proposal_id") or "").strip()
    decision_status = str(payload.get("decision_status") or "").strip().lower()
    decision_reason = str(payload.get("decision_reason") or "").strip()
    decided_by = str(payload.get("decided_by") or "").strip()
    run_date = str(payload.get("proposal_run_date") or "").strip() or None

    if not proposal_id:
        raise ValueError("proposal_id is required")
    if decision_status not in {"approved", "rejected", "postponed"}:
        raise ValueError("decision_status must be one of approved, rejected, postponed")
    if not decision_reason:
        raise ValueError("decision_reason is required")
    if not decided_by:
        raise ValueError("decided_by is required")

    proposals = load_action_proposals(root, run_date)
    matching = [proposal for proposal in proposals if proposal["proposal_id"] == proposal_id]
    if not matching:
        raise ValueError(f"proposal_id '{proposal_id}' was not found in the proposal artifact")
    proposal = matching[0]
    if proposal["decision_status"] != "pending":
        raise ValueError(f"proposal_id '{proposal_id}' already has decision_status '{proposal['decision_status']}'")

    decision_ts = _utc_now_iso()
    proposal["decision_status"] = decision_status
    proposal["decision_reason"] = decision_reason
    proposal["decided_by"] = decided_by
    proposal["decision_ts"] = decision_ts

    proposals_path = _proposals_path(root, proposal["proposal_run_date"])
    _write_json(proposals_path, proposals)
    _proposal_summary_path(root, proposal["proposal_run_date"]).write_text(
        render_action_proposals_summary(proposals, proposal["proposal_run_date"]),
        encoding="utf-8",
    )

    record = {
        "event_id": str(uuid.uuid4()),
        "event_type": "decision",
        "proposal_id": proposal_id,
        "proposal_run_date": proposal["proposal_run_date"],
        "decision_status": decision_status,
        "decision_reason": decision_reason,
        "decided_by": decided_by,
        "decision_ts": decision_ts,
        "deployment_mode": proposal["deployment_mode"],
        "intervention_id": proposal["intervention_id"],
        "source_name": proposal["source_name"],
        "ref_id": proposal["ref_id"],
        "recommendation_tier": proposal["recommendation_tier"],
        "priority_score": proposal["priority_score"],
        "ab_test_status": "not_started",
        "kpi_status": "not_started",
    }
    _append_history_record(root, record)
    LOGGER.info("Recorded Phase 6.4 decision for proposal %s", proposal_id)
    return record


def launch_ab_test(
    payload: dict[str, Any],
    project_root: Path | None = None,
    *,
    test_scenario_key: str | None = None,
) -> dict[str, Any]:
    """Launch a simulated Phase 6.4 A/B test for an approved proposal and persist the result.

    `test_scenario_key` is an internal-only injection point for tests and must not be exposed
    through the public HTTP API payload.
    """
    root = project_root or _project_root()
    proposal_id = str(payload.get("proposal_id") or "").strip()
    launched_by = str(payload.get("launched_by") or "").strip()
    run_date = str(payload.get("proposal_run_date") or "").strip() or None
    if not proposal_id:
        raise ValueError("proposal_id is required")
    if not launched_by:
        raise ValueError("launched_by is required")

    proposals = load_action_proposals(root, run_date)
    matching = [proposal for proposal in proposals if proposal["proposal_id"] == proposal_id]
    if not matching:
        raise ValueError(f"proposal_id '{proposal_id}' was not found in the proposal artifact")
    proposal = matching[0]
    if proposal["decision_status"] != "approved":
        raise ValueError("only approved proposals can launch an A/B test")
    if proposal["deployment_mode"] != DEFAULT_DEPLOYMENT_MODE:
        raise ValueError("only simulated deployment mode is supported in Phase 6.4")

    ab_runs = _load_ab_test_runs_frame(root)
    if not ab_runs.empty and (ab_runs["proposal_id"] == proposal_id).any():
        raise ValueError(f"proposal_id '{proposal_id}' already has a launched A/B test")

    effective_scenario_key = test_scenario_key or SIMULATED_SCENARIO_DEFAULTS.get(proposal["intervention_id"], "positive_lift")
    scenario_group = SIMULATED_SCENARIOS.get(effective_scenario_key)
    if scenario_group is None:
        raise ValueError(f"scenario_key '{effective_scenario_key}' is not configured")
    scenario = scenario_group.get(proposal["intervention_id"])
    if scenario is None:
        raise ValueError(
            f"no simulated scenario configured for intervention_id '{proposal['intervention_id']}' under scenario_key '{effective_scenario_key}'"
        )

    control = scenario["control"]
    variant = scenario["variant"]
    control_arm = _make_arm(control["n"], control["converted"], control["opt_out"])
    variant_arm = _make_arm(variant["n"], variant["converted"], variant["opt_out"])
    ab_result = run_ab_test(
        control_arm,
        variant_arm,
        baseline_p0=DEFAULT_BASELINE_P0,
        guardrail_q_threshold=DEFAULT_GUARDRAIL_Q_THRESHOLD,
    )

    launch_ts = _utc_now_iso()
    run_id = f"ab-{proposal['proposal_run_date']}-{uuid.uuid4().hex[:8]}"
    result = {
        "ab_test_run_id": run_id,
        "proposal_id": proposal_id,
        "proposal_run_date": proposal["proposal_run_date"],
        "intervention_id": proposal["intervention_id"],
        "deployment_mode": proposal["deployment_mode"],
        "launched_by": launched_by,
        "launch_ts": launch_ts,
        "status": "completed",
        "scenario_key": effective_scenario_key,
        "primary_kpi": "conversion_rate",
        "guardrail_kpi": "opt_out_rate",
        "control_n": control["n"],
        "variant_n": variant["n"],
        "control_conversion_rate": round(control["converted"] / control["n"], 6),
        "variant_conversion_rate": round(variant["converted"] / variant["n"], 6),
        "control_opt_out_rate": round(control["opt_out"] / control["n"], 6),
        "variant_opt_out_rate": round(variant["opt_out"] / variant["n"], 6),
        "verdict": ab_result["verdict"],
        "p_value": ab_result["p_value"],
        "power_achieved": ab_result["power_achieved"],
        "guardrail_breach": ab_result["guardrail_breach"],
        "guardrail_ci_low": ab_result["guardrail_ci"][0],
        "guardrail_ci_high": ab_result["guardrail_ci"][1],
        "test_used": ab_result["test_used"],
    }

    path = _ab_test_runs_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        runs_df = pd.read_parquet(path)
        runs_df = pd.concat([runs_df, pd.DataFrame([result])], ignore_index=True)
    else:
        runs_df = pd.DataFrame([result])
    runs_df.to_parquet(path, index=False)

    history_record = {
        "event_id": str(uuid.uuid4()),
        "event_type": "ab_test_result",
        "proposal_id": proposal_id,
        "proposal_run_date": proposal["proposal_run_date"],
        "decision_status": proposal["decision_status"],
        "decision_reason": proposal["decision_reason"],
        "decided_by": proposal["decided_by"],
        "decision_ts": proposal["decision_ts"],
        "deployment_mode": proposal["deployment_mode"],
        "intervention_id": proposal["intervention_id"],
        "source_name": proposal["source_name"],
        "ref_id": proposal["ref_id"],
        "recommendation_tier": proposal["recommendation_tier"],
        "priority_score": proposal["priority_score"],
        "ab_test_status": "completed",
        "kpi_status": "available",
        "ab_test_run_id": run_id,
        "launch_ts": launch_ts,
        "launched_by": launched_by,
        "scenario_key": effective_scenario_key,
        "verdict": result["verdict"],
        "p_value": result["p_value"],
        "power_achieved": result["power_achieved"],
        "guardrail_breach": result["guardrail_breach"],
        "control_conversion_rate": result["control_conversion_rate"],
        "variant_conversion_rate": result["variant_conversion_rate"],
        "control_opt_out_rate": result["control_opt_out_rate"],
        "variant_opt_out_rate": result["variant_opt_out_rate"],
    }
    _append_history_record(root, history_record)
    LOGGER.info("Launched simulated Phase 6.4 A/B test for proposal %s", proposal_id)
    return result


def build_kpi_status_view(project_root: Path | None = None) -> dict[str, Any]:
    """Build a latest KPI status view from the append-only history of simulated Phase 6.4 launches."""
    root = project_root or _project_root()
    runs_df = _load_ab_test_runs_frame(root)
    run_date = _utc_now_iso()[:10].replace("-", "")
    records: list[dict[str, Any]] = []
    if not runs_df.empty:
        for _, row in runs_df.sort_values(["launch_ts", "proposal_id"], ascending=[False, True]).iterrows():
            records.append(
                {
                    "ab_test_run_id": row["ab_test_run_id"],
                    "proposal_id": row["proposal_id"],
                    "intervention_id": row["intervention_id"],
                    "status": row["status"],
                    "deployment_mode": row["deployment_mode"],
                    "primary_kpi": row["primary_kpi"],
                    "guardrail_kpi": row["guardrail_kpi"],
                    "control_conversion_rate": row["control_conversion_rate"],
                    "variant_conversion_rate": row["variant_conversion_rate"],
                    "conversion_lift": round(row["variant_conversion_rate"] - row["control_conversion_rate"], 6),
                    "control_opt_out_rate": row["control_opt_out_rate"],
                    "variant_opt_out_rate": row["variant_opt_out_rate"],
                    "verdict": row["verdict"],
                    "guardrail_breach": bool(row["guardrail_breach"]),
                    "p_value": row["p_value"],
                    "power_achieved": row["power_achieved"],
                    "launch_ts": row["launch_ts"],
                }
            )

    payload = {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "deployment_mode": DEFAULT_DEPLOYMENT_MODE,
        "test_count": len(records),
        "records": records,
    }
    _write_json(_kpi_status_json_path(root, run_date), payload)
    _kpi_status_md_path(root, run_date).write_text(render_kpi_status_summary(payload), encoding="utf-8")
    return payload


def render_kpi_status_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# PHASE 6 KPI STATUS",
        "",
        f"- Generated at: {payload['generated_at']}",
        f"- Deployment mode: {payload['deployment_mode']}",
        f"- Tests tracked: {payload['test_count']}",
        "",
        "## Tests",
    ]
    if not payload["records"]:
        lines.append("- No simulated A/B tests have been launched yet.")
    for row in payload["records"]:
        lines.extend(
            [
                f"### {row['ab_test_run_id']} — {row['intervention_id']}",
                f"- Proposal: {row['proposal_id']}",
                f"- Status: {row['status']}",
                f"- Verdict: {row['verdict']}",
                f"- Conversion control vs variant: {row['control_conversion_rate']:.4f} → {row['variant_conversion_rate']:.4f}",
                f"- Conversion lift: {row['conversion_lift']:.4f}",
                f"- Opt-out control vs variant: {row['control_opt_out_rate']:.4f} → {row['variant_opt_out_rate']:.4f}",
                f"- Guardrail breach: {row['guardrail_breach']}",
                f"- p-value: {row['p_value']:.6f}",
                f"- Power achieved: {row['power_achieved']:.4f}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def build_n8n_action_payload(project_root: Path | None = None, run_date: str | None = None) -> dict[str, Any]:
    """Build a versioned n8n-ready payload from approved Phase 6.4 proposals."""
    root = project_root or _project_root()
    proposals = load_action_proposals(root, run_date)
    approved = [proposal for proposal in proposals if proposal["decision_status"] == "approved"]
    effective_run_date = run_date or (approved[0]["proposal_run_date"] if approved else proposals[0]["proposal_run_date"] if proposals else _utc_now_iso()[:10].replace("-", ""))
    runs_df = _load_ab_test_runs_frame(root)
    actions = []
    for proposal in approved:
        latest_run = None
        if not runs_df.empty:
            matching = runs_df.loc[runs_df["proposal_id"] == proposal["proposal_id"]]
            if not matching.empty:
                latest_run = matching.sort_values("launch_ts", ascending=False).iloc[0].to_dict()
        actions.append(
            {
                "proposal_id": proposal["proposal_id"],
                "intervention_id": proposal["intervention_id"],
                "deployment_mode": proposal["deployment_mode"],
                "decision_status": proposal["decision_status"],
                "copy_hypothesis": proposal["copy_hypothesis"],
                "channel_hypothesis": proposal["channel_hypothesis"],
                "timing_hypothesis": proposal["timing_hypothesis"],
                "incentive_hypothesis": proposal["incentive_hypothesis"],
                "ab_test_status": latest_run.get("status") if latest_run else "not_started",
                "latest_ab_test_run_id": latest_run.get("ab_test_run_id") if latest_run else None,
                "latest_verdict": latest_run.get("verdict") if latest_run else None,
            }
        )
    payload = {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "run_date": effective_run_date,
        "deployment_mode": DEFAULT_DEPLOYMENT_MODE,
        "action_count": len(actions),
        "actions": actions,
    }
    _write_json(_n8n_payload_path(root, effective_run_date), payload)
    return payload


def load_latest_kpi_status(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _project_root()
    candidates = sorted((root / "data" / "processed").glob("phase6_kpi_status_*.json"))
    if not candidates:
        return build_kpi_status_view(root)
    return _read_json(candidates[-1])


def load_latest_n8n_action_payload(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _project_root()
    candidates = sorted((root / "data" / "processed").glob("phase6_n8n_payload_*.json"))
    if not candidates:
        raise FileNotFoundError("no Phase 6 n8n payload found under data/processed")
    return _read_json(candidates[-1])


def load_action_history(project_root: Path | None = None) -> list[dict[str, Any]]:
    root = project_root or _project_root()
    history_path = _action_history_path(root)
    if not history_path.exists():
        return []
    return pd.read_parquet(history_path).to_dict(orient="records")
