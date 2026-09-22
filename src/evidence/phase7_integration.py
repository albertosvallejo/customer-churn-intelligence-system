from __future__ import annotations

import json
import logging
import copy
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from pipeline.ab_testing_framework import run_ab_test
from evidence.phase7_artifacts import (
    SYNTHETIC_WARNING,
    namespaced_artifact_path,
    namespaced_report_path,
    phase7_namespace_dir,
    SyntheticDemoManifestError,
    resolve_synthetic_manifest_run_date,
    resolve_synthetic_runtime_artifact,
    resolve_phase7_mode,
)

LOGGER = logging.getLogger(__name__)
INTEGRATED_ACTIONS_CACHE_TTL_SECONDS = 45.0
_INTEGRATED_ACTIONS_CACHE_LOCK = threading.Lock()
_INTEGRATED_ACTIONS_CACHE: Dict[str, Tuple[float, Tuple[int, int], Dict[str, Any]]] = {}

DEFAULT_BASELINE_P0 = 0.096
DEFAULT_GUARDRAIL_Q_THRESHOLD = 0.020
DEFAULT_PRIMARY_KPI = "conversion_rate"
DEFAULT_GUARDRAIL_KPI = "opt_out_rate"
DECIDED_APPROVAL_STATUSES = {"approved", "rejected", "postponed"}
DECISION_SNAPSHOT_FIELDS = {
    "source_name",
    "article_title",
    "article_url",
    "published_at",
    "summary_for_business",
    "pros",
    "cons",
    "recommended_action",
}
REQUIRED_DECISION_CONTEXT_FIELDS = (
    "primary_kpi",
    "recommended_action",
    "summary_for_business",
    "launch_ts",
    "latest_stat_completed_at",
    "latest_conversion_lift",
)
PERSISTED_STATE_FIELDS = {
    "created_at",
    "approval_required",
    "approval_status",
    "decision_reason",
    "decided_by",
    "decision_ts",
    "launch_status",
    "stat_test_status",
    "lifecycle_state",
    "lifecycle_updated_at",
    "latest_stat_run_id",
    "latest_verdict",
    "draft_content_changed_since_decision",
    "draft_refresh_blocked_reason",
    "comparison_target_action_id",
    "comparison_target_latest_stat_run_id",
    "comparison_outcome",
    "decision_type",
    "previous_incumbent_status",
    "post_test_decision_reason",
    "post_test_decided_by",
    "post_test_decision_ts",
    "post_test_decision_snapshot",
}
POST_TEST_DECISION_TYPES = {"promote_challenger", "keep_incumbent", "retest", "retire_candidate"}
POST_TEST_COMPARISON_OUTCOMES = {"candidate_wins", "incumbent_keeps", "inconclusive", "needs_retest"}
VERDICT_TO_ALLOWED_COMPARISON_OUTCOMES = {
    "B_wins": {"candidate_wins"},
    "A_wins": {"incumbent_keeps"},
    "not_recommended_guardrail": {"incumbent_keeps", "retire_candidate"},
    "no_significant_difference": {"inconclusive", "needs_retest"},
    "insufficient_sample": {"inconclusive", "needs_retest"},
}
ALLOWED_DECISIONS_BY_COMPARISON_OUTCOME = {
    "candidate_wins": {"promote_challenger", "retest"},
    "incumbent_keeps": {"keep_incumbent", "retire_candidate"},
    "inconclusive": {"keep_incumbent", "retest", "retire_candidate"},
    "needs_retest": {"retest", "keep_incumbent"},
}
# 7.2.2 decision (confirmed 2026-07-30, not inherited): an action counts as an
# "active incumbent" candidate for the post-test-decision comparison UI (page
# 2.2) only if it is both formally approved and currently occupying an active
# lifecycle slot — i.e. it either already won a previous post-test decision
# (`active_winner`) or was kept in place after one (`post_test_incumbent_retained`).
# A `pending_review` or merely `stat_test_status == "ready"` action is never an
# incumbent candidate on its own, even if approved, because it has not yet
# reached an active/decided state.
ACTIVE_INCUMBENT_LIFECYCLE_STATES = {"active_winner", "post_test_incumbent_retained"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _deterministic_phase7_generated_at(payload: Dict[str, Any], run_date: str, mode: str) -> str:
    seeded_generated_at = payload.get("generated_at")
    if mode == "synthetic_demo" and seeded_generated_at:
        return str(seeded_generated_at)
    if mode == "synthetic_demo":
        return f"{run_date[:4]}-{run_date[4:6]}-{run_date[6:8]}T00:00:00Z"
    return _utc_now_iso()


def _drafts_path(root: Path, run_date: str, mode: str | None = None) -> Path:
    return namespaced_artifact_path(root, f"phase7_action_drafts_{run_date}.json", resolve_phase7_mode(mode))


def _integrated_actions_path(root: Path, run_date: str, mode: str | None = None) -> Path:
    return namespaced_artifact_path(root, f"phase7_integrated_actions_{run_date}.json", resolve_phase7_mode(mode))


def _integrated_actions_report_path(root: Path, run_date: str, mode: str | None = None) -> Path:
    return namespaced_report_path(root, f"phase7_integrated_actions_{run_date}.md", resolve_phase7_mode(mode))


def _stat_runs_path(root: Path, mode: str | None = None) -> Path:
    return namespaced_artifact_path(root, "phase7_stat_test_runs.parquet", resolve_phase7_mode(mode))


def _phase7_action_history_path(root: Path, mode: str | None = None) -> Path:
    return namespaced_artifact_path(root, "phase7_action_history_log.parquet", resolve_phase7_mode(mode))


def _phase7_launch_requests_path(root: Path, mode: str | None = None) -> Path:
    return namespaced_artifact_path(root, "phase7_stat_launch_requests.parquet", resolve_phase7_mode(mode))


def _phase7_kpi_status_json_path(root: Path, run_date: str, mode: str | None = None) -> Path:
    return namespaced_artifact_path(root, f"phase7_kpi_status_{run_date}.json", resolve_phase7_mode(mode))


def _phase7_kpi_status_md_path(root: Path, run_date: str, mode: str | None = None) -> Path:
    return namespaced_report_path(root, f"phase7_kpi_status_{run_date}.md", resolve_phase7_mode(mode))


def _phase7_n8n_payload_path(root: Path, run_date: str, mode: str | None = None) -> Path:
    return namespaced_artifact_path(root, f"phase7_n8n_payload_{run_date}.json", resolve_phase7_mode(mode))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_default(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        return value.tolist()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8")


def _integrated_actions_cache_key(path: Path) -> str:
    return str(path.resolve(strict=False))


def _integrated_actions_file_signature(path: Path) -> Tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _get_cached_integrated_actions(path: Path) -> Dict[str, Any] | None:
    cache_key = _integrated_actions_cache_key(path)
    now = time.monotonic()
    current_signature = _integrated_actions_file_signature(path)
    with _INTEGRATED_ACTIONS_CACHE_LOCK:
        cached = _INTEGRATED_ACTIONS_CACHE.get(cache_key)
        if cached is None:
            return None
        expires_at, cached_signature, payload = cached
        if now >= expires_at or cached_signature != current_signature:
            _INTEGRATED_ACTIONS_CACHE.pop(cache_key, None)
            return None
        return copy.deepcopy(payload)


def _set_cached_integrated_actions(path: Path, payload: Dict[str, Any]) -> None:
    cache_key = _integrated_actions_cache_key(path)
    file_signature = _integrated_actions_file_signature(path)
    with _INTEGRATED_ACTIONS_CACHE_LOCK:
        _INTEGRATED_ACTIONS_CACHE[cache_key] = (
            time.monotonic() + INTEGRATED_ACTIONS_CACHE_TTL_SECONDS,
            file_signature,
            copy.deepcopy(payload),
        )


def _load_integrated_actions_uncached(path: Path) -> Dict[str, Any]:
    file_signature = _integrated_actions_file_signature(path)
    with _INTEGRATED_ACTIONS_CACHE_LOCK:
        cached = _INTEGRATED_ACTIONS_CACHE.get(_integrated_actions_cache_key(path))
        now = time.monotonic()
        if cached is not None:
            expires_at, cached_signature, payload = cached
            if now < expires_at and cached_signature == file_signature:
                return copy.deepcopy(payload)
            _INTEGRATED_ACTIONS_CACHE.pop(_integrated_actions_cache_key(path), None)

        payload = _read_json(path)
        _INTEGRATED_ACTIONS_CACHE[_integrated_actions_cache_key(path)] = (
            now + INTEGRATED_ACTIONS_CACHE_TTL_SECONDS,
            file_signature,
            copy.deepcopy(payload),
        )
        return copy.deepcopy(payload)


def _resolve_drafts_and_run_date(project_root: Path, run_date: str | None, mode: str | None = None) -> Tuple[Path, str]:
    resolved_mode = resolve_phase7_mode(mode)
    if run_date:
        path = _drafts_path(project_root, run_date, resolved_mode)
        if not path.exists():
            raise FileNotFoundError(f"no Phase 7 action drafts found for run_date {run_date}: {path}")
        return path, run_date
    if resolved_mode == "synthetic_demo":
        resolved_run_date = resolve_synthetic_manifest_run_date(project_root, run_date)
        return _drafts_path(project_root, resolved_run_date, resolved_mode), resolved_run_date
    namespace_dir = phase7_namespace_dir(project_root, resolved_mode)
    candidates = sorted(namespace_dir.glob(_drafts_path(project_root, "*", resolved_mode).name))
    if not candidates:
        raise FileNotFoundError(f"no Phase 7 action drafts found under {namespace_dir}")
    path = candidates[-1]
    resolved_name = path.name.removeprefix("synthetic_demo__")
    return path, resolved_name.removeprefix("phase7_action_drafts_").removesuffix(".json")


def _make_arm(n: int, converted: int, opt_out: int) -> pd.DataFrame:
    if converted > n or opt_out > n:
        raise ValueError("converted and opt_out counts must be <= n")
    conv_col = [1] * converted + [0] * (n - converted)
    opt_col = [1] * opt_out + [0] * (n - opt_out)
    return pd.DataFrame({"converted": conv_col, "opt_out": opt_col})


def _build_base_integrated_action(
    draft: Dict[str, Any],
    row: Dict[str, Any],
    run_date: str,
    generated_at: str,
) -> Dict[str, Any]:
    now_iso = generated_at
    passed = bool(row.get("passed", False))
    generation_contract_violation = bool(draft.get("generation_contract_violation", False))
    return {
        "action_id": f"P7-ACT-{draft['proposal_id'].split('-')[-1]}",
        "proposal_id": draft["proposal_id"],
        "proposal_run_date": run_date,
        "created_at": now_iso,
        "source_name": draft["source_name"],
        "article_title": draft["article_title"],
        "article_url": draft.get("article_url"),
        "published_at": draft.get("published_at"),
        "summary_for_business": draft.get("summary_for_business"),
        "pros": draft.get("pros", []),
        "cons": draft.get("cons", []),
        "recommended_action": draft.get("recommended_action", ""),
        "primary_kpi": draft.get("primary_kpi") or DEFAULT_PRIMARY_KPI,
        "recommended_kpi": draft.get("recommended_kpi") or draft.get("primary_kpi") or DEFAULT_PRIMARY_KPI,
        "guardrail_kpi": draft.get("guardrail_kpi") or DEFAULT_GUARDRAIL_KPI,
        "business_context": draft.get("business_context"),
        "guardrails": draft.get("guardrails") or [],
        "result_summary": draft.get("result_summary"),
        "synthetic_previous_action": draft.get("synthetic_previous_action"),
        "approval_required": True,
        "approval_status": "pending_review",
        "decision_reason": None,
        "decided_by": None,
        "decision_ts": None,
        "launch_status": "not_started",
        "lifecycle_state": "draft_ready_for_review",
        "lifecycle_updated_at": now_iso,
        "numeric_coherence_passed": passed,
        "generation_contract_violation": generation_contract_violation,
        "stat_test_status": "ready" if passed and not generation_contract_violation else "blocked",
        "block_reason": None if passed and not generation_contract_violation else "draft_validation_failed",
        "latest_stat_run_id": None,
        "latest_verdict": None,
        "draft_content_changed_since_decision": False,
        "draft_refresh_blocked_reason": None,
    }


def _action_content_snapshot(action: Dict[str, Any]) -> Dict[str, Any]:
    return {field: action.get(field) for field in DECISION_SNAPSHOT_FIELDS}


def _find_action(actions: List[Dict[str, Any]], action_id: str) -> Dict[str, Any]:
    matches = [action for action in actions if action["action_id"] == action_id]
    if not matches:
        raise ValueError(f"action_id '{action_id}' was not found in the integrated action artifact")
    return matches[0]


def _find_action_or_none(actions: List[Dict[str, Any]], action_id: str) -> Dict[str, Any] | None:
    matches = [action for action in actions if action["action_id"] == action_id]
    return matches[0] if matches else None


def _merge_integrated_action_with_persisted_state(
    base_action: Dict[str, Any],
    persisted_action: Dict[str, Any] | None,
) -> Dict[str, Any]:
    if not persisted_action:
        return base_action

    merged = dict(base_action)
    for field in PERSISTED_STATE_FIELDS:
        if field in persisted_action:
            merged[field] = persisted_action[field]

    if persisted_action.get("approval_status") in DECIDED_APPROVAL_STATUSES:
        persisted_snapshot = _action_content_snapshot(persisted_action)
        refreshed_snapshot = _action_content_snapshot(base_action)
        if persisted_snapshot != refreshed_snapshot:
            for field in DECISION_SNAPSHOT_FIELDS:
                merged[field] = persisted_action.get(field)
            merged["draft_content_changed_since_decision"] = True
            merged["draft_refresh_blocked_reason"] = "governance_snapshot_preserved"
        else:
            merged["draft_content_changed_since_decision"] = bool(
                persisted_action.get("draft_content_changed_since_decision", False)
            )
            merged["draft_refresh_blocked_reason"] = persisted_action.get("draft_refresh_blocked_reason")
        return merged

    merged["draft_content_changed_since_decision"] = False
    merged["draft_refresh_blocked_reason"] = None
    return merged


def _load_stat_runs_by_action_id(root: Path, mode: str | None = None) -> Dict[str, Dict[str, Any]]:
    path = _stat_runs_path(root, mode)
    if not path.exists():
        return {}
    frame = pd.read_parquet(path)
    if frame.empty:
        return {}
    latest_by_action: Dict[str, Dict[str, Any]] = {}
    for row in frame.to_dict(orient="records"):
        action_id = str(row.get("action_id") or "").strip()
        if not action_id:
            continue
        latest_by_action[action_id] = row
    return latest_by_action


def _enrich_integrated_action_with_stat_run(action: Dict[str, Any], stat_run: Dict[str, Any] | None) -> Dict[str, Any]:
    if not stat_run:
        return action
    enriched = dict(action)
    enriched["primary_kpi"] = stat_run.get("primary_kpi") or enriched.get("primary_kpi")
    enriched["recommended_kpi"] = enriched.get("recommended_kpi") or stat_run.get("primary_kpi")
    enriched["guardrail_kpi"] = stat_run.get("guardrail_kpi") or enriched.get("guardrail_kpi")
    enriched["guardrail_breach"] = bool(stat_run.get("guardrail_breach"))
    enriched["latest_conversion_lift"] = stat_run.get("conversion_lift")
    enriched["launch_ts"] = stat_run.get("launch_ts") or enriched.get("launch_ts")
    enriched["latest_launch_ts"] = stat_run.get("launch_ts") or enriched.get("latest_launch_ts")
    enriched["latest_stat_completed_at"] = stat_run.get("launch_ts") or enriched.get("latest_stat_completed_at")
    if stat_run.get("verdict"):
        enriched["latest_verdict"] = stat_run.get("verdict")
    if stat_run.get("stat_test_run_id"):
        enriched["latest_stat_run_id"] = stat_run.get("stat_test_run_id")
    return enriched


def _has_required_post_test_context(action: Dict[str, Any]) -> bool:
    for field in REQUIRED_DECISION_CONTEXT_FIELDS:
        value = action.get(field)
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
    return bool(action.get("synthetic_previous_action") or action.get("comparison_target_action_id") or action.get("approval_status") == "approved")


def build_integrated_actions(project_root: Path | None = None, run_date: str | None = None, mode: str | None = None) -> Dict[str, Any]:
    """Translate Phase 7 drafts into stat-engine-ready action candidates without duplicating verdict logic."""
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    drafts_path, effective_run_date = _resolve_drafts_and_run_date(root, run_date, resolved_mode)
    payload = _read_json(drafts_path)
    drafts = payload.get("drafts", [])
    generated_at = _deterministic_phase7_generated_at(payload, effective_run_date, resolved_mode)
    validation = {row["proposal_id"]: row for row in payload.get("validation", [])}
    persisted_actions_by_proposal_id: Dict[str, Dict[str, Any]] = {}
    integrated_path = _integrated_actions_path(root, effective_run_date, resolved_mode)
    if integrated_path.exists():
        persisted_payload = _read_json(integrated_path)
        persisted_actions_by_proposal_id = {
            action["proposal_id"]: action for action in persisted_payload.get("actions", []) if action.get("proposal_id")
        }

    stat_runs_by_action_id = _load_stat_runs_by_action_id(root, resolved_mode)
    actions: List[Dict[str, Any]] = []
    for draft in drafts:
        row = validation.get(draft["proposal_id"], {})
        base_action = _build_base_integrated_action(draft, row, effective_run_date, generated_at)
        merged_action = _merge_integrated_action_with_persisted_state(base_action, persisted_actions_by_proposal_id.get(draft["proposal_id"]))
        actions.append(_enrich_integrated_action_with_stat_run(merged_action, stat_runs_by_action_id.get(merged_action["action_id"])))

    integrated_payload = {
        "status": "ok",
        "generated_at": generated_at,
        "run_date": effective_run_date,
        "action_count": len(actions),
        "actions": actions,
        "mode": resolved_mode,
        "warning": SYNTHETIC_WARNING if resolved_mode == "synthetic_demo" else None,
    }
    integrated_actions_path = _integrated_actions_path(root, effective_run_date, resolved_mode)
    report_path = _integrated_actions_report_path(root, effective_run_date, resolved_mode)
    _write_json(integrated_actions_path, integrated_payload)
    _set_cached_integrated_actions(integrated_actions_path, integrated_payload)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_integrated_actions_report(integrated_payload), encoding="utf-8")
    LOGGER.info("Wrote Phase 7 integrated actions to %s", integrated_actions_path)
    return {
        "integrated_actions_path": str(integrated_actions_path),
        "report_path": str(report_path),
        "run_date": effective_run_date,
        "action_count": len(actions),
        "mode": resolved_mode,
    }


def render_integrated_actions_report(payload: Dict[str, Any]) -> str:
    lines = [
        "# PHASE 7 INTEGRATED ACTIONS",
        "",
        f"- Run date: {payload['run_date']}",
        f"- Action count: {payload['action_count']}",
        "- Statistical engine: reused via pipeline.ab_testing_framework.run_ab_test",
        "",
        "## Actions",
    ]
    for action in payload.get("actions", []):
        lines.extend(
            [
                f"### {action['action_id']} — {action['source_name']}",
                f"- Proposal source: {action['proposal_id']}",
                f"- Title: {action['article_title']}",
                f"- Approval status: {action.get('approval_status', 'legacy_untracked')}",
                f"- Lifecycle state: {action.get('lifecycle_state', 'legacy_untracked')}",
                f"- Launch status: {action.get('launch_status', 'legacy_untracked')}",
                f"- Stat test status: {action['stat_test_status']}",
                f"- Latest verdict: {action['latest_verdict'] or 'none'}",
                f"- Recommended action: {action['recommended_action']}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def load_integrated_actions(project_root: Path | None = None, run_date: str | None = None, mode: str | None = None) -> Dict[str, Any]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    if resolved_mode == "synthetic_demo":
        try:
            effective_run_date = resolve_synthetic_manifest_run_date(root, run_date)
            path = resolve_synthetic_runtime_artifact(root, "phase7_integrated_actions", effective_run_date)
        except SyntheticDemoManifestError:
            if not run_date:
                raise
            effective_run_date = run_date
            path = _integrated_actions_path(root, effective_run_date, resolved_mode)
    else:
        _, effective_run_date = _resolve_drafts_and_run_date(root, run_date, resolved_mode)
        path = _integrated_actions_path(root, effective_run_date, resolved_mode)
    if not path.exists():
        raise FileNotFoundError(f"no Phase 7 integrated actions found for run_date {effective_run_date}: {path}")
    cached = _get_cached_integrated_actions(path)
    if cached is not None:
        return cached
    return _load_integrated_actions_uncached(path)


def _load_stat_runs_frame(root: Path, mode: str | None = None) -> pd.DataFrame:
    resolved_mode = resolve_phase7_mode(mode)
    if resolved_mode == "synthetic_demo":
        try:
            path = resolve_synthetic_runtime_artifact(root, "phase7_stat_test_runs")
        except SyntheticDemoManifestError:
            path = _stat_runs_path(root, resolved_mode)
    else:
        path = _stat_runs_path(root, resolved_mode)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _save_stat_runs_frame(root: Path, frame: pd.DataFrame, mode: str | None = None) -> None:
    path = _stat_runs_path(root, resolve_phase7_mode(mode))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def _append_phase7_history_record(root: Path, record: Dict[str, Any], mode: str | None = None) -> None:
    path = _phase7_action_history_path(root, resolve_phase7_mode(mode))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        history_df = pd.read_parquet(path)
        history_df = pd.concat([history_df, pd.DataFrame([record])], ignore_index=True)
    else:
        history_df = pd.DataFrame([record])
    history_df.to_parquet(path, index=False)


def _load_phase7_history_frame(root: Path, mode: str | None = None) -> pd.DataFrame:
    resolved_mode = resolve_phase7_mode(mode)
    if resolved_mode == "synthetic_demo":
        try:
            path = resolve_synthetic_runtime_artifact(root, "phase7_action_history_log")
        except SyntheticDemoManifestError:
            path = _phase7_action_history_path(root, resolved_mode)
    else:
        path = _phase7_action_history_path(root, resolved_mode)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _load_phase7_launch_requests_frame(root: Path, mode: str | None = None) -> pd.DataFrame:
    resolved_mode = resolve_phase7_mode(mode)
    if resolved_mode == "synthetic_demo":
        try:
            path = resolve_synthetic_runtime_artifact(root, "phase7_stat_launch_requests")
        except SyntheticDemoManifestError:
            path = _phase7_launch_requests_path(root, resolved_mode)
    else:
        path = _phase7_launch_requests_path(root, resolved_mode)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _save_phase7_launch_requests_frame(root: Path, frame: pd.DataFrame, mode: str | None = None) -> None:
    path = _phase7_launch_requests_path(root, resolve_phase7_mode(mode))
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def load_phase7_stat_test_runs(project_root: Path | None = None, mode: str | None = None) -> List[Dict[str, Any]]:
    root = project_root or _project_root()
    runs_df = _load_stat_runs_frame(root, mode)
    if runs_df.empty:
        return []
    return runs_df.to_dict(orient="records")


def _phase7_history_visibility_status(record: Dict[str, Any]) -> str:
    event_type = str(record.get("event_type") or "").strip()
    decision_status = str(record.get("decision_status") or "").strip().lower()
    decision_type = str(record.get("decision_type") or "").strip()

    if event_type == "stat_launch_requested":
        return "hidden_pending_data"
    if event_type == "governance_decision" and decision_status in {"rejected", "postponed"}:
        return "visible_discarded_once"
    if event_type == "post_test_decision" and decision_type == "retire_candidate":
        return "visible_discarded_once"
    if event_type in {"governance_decision", "stat_test_completed", "post_test_decision"}:
        return "visible"
    return "hidden_unsupported"


def _is_phase7_history_record_visible(record: Dict[str, Any]) -> bool:
    return _phase7_history_visibility_status(record).startswith("visible")


def load_phase7_action_history(project_root: Path | None = None, run_date: str | None = None, mode: str | None = None) -> List[Dict[str, Any]]:
    root = project_root or _project_root()
    history_df = _load_phase7_history_frame(root, mode)
    if history_df.empty:
        return []
    records = history_df.to_dict(orient="records")
    if run_date:
        records = [row for row in records if row.get("proposal_run_date") == run_date]

    visible_records: List[Dict[str, Any]] = []
    for row in records:
        visibility_status = _phase7_history_visibility_status(row)
        enriched_row = dict(row)
        enriched_row["visibility_status"] = visibility_status
        if _is_phase7_history_record_visible(enriched_row):
            visible_records.append(enriched_row)
    return json.loads(json.dumps(visible_records, default=_json_default))


def record_phase7_post_test_decision(payload: Dict[str, Any], project_root: Path | None = None, mode: str | None = None) -> Dict[str, Any]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    action_id = str(payload.get("action_id") or "").strip()
    comparison_target_action_id = str(payload.get("comparison_target_action_id") or "").strip()
    comparison_outcome = str(payload.get("comparison_outcome") or "").strip()
    decision_type = str(payload.get("decision_type") or "").strip()
    previous_incumbent_status = str(payload.get("previous_incumbent_status") or "").strip() or None
    decision_reason = str(payload.get("decision_reason") or "").strip()
    decided_by = str(payload.get("decided_by") or "").strip()
    run_date = str(payload.get("proposal_run_date") or "").strip() or None

    if not action_id:
        raise ValueError("action_id is required")
    if not comparison_target_action_id:
        raise ValueError("comparison_target_action_id is required")
    if comparison_target_action_id == action_id:
        raise ValueError("comparison_target_action_id must be different from action_id")
    if comparison_outcome not in POST_TEST_COMPARISON_OUTCOMES:
        raise ValueError("comparison_outcome must be one of candidate_wins, incumbent_keeps, inconclusive, needs_retest")
    if decision_type not in POST_TEST_DECISION_TYPES:
        raise ValueError("decision_type must be one of promote_challenger, keep_incumbent, retest, retire_candidate")
    if not decision_reason:
        raise ValueError("decision_reason is required")
    if not decided_by:
        raise ValueError("decided_by is required")
    if decision_type == "promote_challenger" and not previous_incumbent_status:
        raise ValueError("previous_incumbent_status is required when decision_type is promote_challenger")

    integrated = load_integrated_actions(root, run_date, resolved_mode)
    actions = integrated.get("actions", [])
    challenger = _find_action(actions, action_id)
    incumbent = _find_action_or_none(actions, comparison_target_action_id) or {}

    if challenger.get("launch_status") != "completed" or not challenger.get("latest_stat_run_id"):
        raise ValueError(f"action_id '{action_id}' does not have a completed statistical run")
    synthetic_previous_action = challenger.get("synthetic_previous_action") or {}
    synthetic_target_matches = comparison_target_action_id and comparison_target_action_id == synthetic_previous_action.get("action_id")
    if not synthetic_target_matches and incumbent.get("approval_status") != "approved":
        raise ValueError(f"comparison_target_action_id '{comparison_target_action_id}' is not in an approved incumbent state")

    latest_verdict = challenger.get("latest_verdict")
    if latest_verdict not in VERDICT_TO_ALLOWED_COMPARISON_OUTCOMES:
        raise ValueError(
            f"unknown latest_verdict '{latest_verdict}'; comparison_outcome cannot be validated"
        )
    allowed_outcomes = VERDICT_TO_ALLOWED_COMPARISON_OUTCOMES[latest_verdict]
    if comparison_outcome not in allowed_outcomes:
        raise ValueError(
            f"comparison_outcome '{comparison_outcome}' is incompatible with latest_verdict '{latest_verdict}'"
        )

    if decision_type not in ALLOWED_DECISIONS_BY_COMPARISON_OUTCOME[comparison_outcome]:
        raise ValueError(
            f"decision_type '{decision_type}' is incompatible with comparison_outcome '{comparison_outcome}'"
        )

    decision_ts = _utc_now_iso()
    snapshot = {
        "challenger_action_id": challenger["action_id"],
        "challenger_latest_stat_run_id": challenger.get("latest_stat_run_id"),
        "challenger_latest_verdict": challenger.get("latest_verdict"),
        "incumbent_action_id": comparison_target_action_id,
        "incumbent_latest_stat_run_id": incumbent.get("latest_stat_run_id") if not synthetic_target_matches else synthetic_previous_action.get("latest_stat_run_id"),
        "comparison_outcome": comparison_outcome,
        "decision_type": decision_type,
    }

    challenger["comparison_target_action_id"] = comparison_target_action_id
    challenger["comparison_target_latest_stat_run_id"] = incumbent.get("latest_stat_run_id") if not synthetic_target_matches else synthetic_previous_action.get("latest_stat_run_id")
    challenger["comparison_outcome"] = comparison_outcome
    challenger["decision_type"] = decision_type
    challenger["previous_incumbent_status"] = previous_incumbent_status
    challenger["post_test_decision_reason"] = decision_reason
    challenger["post_test_decided_by"] = decided_by
    challenger["post_test_decision_ts"] = decision_ts
    challenger["post_test_decision_snapshot"] = snapshot
    challenger["lifecycle_updated_at"] = decision_ts

    if decision_type == "promote_challenger":
        challenger["lifecycle_state"] = "active_winner"
        challenger["launch_status"] = "promoted"
        if not synthetic_target_matches:
            incumbent["lifecycle_state"] = previous_incumbent_status
            incumbent["launch_status"] = previous_incumbent_status
            incumbent["lifecycle_updated_at"] = decision_ts
    elif decision_type == "keep_incumbent":
        if synthetic_target_matches:
            challenger["lifecycle_state"] = "candidate_retired"
            challenger["launch_status"] = "retired"
            challenger["stat_test_status"] = "blocked"
            challenger["block_reason"] = "incumbent_retained_post_test"
        else:
            challenger["lifecycle_state"] = "post_test_incumbent_retained"
            challenger["launch_status"] = "completed"
    elif decision_type == "retest":
        challenger["lifecycle_state"] = "post_test_retest_required"
        challenger["launch_status"] = "not_started"
    else:
        challenger["lifecycle_state"] = "candidate_retired"
        challenger["launch_status"] = "retired"
        challenger["stat_test_status"] = "blocked"
        challenger["block_reason"] = "candidate_retired_post_test"

    integrated["generated_at"] = _utc_now_iso()
    integrated_path = _integrated_actions_path(root, integrated["run_date"], resolved_mode)
    _write_json(integrated_path, integrated)
    _set_cached_integrated_actions(integrated_path, integrated)
    report_path = _integrated_actions_report_path(root, integrated["run_date"], resolved_mode)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_integrated_actions_report(integrated), encoding="utf-8")

    record = {
        "event_id": str(uuid.uuid4()),
        "event_type": "post_test_decision",
        "action_id": action_id,
        "proposal_id": challenger["proposal_id"],
        "proposal_run_date": integrated["run_date"],
        "comparison_target_action_id": comparison_target_action_id,
        "comparison_target_latest_stat_run_id": incumbent.get("latest_stat_run_id") if not synthetic_target_matches else synthetic_previous_action.get("latest_stat_run_id"),
        "comparison_outcome": comparison_outcome,
        "decision_type": decision_type,
        "previous_incumbent_status": previous_incumbent_status,
        "decision_reason": decision_reason,
        "decided_by": decided_by,
        "decision_ts": decision_ts,
        "lifecycle_state": challenger["lifecycle_state"],
    }
    _append_phase7_history_record(root, record, resolved_mode)
    return record


def _is_active_incumbent_candidate(action: Dict[str, Any]) -> bool:
    return (
        action.get("approval_status") == "approved"
        and action.get("lifecycle_state") in ACTIVE_INCUMBENT_LIFECYCLE_STATES
    )


def _is_pending_post_test_decision(action: Dict[str, Any]) -> bool:
    # A challenger is "pending" for page 2.2 exactly when it has a completed
    # stat run with a recognized verdict, and no decision_type has been
    # recorded for it yet (record_phase7_post_test_decision writes
    # decision_type onto the action once a decision lands).
    return (
        action.get("lifecycle_state") == "stat_test_completed"
        and action.get("latest_verdict") == "B_wins"
        and not action.get("decision_type")
        and _has_required_post_test_context(action)
    )


def build_phase7_post_test_decision_queue(
    project_root: Path | None = None,
    run_date: str | None = None,
    mode: str | None = None,
    integrated_actions_payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """7.2.2 read contract: formalizes, as a server-resolved payload, what page 2.2
    needs to render 'winners pending post-test-decision against the active action'.
    Does not write anything; the actual decision is still made via
    record_phase7_post_test_decision (POST /phase7/actions/post-test-decision)."""
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    integrated = integrated_actions_payload if integrated_actions_payload is not None else load_integrated_actions(root, run_date, resolved_mode)
    actions = integrated.get("actions", [])
    incumbent_candidates = [action for action in actions if _is_active_incumbent_candidate(action)]

    pending_entries: List[Dict[str, Any]] = []
    for action in actions:
        if not _is_pending_post_test_decision(action):
            continue
        previous_action = action.get("synthetic_previous_action") or next(
            (
                {
                    "action_id": incumbent["action_id"],
                    "proposal_id": incumbent.get("proposal_id"),
                    "article_title": incumbent.get("article_title"),
                    "status_label": "Current action",
                    "summary": incumbent.get("summary_for_business"),
                    "latest_stat_run_id": incumbent.get("latest_stat_run_id"),
                }
                for incumbent in incumbent_candidates
                if incumbent["action_id"] != action["action_id"]
            ),
            {},
        )
        latest_verdict = str(action.get("latest_verdict") or "").strip()
        allowed_outcomes = sorted(VERDICT_TO_ALLOWED_COMPARISON_OUTCOMES.get(latest_verdict, set()))
        allowed_decisions = {
            outcome: sorted(ALLOWED_DECISIONS_BY_COMPARISON_OUTCOME.get(outcome, set()))
            for outcome in allowed_outcomes
        }
        pending_entries.append(
            {
                "action_id": action["action_id"],
                "proposal_id": action["proposal_id"],
                "article_title": action["article_title"],
                "latest_stat_run_id": action.get("latest_stat_run_id"),
                "latest_verdict": latest_verdict,
                "allowed_comparison_outcomes": allowed_outcomes,
                "allowed_decisions_by_comparison_outcome": allowed_decisions,
                "candidate_incumbents": [previous_action] if previous_action else [],
            }
        )

    payload = {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "run_date": integrated["run_date"],
        "pending_count": len(pending_entries),
        "pending_decisions": pending_entries,
    }
    return json.loads(json.dumps(payload, default=_json_default))


def load_phase7_launch_requests(project_root: Path | None = None, run_date: str | None = None, mode: str | None = None) -> List[Dict[str, Any]]:
    root = project_root or _project_root()
    frame = _load_phase7_launch_requests_frame(root, mode)
    if frame.empty:
        return []
    records = frame.to_dict(orient="records")
    if run_date:
        records = [row for row in records if row.get("proposal_run_date") == run_date]
    return json.loads(json.dumps(records, default=_json_default))


def record_phase7_action_decision(payload: Dict[str, Any], project_root: Path | None = None, mode: str | None = None) -> Dict[str, Any]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    action_id = str(payload.get("action_id") or "").strip()
    decision_status = str(payload.get("decision_status") or "").strip().lower()
    decision_reason = str(payload.get("decision_reason") or "").strip()
    decided_by = str(payload.get("decided_by") or "").strip()
    run_date = str(payload.get("proposal_run_date") or "").strip() or None

    if not action_id:
        raise ValueError("action_id is required")
    if decision_status not in {"approved", "rejected", "postponed"}:
        raise ValueError("decision_status must be one of approved, rejected, postponed")
    if not decision_reason:
        raise ValueError("decision_reason is required")
    if not decided_by:
        raise ValueError("decided_by is required")

    integrated = load_integrated_actions(root, run_date, resolved_mode)
    action = _find_action(integrated.get("actions", []), action_id)
    if action.get("approval_status") != "pending_review":
        raise ValueError(f"action_id '{action_id}' already has approval_status '{action.get('approval_status')}'")

    decision_ts = _utc_now_iso()
    action["approval_status"] = decision_status
    action["decision_reason"] = decision_reason
    action["decided_by"] = decided_by
    action["decision_ts"] = decision_ts
    action["lifecycle_updated_at"] = decision_ts
    if decision_status == "approved":
        action["lifecycle_state"] = "approved_for_stat_test"
    elif decision_status == "rejected":
        action["lifecycle_state"] = "rejected"
        action["stat_test_status"] = "blocked"
        action["block_reason"] = "business_rejected"
    else:
        action["lifecycle_state"] = "postponed"
        action["stat_test_status"] = "blocked"
        action["block_reason"] = "business_postponed"

    integrated["generated_at"] = _utc_now_iso()
    integrated_path = _integrated_actions_path(root, integrated["run_date"], resolved_mode)
    _write_json(integrated_path, integrated)
    _set_cached_integrated_actions(integrated_path, integrated)
    report_path = _integrated_actions_report_path(root, integrated["run_date"], resolved_mode)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_integrated_actions_report(integrated), encoding="utf-8")

    record = {
        "event_id": str(uuid.uuid4()),
        "event_type": "governance_decision",
        "action_id": action_id,
        "proposal_id": action["proposal_id"],
        "proposal_run_date": integrated["run_date"],
        "decision_status": decision_status,
        "decision_reason": decision_reason,
        "decided_by": decided_by,
        "decision_ts": decision_ts,
        "lifecycle_state": action["lifecycle_state"],
    }
    _append_phase7_history_record(root, record, resolved_mode)
    return record


def create_phase7_stat_launch_request(payload: Dict[str, Any], project_root: Path | None = None, mode: str | None = None) -> Dict[str, Any]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    action_id = str(payload.get("action_id") or "").strip()
    run_date = str(payload.get("proposal_run_date") or "").strip() or None
    requested_by = str(payload.get("requested_by") or "").strip()
    if not action_id:
        raise ValueError("action_id is required")
    if not requested_by:
        raise ValueError("requested_by is required")

    integrated = load_integrated_actions(root, run_date, resolved_mode)
    matches = [action for action in integrated.get("actions", []) if action["action_id"] == action_id]
    if not matches:
        raise ValueError(f"action_id '{action_id}' was not found in the integrated action artifact")
    action = matches[0]
    if action.get("approval_required", False) and action.get("approval_status") != "approved":
        raise ValueError(f"action_id '{action_id}' is not approved for launch request creation")
    if action.get("launch_status") == "completed":
        raise ValueError(f"action_id '{action_id}' already has a completed statistical launch")

    requests_df = _load_phase7_launch_requests_frame(root, resolved_mode)
    if not requests_df.empty and ((requests_df["action_id"] == action_id) & (requests_df["request_status"] == "pending_execution")).any():
        raise ValueError(f"action_id '{action_id}' already has a pending launch request")

    request_ts = _utc_now_iso()
    record = {
        "launch_request_id": f"p7-launch-{integrated['run_date']}-{uuid.uuid4().hex[:8]}",
        "action_id": action_id,
        "proposal_id": action["proposal_id"],
        "proposal_run_date": integrated["run_date"],
        "requested_by": requested_by,
        "request_ts": request_ts,
        "request_status": "pending_execution",
        "executed_ts": None,
        "executed_by": None,
        "stat_test_run_id": None,
        "baseline_p0": float(payload.get("baseline_p0", DEFAULT_BASELINE_P0)),
        "guardrail_q_threshold": float(payload.get("guardrail_q_threshold", DEFAULT_GUARDRAIL_Q_THRESHOLD)),
        "control_n": int(payload.get("control_n")),
        "control_converted": int(payload.get("control_converted")),
        "control_opt_out": int(payload.get("control_opt_out")),
        "variant_n": int(payload.get("variant_n")),
        "variant_converted": int(payload.get("variant_converted")),
        "variant_opt_out": int(payload.get("variant_opt_out")),
    }
    requests_df = pd.concat([requests_df, pd.DataFrame([record])], ignore_index=True) if not requests_df.empty else pd.DataFrame([record])
    _save_phase7_launch_requests_frame(root, requests_df, resolved_mode)

    action["launch_status"] = "pending_execution"
    action["lifecycle_state"] = "launch_requested"
    action["lifecycle_updated_at"] = request_ts
    integrated["generated_at"] = _utc_now_iso()
    integrated_path = _integrated_actions_path(root, integrated["run_date"], resolved_mode)
    _write_json(integrated_path, integrated)
    _set_cached_integrated_actions(integrated_path, integrated)
    report_path = _integrated_actions_report_path(root, integrated["run_date"], resolved_mode)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_integrated_actions_report(integrated), encoding="utf-8")

    _append_phase7_history_record(
        root,
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "stat_launch_requested",
            "action_id": action_id,
            "proposal_id": action["proposal_id"],
            "proposal_run_date": integrated["run_date"],
            "launch_request_id": record["launch_request_id"],
            "requested_by": requested_by,
            "request_ts": request_ts,
            "lifecycle_state": action["lifecycle_state"],
        },
        resolved_mode,
    )
    return json.loads(json.dumps(record, default=_json_default))


def execute_phase7_stat_launch_request(payload: Dict[str, Any], project_root: Path | None = None, mode: str | None = None) -> Dict[str, Any]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    launch_request_id = str(payload.get("launch_request_id") or "").strip()
    executed_by = str(payload.get("executed_by") or payload.get("launched_by") or "").strip()
    if not launch_request_id:
        raise ValueError("launch_request_id is required")
    if not executed_by:
        raise ValueError("executed_by is required")

    requests_df = _load_phase7_launch_requests_frame(root, resolved_mode)
    if requests_df.empty:
        raise ValueError("no Phase 7 launch requests are available")
    matches = requests_df[requests_df["launch_request_id"] == launch_request_id]
    if matches.empty:
        raise ValueError(f"launch_request_id '{launch_request_id}' was not found")
    idx = matches.index[0]
    request_row = matches.iloc[0].to_dict()
    if request_row.get("request_status") != "pending_execution":
        raise ValueError(f"launch_request_id '{launch_request_id}' is not pending execution")

    result = evaluate_integrated_action(
        {
            "action_id": request_row["action_id"],
            "proposal_run_date": request_row["proposal_run_date"],
            "launched_by": executed_by,
            "baseline_p0": request_row["baseline_p0"],
            "guardrail_q_threshold": request_row["guardrail_q_threshold"],
            "control_n": request_row["control_n"],
            "control_converted": request_row["control_converted"],
            "control_opt_out": request_row["control_opt_out"],
            "variant_n": request_row["variant_n"],
            "variant_converted": request_row["variant_converted"],
            "variant_opt_out": request_row["variant_opt_out"],
        },
        project_root=root,
        mode=resolved_mode,
    )

    executed_ts = _utc_now_iso()
    requests_df.loc[idx, "request_status"] = "executed"
    requests_df.loc[idx, "executed_ts"] = executed_ts
    requests_df.loc[idx, "executed_by"] = executed_by
    requests_df.loc[idx, "stat_test_run_id"] = result["stat_test_run_id"]
    _save_phase7_launch_requests_frame(root, requests_df, resolved_mode)
    return result


def build_phase7_stat_summary(project_root: Path | None = None, run_date: str | None = None, mode: str | None = None) -> Dict[str, Any]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    integrated = load_integrated_actions(root, run_date, resolved_mode)
    runs = load_phase7_stat_test_runs(root, resolved_mode)
    effective_run_date = integrated["run_date"]
    relevant_runs = [run for run in runs if run.get("proposal_run_date") == effective_run_date]
    payload = {
        "status": "ok",
        "generated_at": _deterministic_phase7_generated_at(integrated, effective_run_date, resolved_mode),
        "run_date": effective_run_date,
        "action_count": integrated.get("action_count", len(integrated.get("actions", []))),
        "evaluated_action_count": len([action for action in integrated.get("actions", []) if action.get("latest_stat_run_id")]),
        "stat_run_count": len(relevant_runs),
        "records": relevant_runs,
        "mode": resolved_mode,
        "warning": SYNTHETIC_WARNING if resolved_mode == "synthetic_demo" else None,
    }
    return json.loads(json.dumps(payload, default=_json_default))


def render_phase7_kpi_status_summary(payload: Dict[str, Any]) -> str:
    lines = [
        "# PHASE 7 KPI STATUS",
        "",
        f"- Generated at: {payload['generated_at']}",
        f"- Run date: {payload['run_date']}",
        f"- Evaluated action count: {payload['evaluated_action_count']}",
        f"- Statistical run count: {payload['stat_run_count']}",
        "",
        "## Records",
    ]
    if not payload.get("records"):
        lines.append("- No persisted statistical runs found for this Phase 7 run date.")
    for row in payload.get("records", []):
        lines.extend([
            f"### {row['action_id']} — {row['proposal_id']}",
            f"- Verdict: {row['verdict']}",
            f"- Test used: {row['test_used']}",
            f"- Guardrail breach: {row['guardrail_breach']}",
            f"- P-value: {row['p_value']}",
            f"- Power achieved: {row['power_achieved']}",
            "",
        ])
    return "\n".join(lines) + "\n"


def build_phase7_kpi_status_view(project_root: Path | None = None, run_date: str | None = None, mode: str | None = None) -> Dict[str, Any]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    payload = build_phase7_stat_summary(root, run_date, resolved_mode)
    output_run_date = payload['run_date']
    _write_json(_phase7_kpi_status_json_path(root, output_run_date, resolved_mode), payload)
    report_path = _phase7_kpi_status_md_path(root, output_run_date, resolved_mode)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_phase7_kpi_status_summary(payload), encoding='utf-8')
    return payload


def load_latest_phase7_kpi_status(project_root: Path | None = None, mode: str | None = None) -> Dict[str, Any]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    if resolved_mode == "synthetic_demo":
        return _read_json(resolve_synthetic_runtime_artifact(root, "phase7_kpi_status"))
    candidates = sorted(phase7_namespace_dir(root, resolved_mode).glob(_phase7_kpi_status_json_path(root, "*", resolved_mode).name))
    if not candidates:
        return build_phase7_kpi_status_view(root, mode=resolved_mode)
    return _read_json(candidates[-1])


def build_phase7_n8n_payload(project_root: Path | None = None, run_date: str | None = None, mode: str | None = None) -> Dict[str, Any]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    integrated = load_integrated_actions(root, run_date, resolved_mode)
    effective_run_date = integrated['run_date']
    actions = []
    for action in integrated.get('actions', []):
        actions.append(
            {
                'action_id': action['action_id'],
                'proposal_id': action['proposal_id'],
                'source_name': action['source_name'],
                'article_title': action['article_title'],
                'recommended_action': action['recommended_action'],
                'approval_status': action.get('approval_status'),
                'launch_status': action.get('launch_status'),
                'lifecycle_state': action.get('lifecycle_state'),
                'stat_test_status': action['stat_test_status'],
                'latest_stat_run_id': action.get('latest_stat_run_id'),
                'latest_verdict': action.get('latest_verdict'),
                'numeric_coherence_passed': action['numeric_coherence_passed'],
                'generation_contract_violation': action['generation_contract_violation'],
            }
        )
    payload = {
        'status': 'ok',
        'generated_at': _deterministic_phase7_generated_at(integrated, effective_run_date, resolved_mode),
        'run_date': effective_run_date,
        'action_count': len(actions),
        'actions': actions,
        'mode': resolved_mode,
        'warning': SYNTHETIC_WARNING if resolved_mode == 'synthetic_demo' else None,
    }
    _write_json(_phase7_n8n_payload_path(root, effective_run_date, resolved_mode), payload)
    return payload


def load_latest_phase7_n8n_payload(project_root: Path | None = None, mode: str | None = None) -> Dict[str, Any]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    if resolved_mode == "synthetic_demo":
        return _read_json(resolve_synthetic_runtime_artifact(root, "phase7_n8n_payload"))
    candidates = sorted(phase7_namespace_dir(root, resolved_mode).glob(_phase7_n8n_payload_path(root, "*", resolved_mode).name))
    if not candidates:
        raise FileNotFoundError(f'no Phase 7 n8n payload found under {phase7_namespace_dir(root, resolved_mode)}')
    return _read_json(candidates[-1])


def evaluate_integrated_action(payload: Dict[str, Any], project_root: Path | None = None, mode: str | None = None) -> Dict[str, Any]:
    """Run the validated statistical engine on a Phase 7 action candidate using supplied experiment counts."""
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    action_id = str(payload.get("action_id") or "").strip()
    run_date = str(payload.get("proposal_run_date") or "").strip() or None
    launched_by = str(payload.get("launched_by") or "").strip()
    baseline_p0 = float(payload.get("baseline_p0", DEFAULT_BASELINE_P0))
    guardrail_q_threshold = float(payload.get("guardrail_q_threshold", DEFAULT_GUARDRAIL_Q_THRESHOLD))
    control_n = int(payload.get("control_n"))
    control_converted = int(payload.get("control_converted"))
    control_opt_out = int(payload.get("control_opt_out"))
    variant_n = int(payload.get("variant_n"))
    variant_converted = int(payload.get("variant_converted"))
    variant_opt_out = int(payload.get("variant_opt_out"))
    if not action_id:
        raise ValueError("action_id is required")
    if not launched_by:
        raise ValueError("launched_by is required")

    integrated = load_integrated_actions(root, run_date, resolved_mode)
    actions = integrated.get("actions", [])
    action = _find_action(actions, action_id)
    if action["stat_test_status"] != "ready":
        raise ValueError(f"action_id '{action_id}' is not ready for statistical evaluation")
    if action.get("approval_required", False) and action.get("approval_status") != "approved":
        raise ValueError(f"action_id '{action_id}' is not approved for statistical evaluation")

    control_arm = _make_arm(control_n, control_converted, control_opt_out)
    variant_arm = _make_arm(variant_n, variant_converted, variant_opt_out)
    ab_result = run_ab_test(
        control_arm,
        variant_arm,
        baseline_p0=baseline_p0,
        guardrail_q_threshold=guardrail_q_threshold,
    )
    run_id = f"p7-stat-{integrated['run_date']}-{uuid.uuid4().hex[:8]}"
    launch_ts = _utc_now_iso()
    result = {
        "stat_test_run_id": run_id,
        "action_id": action_id,
        "proposal_id": action["proposal_id"],
        "proposal_run_date": integrated["run_date"],
        "launched_by": launched_by,
        "launch_ts": launch_ts,
        "baseline_p0": baseline_p0,
        "guardrail_q_threshold": guardrail_q_threshold,
        "control_n": control_n,
        "control_converted": control_converted,
        "control_opt_out": control_opt_out,
        "variant_n": variant_n,
        "variant_converted": variant_converted,
        "variant_opt_out": variant_opt_out,
        "primary_kpi": action.get("primary_kpi") or DEFAULT_PRIMARY_KPI,
        "guardrail_kpi": action.get("guardrail_kpi") or DEFAULT_GUARDRAIL_KPI,
        "conversion_lift": ((variant_converted / variant_n) - (control_converted / control_n)) if control_n and variant_n else None,
        **ab_result,
    }

    runs_df = _load_stat_runs_frame(root, resolved_mode)
    runs_df = pd.concat([runs_df, pd.DataFrame([result])], ignore_index=True) if not runs_df.empty else pd.DataFrame([result])
    _save_stat_runs_frame(root, runs_df, resolved_mode)

    action["latest_stat_run_id"] = run_id
    action["latest_verdict"] = result["verdict"]
    action["latest_conversion_lift"] = result.get("conversion_lift")
    action["launch_ts"] = launch_ts
    action["latest_launch_ts"] = launch_ts
    action["latest_stat_completed_at"] = launch_ts
    action["guardrail_breach"] = bool(result.get("guardrail_breach"))
    action["stat_test_status"] = "completed"
    action["launch_status"] = "completed"
    action["lifecycle_state"] = "stat_test_completed"
    action["lifecycle_updated_at"] = launch_ts
    integrated["generated_at"] = _utc_now_iso()
    integrated_path = _integrated_actions_path(root, integrated["run_date"], resolved_mode)
    _write_json(integrated_path, integrated)
    _set_cached_integrated_actions(integrated_path, integrated)
    report_path = _integrated_actions_report_path(root, integrated["run_date"], resolved_mode)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_integrated_actions_report(integrated), encoding="utf-8")
    _append_phase7_history_record(
        root,
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "stat_test_completed",
            "action_id": action_id,
            "proposal_id": action["proposal_id"],
            "proposal_run_date": integrated["run_date"],
            "stat_test_run_id": run_id,
            "verdict": result["verdict"],
            "launched_by": launched_by,
            "launch_ts": launch_ts,
            "lifecycle_state": action["lifecycle_state"],
        },
        resolved_mode,
    )
    LOGGER.info("Evaluated Phase 7 integrated action %s with verdict %s", action_id, result["verdict"])
    return result
