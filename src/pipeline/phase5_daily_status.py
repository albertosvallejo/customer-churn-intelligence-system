import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline.phase5_shadow_monitor import build_shadow_monitor_payload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_MARKDOWN_PATH = PROJECT_ROOT / "reports" / "phase5_daily_status_latest.md"
OUTPUT_JSON_PATH = PROJECT_ROOT / "data" / "processed" / "phase5_daily_status_latest.json"
GATE_TARGET = 14
CANONICAL_DB_URL = f"sqlite:///{PROJECT_ROOT / 'data' / 'raw' / 'churn_sqlite_db.sqlite'}"


def _pct(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "Pending"
    return f"{value * 100:.1f}%"


def build_daily_status_snapshot() -> dict:
    payload = build_shadow_monitor_payload()
    summary = payload["summary"]
    status_snapshot = payload["status_snapshot"]

    total_cycles = int(summary.get("total_cycles", 0))
    reconciled_cycles = int(summary.get("reconciled_cycles", 0))
    matched_cycles = int(summary.get("matched_cycles", 0))
    divergence_cycles = int(summary.get("divergence_cycles", 0))
    critical_divergence_cycles = int(summary.get("critical_divergence_cycles", 0))
    pending_cycles = int(summary.get("pending_cycles", 0))
    gate_remaining = max(0, GATE_TARGET - total_cycles)
    gate_progress = min(total_cycles / GATE_TARGET, 1.0) if GATE_TARGET else 0.0

    if total_cycles >= GATE_TARGET and critical_divergence_cycles == 0:
        gate_state = "gate_reached_pending_review"
    elif critical_divergence_cycles > 0:
        gate_state = "critical_divergence_open"
    else:
        gate_state = "accumulating_shadow_days"

    if total_cycles == 0:
        decision_quality_state = "not_ready"
    elif divergence_cycles == 0 and total_cycles < GATE_TARGET:
        decision_quality_state = "partial_routine_alignment"
    elif divergence_cycles > 0:
        decision_quality_state = "mixed_or_divergent"
    else:
        decision_quality_state = "ready_for_gate_review"

    latest_recent = payload.get("recent_cycles", [None])[0] if payload.get("recent_cycles") else None
    source = payload.get("source", {})
    source_db_url = source.get("db_url")
    source_is_canonical = source_db_url == CANONICAL_DB_URL
    source_is_temp = isinstance(source_db_url, str) and "/tmp/" in source_db_url

    latest_logged_cycle_date = status_snapshot.get("latest_logged_cycle_date")
    cycle_gap_days = None
    if latest_logged_cycle_date:
        try:
            cycle_gap_days = (datetime.now(timezone.utc).date() - date.fromisoformat(str(latest_logged_cycle_date))).days
        except ValueError:
            cycle_gap_days = None

    source_integrity = {
        "db_url": source_db_url,
        "canonical_db_url": CANONICAL_DB_URL,
        "is_canonical_db": source_is_canonical,
        "is_temp_db": source_is_temp,
        "latest_logged_cycle_gap_days": cycle_gap_days,
        "stale_shadow_log": cycle_gap_days is not None and cycle_gap_days > 1,
    }

    return {
        "run_timestamp": payload.get("run_timestamp"),
        "gate": {
            "target_shadow_days": GATE_TARGET,
            "logged_shadow_days": total_cycles,
            "remaining_shadow_days": gate_remaining,
            "progress_pct": gate_progress,
            "state": gate_state,
        },
        "decision_quality": {
            "state": decision_quality_state,
            "reconciled_cycles": reconciled_cycles,
            "matched_cycles": matched_cycles,
            "divergence_cycles": divergence_cycles,
            "critical_divergence_cycles": critical_divergence_cycles,
            "pending_cycles": pending_cycles,
            "match_rate": summary.get("match_rate"),
        },
        "operational_status": {
            "recommended_decision_type": status_snapshot.get("recommended_decision_type"),
            "agent_action_required": bool(status_snapshot.get("agent_action_required")),
            "human_override": status_snapshot.get("human_override"),
            "active_triggers": status_snapshot.get("active_triggers", []),
            "latest_shadow_cycle": status_snapshot.get("latest_shadow_cycle"),
            "latest_logged_cycle_date": status_snapshot.get("latest_logged_cycle_date"),
            "latest_logged_decision_ts": status_snapshot.get("latest_logged_decision_ts"),
        },
        "latest_cycle_review": latest_recent,
        "source_integrity": source_integrity,
        "next_honest_step": (
            "Keep accumulating valid shadow days and avoid treating preparation artifacts as gate closure."
            if gate_state != "gate_reached_pending_review"
            else "Review Block G closure conditions with Alberto before any Block H activation."
        ),
        "source": source,
    }


def render_daily_status_markdown(snapshot: dict) -> str:
    gate = snapshot["gate"]
    quality = snapshot["decision_quality"]
    ops = snapshot["operational_status"]
    latest = snapshot.get("latest_cycle_review") or {}
    integrity = snapshot.get("source_integrity") or {}
    triggers = ops.get("active_triggers") or []
    trigger_lines = "\n".join(f"- {item}" for item in triggers) if triggers else "- None"

    return f"""# Phase 5 Daily Status\n\n- Run timestamp: {snapshot.get('run_timestamp')}\n- Gate progress: {gate['logged_shadow_days']}/{gate['target_shadow_days']} ({gate['progress_pct']*100:.1f}%)\n- Gate state: {gate['state']}\n- Remaining shadow days: {gate['remaining_shadow_days']}\n\n## Decision quality\n\n- State: {quality['state']}\n- Reconciled cycles: {quality['reconciled_cycles']}\n- Matched cycles: {quality['matched_cycles']}\n- Divergence cycles: {quality['divergence_cycles']}\n- Critical divergences: {quality['critical_divergence_cycles']}\n- Pending cycles: {quality['pending_cycles']}\n- Match rate: {_pct(quality.get('match_rate'))}\n\n## Operational status\n\n- Recommended decision type: {ops.get('recommended_decision_type')}\n- Agent action required: {ops.get('agent_action_required')}\n- Human override: {ops.get('human_override')}\n- Latest shadow cycle (service): {ops.get('latest_shadow_cycle')}\n- Latest logged cycle date: {ops.get('latest_logged_cycle_date')}\n- Latest logged decision timestamp: {ops.get('latest_logged_decision_ts')}\n\n## Source integrity\n\n- Source DB: {integrity.get('db_url')}\n- Canonical DB expected: {integrity.get('canonical_db_url')}\n- Canonical DB in use: {integrity.get('is_canonical_db')}\n- Temporary/test DB detected: {integrity.get('is_temp_db')}\n- Days since latest logged cycle: {integrity.get('latest_logged_cycle_gap_days')}\n- Stale shadow log alert: {integrity.get('stale_shadow_log')}\n\n### Active triggers\n{trigger_lines}\n\n## Latest cycle review\n\n- Cycle date: {latest.get('cycle_date')}\n- Decision type: {latest.get('decision_type')}\n- Agent decision: {latest.get('agent_decision')}\n- Human decision: {latest.get('human_decision') or 'Pending'}\n- Match: {latest.get('match')}\n- Critical divergence: {latest.get('critical_divergence')}\n\n## Next honest step\n\n{snapshot.get('next_honest_step')}\n"""


def save_outputs(snapshot: dict) -> None:
    OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MARKDOWN_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON_PATH.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    OUTPUT_MARKDOWN_PATH.write_text(render_daily_status_markdown(snapshot), encoding="utf-8")
    logger.info("Saved Phase 5 daily status artifacts: %s and %s", OUTPUT_JSON_PATH, OUTPUT_MARKDOWN_PATH)


if __name__ == "__main__":
    snapshot = build_daily_status_snapshot()
    save_outputs(snapshot)
    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
