import logging
import os
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api.churn_service import _ensure_agent_decision_log_table, _load_agent_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)

REPORTS_DIR = PROJECT_ROOT / "reports"
OUTPUT_HTML_PATH = REPORTS_DIR / "phase5_shadow_monitor_latest.html"
OUTPUT_DIVERGENCES_PATH = REPORTS_DIR / "phase5_shadow_divergences.md"
DEFAULT_DB_URL = f"sqlite:///{PROJECT_ROOT / 'data' / 'raw' / 'churn_sqlite_db.sqlite'}"


def _current_db_url() -> str:
    return os.getenv("CHURN_DB_URL", DEFAULT_DB_URL)


def _ops_engine():
    return create_engine(_current_db_url())


def _load_shadow_log_frame() -> pd.DataFrame:
    _ensure_agent_decision_log_table()
    query = text(
        """
        SELECT
            id AS record_id,
            decision_ts,
            cycle_date,
            decision_type,
            agent_decision,
            human_decision,
            match,
            rationale,
            input_snapshot,
            shadow_mode
        FROM agent_decision_log
        WHERE shadow_mode = TRUE
        ORDER BY cycle_date DESC, decision_ts DESC
        """
    )
    engine = _ops_engine()
    try:
        with engine.connect() as conn:
            frame = pd.read_sql(query, conn)
    finally:
        engine.dispose()
    if frame.empty:
        return frame
    frame["decision_ts"] = pd.to_datetime(frame["decision_ts"], utc=False, errors="coerce")
    frame["cycle_date"] = pd.to_datetime(frame["cycle_date"], errors="coerce").dt.date.astype(str)
    frame["match_bool"] = frame["match"].fillna(False).astype(bool)
    frame["has_human_decision"] = frame["human_decision"].notna() & frame["human_decision"].astype(str).str.strip().ne("")
    return frame


def _is_critical_divergence(agent_decision: str | None, human_decision: str | None) -> bool:
    agent = "" if pd.isna(agent_decision) else str(agent_decision).strip().lower()
    human = "" if pd.isna(human_decision) else str(human_decision).strip().lower()
    if not agent or not human or agent == human:
        return False
    if agent == "dispatch_confirm" and human in {"skip", "escalation"}:
        return True
    return human == "dispatch_confirm" and agent in {"skip", "escalation"}


def build_shadow_monitor_payload() -> dict:
    log_frame = _load_shadow_log_frame()
    status_payload = _load_agent_status()

    total_cycles = len(log_frame)
    reconciled = int(log_frame["has_human_decision"].sum()) if total_cycles else 0
    matched = int((log_frame["has_human_decision"] & log_frame["match_bool"]).sum()) if total_cycles else 0
    divergences = int((log_frame["has_human_decision"] & ~log_frame["match_bool"]).sum()) if total_cycles else 0
    pending = int((~log_frame["has_human_decision"]).sum()) if total_cycles else 0
    match_rate = float(matched / reconciled) if reconciled else None

    if total_cycles:
        log_frame["critical_divergence"] = log_frame.apply(
            lambda row: _is_critical_divergence(row.get("agent_decision"), row.get("human_decision")),
            axis=1,
        )
    else:
        log_frame["critical_divergence"] = pd.Series(dtype=bool)

    critical_divergences = int(
        (log_frame["has_human_decision"] & ~log_frame["match_bool"] & log_frame["critical_divergence"]).sum()
    ) if total_cycles else 0

    decision_mix = []
    if total_cycles:
        mix = log_frame["decision_type"].fillna("unknown").value_counts().sort_index()
        decision_mix = [
            {"decision_type": str(label), "count": int(count), "share": float(count / total_cycles)}
            for label, count in mix.items()
        ]

    latest_cycle = log_frame.iloc[0].to_dict() if total_cycles else None
    latest_logged_cycle_date = latest_cycle["cycle_date"] if latest_cycle is not None else None
    latest_logged_decision_ts = None
    if latest_cycle is not None and pd.notna(latest_cycle.get("decision_ts")):
        latest_logged_decision_ts = pd.Timestamp(latest_cycle["decision_ts"]).isoformat()

    recent_cycles = []
    if total_cycles:
        for _, row in log_frame.head(10).iterrows():
            recent_cycles.append(
                {
                    "cycle_date": row["cycle_date"],
                    "decision_type": row["decision_type"],
                    "agent_decision": row["agent_decision"],
                    "human_decision": row["human_decision"],
                    "match": None if not row["has_human_decision"] else bool(row["match_bool"]),
                    "critical_divergence": bool(row["critical_divergence"]) if row["has_human_decision"] else False,
                    "rationale": row["rationale"],
                    "record_id": row["record_id"],
                }
            )

    cycle_trend = []
    if total_cycles:
        trend_frame = (
            log_frame.assign(
                cycle_state=log_frame.apply(
                    lambda row: "pending"
                    if not row["has_human_decision"]
                    else "match"
                    if bool(row["match_bool"])
                    else "critical_divergence"
                    if bool(row["critical_divergence"])
                    else "divergence",
                    axis=1,
                )
            )
            .groupby(["cycle_date", "cycle_state"], dropna=False)
            .size()
            .unstack(fill_value=0)
            .reset_index()
            .sort_values("cycle_date", ascending=False)
        )
        for _, row in trend_frame.iterrows():
            cycle_trend.append(
                {
                    "cycle_date": row["cycle_date"],
                    "match": int(row.get("match", 0)),
                    "divergence": int(row.get("divergence", 0)),
                    "critical_divergence": int(row.get("critical_divergence", 0)),
                    "pending": int(row.get("pending", 0)),
                }
            )

    divergence_rows = []
    if total_cycles:
        divergence_frame = log_frame[log_frame["has_human_decision"] & ~log_frame["match_bool"]].copy()
        for _, row in divergence_frame.iterrows():
            divergence_rows.append(
                {
                    "cycle_date": row["cycle_date"],
                    "decision_type": row["decision_type"],
                    "agent_decision": row["agent_decision"],
                    "human_decision": row["human_decision"],
                    "critical_divergence": bool(row["critical_divergence"]),
                    "rationale": row["rationale"],
                    "record_id": row["record_id"],
                }
            )

    return {
        "run_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "status_snapshot": {
            "recommended_decision_type": status_payload.get("recommended_decision_type"),
            "agent_action_required": bool(status_payload.get("agent_action_required")),
            "active_triggers": status_payload.get("active_triggers", []),
            "human_override": status_payload.get("human_override"),
            "latest_shadow_cycle": status_payload.get("latest_shadow_cycle"),
            "latest_logged_cycle_date": latest_logged_cycle_date,
            "latest_logged_decision_ts": latest_logged_decision_ts,
            "pending_human_decision_count": int(status_payload.get("pending_human_decision_count", 0)),
        },
        "summary": {
            "total_cycles": total_cycles,
            "reconciled_cycles": reconciled,
            "matched_cycles": matched,
            "divergence_cycles": divergences,
            "critical_divergence_cycles": critical_divergences,
            "pending_cycles": pending,
            "match_rate": match_rate,
        },
        "decision_mix": decision_mix,
        "latest_cycle": latest_cycle,
        "recent_cycles": recent_cycles,
        "cycle_trend": cycle_trend,
        "divergences": divergence_rows,
        "source": {
            "db_url": _current_db_url(),
            "decision_log_table": "agent_decision_log",
            "behavior_spec": "reports/phase5_behavior_spec.md",
        },
    }


def render_shadow_monitor_report(payload: dict) -> str:
    summary = payload["summary"]
    status_snapshot = payload["status_snapshot"]
    match_rate_label = f"{summary['match_rate']*100:.1f}%" if summary["match_rate"] is not None else "Pending"
    trigger_items = "".join(f"<li>{item}</li>" for item in status_snapshot["active_triggers"]) or "<li>No active D-2 triggers at render time.</li>"
    decision_mix_rows = "".join(
        f"<tr><td>{row['decision_type']}</td><td>{row['count']}</td><td>{row['share']*100:.1f}%</td></tr>"
        for row in payload["decision_mix"]
    ) or "<tr><td colspan='3'>No shadow decisions logged yet.</td></tr>"
    recent_cycle_rows = "".join(
        "<tr>"
        f"<td>{row['cycle_date']}</td>"
        f"<td>{row['decision_type']}</td>"
        f"<td>{row['agent_decision']}</td>"
        f"<td>{row['human_decision'] or 'Pending'}</td>"
        f"<td><span class='flag {'flag-ok' if row['match'] is True else 'flag-warn' if row['match'] is None else 'flag-danger'}'>{'Match' if row['match'] is True else 'Pending' if row['match'] is None else 'Divergence'}</span></td>"
        f"<td>{'Critical' if row['critical_divergence'] else '—'}</td>"
        f"<td>{row['rationale']}</td>"
        "</tr>"
        for row in payload["recent_cycles"]
    ) or "<tr><td colspan='7'>No recent cycles available.</td></tr>"
    cycle_trend_rows = "".join(
        "<tr>"
        f"<td>{row['cycle_date']}</td>"
        f"<td>{row['match']}</td>"
        f"<td>{row['divergence']}</td>"
        f"<td>{row['critical_divergence']}</td>"
        f"<td>{row['pending']}</td>"
        "</tr>"
        for row in payload["cycle_trend"]
    ) or "<tr><td colspan='5'>No cycle trend is available yet.</td></tr>"
    divergence_rows = "".join(
        "<tr>"
        f"<td>{row['cycle_date']}</td>"
        f"<td>{row['decision_type']}</td>"
        f"<td>{row['agent_decision']}</td>"
        f"<td>{row['human_decision']}</td>"
        f"<td><span class='flag {'flag-danger' if row['critical_divergence'] else 'flag-warn'}'>{'Critical' if row['critical_divergence'] else 'Non-critical'}</span></td>"
        f"<td>{row['rationale']}</td>"
        "</tr>"
        for row in payload["divergences"]
    ) or "<tr><td colspan='6'>No reconciled divergences have been logged so far.</td></tr>"

    decision_state = "Critical review required" if summary["critical_divergence_cycles"] > 0 else "Attention required" if summary["divergence_cycles"] > 0 else "Shadow baseline aligned"
    decision_state_class = "flag-danger" if summary["critical_divergence_cycles"] > 0 else "flag-warn" if summary["divergence_cycles"] > 0 else "flag-ok"

    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='utf-8' />
  <title>Phase 5 Shadow Monitor</title>
</head>
<body>
  <h1>Phase 5 Shadow Monitor</h1>
  <p>Rendered: {payload['run_timestamp']}</p>
  <p class='{decision_state_class}'>{decision_state}</p>
  <ul>{trigger_items}</ul>
  <table>{decision_mix_rows}</table>
  <table>{recent_cycle_rows}</table>
  <table>{cycle_trend_rows}</table>
  <table>{divergence_rows}</table>
  <p>Match rate: {match_rate_label}</p>
</body>
</html>
"""


def render_shadow_divergences_markdown(payload: dict) -> str:
    rows = payload.get("divergences", [])
    if not rows:
        return "# Phase 5 Shadow Divergences\n\nNo reconciled divergences logged so far.\n"
    lines = ["# Phase 5 Shadow Divergences", ""]
    for row in rows:
        lines.extend(
            [
                f"## Cycle {row['cycle_date']}",
                f"- Decision type: {row['decision_type']}",
                f"- Agent decision: {row['agent_decision']}",
                f"- Human decision: {row['human_decision']}",
                f"- Critical divergence: {row['critical_divergence']}",
                f"- Record id: {row['record_id']}",
                f"- Rationale: {row['rationale']}",
                "",
            ]
        )
    return "\n".join(lines)
