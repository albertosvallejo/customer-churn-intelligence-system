import html
import json
from datetime import datetime, timezone
from math import isnan
from pathlib import Path
from typing import Any

from evidence.phase7_artifacts import (
    SYNTHETIC_WARNING,
    phase7_namespace_dir,
    resolve_phase7_mode,
    resolve_synthetic_runtime_artifact,
)
from evidence.phase7_integration import (
    load_integrated_actions,
    load_phase7_action_history,
)

PHASE7_REPORTING_POLL_MS = 300_000
DASHBOARD_ROUTE = "/customer-churn/dashboard"
TESTED_ACTIONS_ROUTE = "/customer-churn/tested-actions-approval"
NEW_ACTIONS_ROUTE = "/customer-churn/new-actions-testing"


_PROPOSAL_NAME_OVERRIDES = {
    "p6-001": "Reduce checkout friction with express payment",
    "p6-002": "Recover abandoned carts with a timed incentive",
    "p6-003": "Highlight free delivery for high-value baskets",
}

_KPI_LABEL_OVERRIDES = {
    "conversion_rate": "Conversion rate",
    "checkout_completion": "Checkout completion",
    "checkout_completion_rate": "Checkout completion rate",
    "cart_recovery": "Cart recovery",
    "cart_recovery_rate": "Cart recovery rate",
    "average_order_value": "Average order value",
    "average_order_value_lift": "Average order value",
    "aov": "Average order value",
    "retention_conversion": "Retention conversion",
    "repeat_purchase": "Repeat purchase",
    "customer_retention": "Customer retention",
    "reactivation_rate": "Reactivation rate",
    "email_conversion": "Email conversion",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return isnan(value)
    text = str(value).strip()
    return text == "" or text.lower() == "nan"


def _fmt(value: Any) -> str:
    if _is_missing(value):
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _coalesce(*values: Any) -> Any:
    for value in values:
        if not _is_missing(value):
            return value
    return None


def _title_case_kpi(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "—"
    if text in _KPI_LABEL_OVERRIDES:
        return _KPI_LABEL_OVERRIDES[text]
    return text.replace("_", " ").title()


def _proposal_display_name(record: dict[str, Any], integrated_actions: list[dict[str, Any]]) -> str:
    proposal_id = str(record.get("proposal_id") or "").strip()
    for action in integrated_actions:
        if str(action.get("proposal_id") or "").strip() == proposal_id:
            title = str(action.get("article_title") or "").strip()
            if title:
                return title
    if proposal_id in _PROPOSAL_NAME_OVERRIDES:
        return _PROPOSAL_NAME_OVERRIDES[proposal_id]
    return proposal_id or "Untitled proposal"


def _result_label(verdict: str) -> str:
    mapping = {
        "A_wins": "Current action wins",
        "B_wins": "New proposal wins",
        "insufficient_sample": "Not enough data yet",
        "no_significant_difference": "Not enough data yet",
    }
    return mapping.get(str(verdict or ""), str(verdict or "—").replace("_", " ").title())


def _status_label(record: dict[str, Any]) -> str:
    status = str(record.get("status") or "").lower()
    verdict = str(record.get("verdict") or "")
    if status != "completed":
        return "Pending of more data"
    if verdict == "B_wins":
        return "Pending for approval"
    if verdict == "A_wins":
        return "Rejected"
    return "Pending of more data"


def _format_percent(value: Any, *, dash_for_none: bool = True) -> str:
    if value is None or value == "":
        return "—" if dash_for_none else ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = str(value)
        return text if text else ("—" if dash_for_none else "")
    if abs(number) < 1e-12:
        return "0.0%"
    sign = "+" if number > 0 else "-"
    return f"{sign}{abs(number) * 100:.1f}%"


def _format_dt(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "—"
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return dt.strftime("%d %b %Y · %H:%M")


def _load_latest_phase6_kpi_status(project_root: Path, mode: str | None = None) -> dict[str, Any]:
    resolved_mode = resolve_phase7_mode(mode)
    if resolved_mode == "synthetic_demo":
        return _read_json(resolve_synthetic_runtime_artifact(project_root, "phase6_kpi_status"))
    namespace_dir = phase7_namespace_dir(project_root, resolved_mode)
    pattern = "synthetic_demo__phase6_kpi_status_*.json" if resolved_mode == "synthetic_demo" else "phase6_kpi_status_*.json"
    candidates = sorted(namespace_dir.glob(pattern))
    if not candidates:
        raise FileNotFoundError(f"no Phase 6 KPI status JSON found under {namespace_dir}")
    return _read_json(candidates[-1])


def _safe_load_integrated_actions(project_root: Path, run_date: str | None, mode: str | None) -> dict[str, Any] | None:
    try:
        return load_integrated_actions(project_root, run_date, mode)
    except Exception:  # noqa: BLE001 - optional view-model fallback
        return None


def _default_pending_chip(kpi_label: str) -> dict[str, Any]:
    return {
        "kpi": kpi_label,
        "subtitle": "Collecting data",
        "value": "Pending",
        "tone": "gold",
        "state": "pending",
        "pending": True,
        "empty": False,
    }


def _default_empty_chip(kpi_label: str, subtitle: str = "No active proposals") -> dict[str, Any]:
    return {
        "kpi": kpi_label,
        "subtitle": subtitle,
        "value": "—",
        "tone": "grey",
        "state": "empty",
        "pending": False,
        "empty": True,
    }


def _build_kpi_chip_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(_title_case_kpi(record.get("primary_kpi")), []).append(record)

    chips: list[dict[str, Any]] = []
    for kpi_label, rows in grouped.items():
        if kpi_label == "—":
            chips.append(
                {
                    "kpi": "KPI not assigned",
                    "subtitle": "Needs KPI mapping before evaluation",
                    "value": "No KPI yet",
                    "tone": "grey",
                    "state": "empty",
                    "pending": False,
                    "empty": True,
                }
            )
            continue

        completed_with_lift = [
            row
            for row in rows
            if str(row.get("status") or "").lower() == "completed"
            and row.get("conversion_lift") is not None
            and str(row.get("verdict") or "").lower() in {"b_wins", "a_wins"}
        ]
        completed_without_lift = [
            row
            for row in rows
            if str(row.get("status") or "").lower() == "completed"
            and (
                row.get("conversion_lift") is None
                or str(row.get("verdict") or "").lower() in {"insufficient_sample", "no_significant_difference"}
            )
        ]

        if completed_with_lift:
            best = max(completed_with_lift, key=lambda row: float(row.get("conversion_lift") or 0.0))
            lift_value = float(best.get("conversion_lift") or 0.0)
            chips.append(
                {
                    "kpi": kpi_label,
                    "subtitle": "Best measured lift",
                    "value": _format_percent(lift_value),
                    "tone": "green" if lift_value > 0 else "grey",
                    "state": "measured",
                    "pending": False,
                    "empty": False,
                }
            )
        elif completed_without_lift:
            chips.append(_default_pending_chip(kpi_label))
        elif rows:
            chips.append(
                {
                    "kpi": kpi_label,
                    "subtitle": "Collecting data",
                    "value": "Pending",
                    "tone": "gold",
                    "state": "pending",
                    "pending": True,
                    "empty": False,
                }
            )
    existing_kpis = {chip["kpi"] for chip in chips}
    if "Conversion rate" not in existing_kpis:
        chips.append(_default_empty_chip("Conversion rate"))
        existing_kpis.add("Conversion rate")
    if "Average order value" not in existing_kpis:
        chips.append(_default_pending_chip("Average order value"))

    preferred_order = {
        "Checkout completion": 0,
        "Checkout completion rate": 0,
        "Cart recovery": 1,
        "Cart recovery rate": 1,
        "Conversion rate": 2,
        "Average order value": 3,
        "Retention conversion": 4,
    }
    chips.sort(key=lambda chip: (preferred_order.get(chip["kpi"], 99), chip["kpi"]))
    return chips


def _build_campaign_rows(records: list[dict[str, Any]], integrated_actions: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        result = _result_label(str(record.get("verdict") or ""))
        test_result = "—" if result == "Not enough data yet" else _format_percent(record.get("conversion_lift"))
        rows.append(
            {
                "proposal_name": _proposal_display_name(record, integrated_actions),
                "proposal_id": _fmt(record.get("proposal_id")),
                "proposal_href": "#proposal",
                "kpi_to_improve": _title_case_kpi(record.get("primary_kpi")),
                "result": result,
                "test_result": test_result,
                "guardrail_risk": bool(record.get("guardrail_breach")),
                "guardrail_tooltip": "Risk detected in a monitored guardrail metric." if bool(record.get("guardrail_breach")) else "All monitored guardrails remained within threshold.",
                "launch_at": _format_dt(record.get("launch_ts")),
                "closed_at": _format_dt(generated_at) if str(record.get("status") or "").lower() == "completed" else "Still running",
                "status": _status_label(record),
            }
        )
    return rows


def _coerce_guardrail_risk(event: dict[str, Any]) -> bool | None:
    if not _is_missing(event.get("guardrail_risk")):
        return bool(event.get("guardrail_risk"))
    if not _is_missing(event.get("guardrail")):
        return bool(event.get("guardrail"))
    if not _is_missing(event.get("guardrail_breach")):
        return bool(event.get("guardrail_breach"))
    return None


def _coerce_history_period(event: dict[str, Any], matching_action: dict[str, Any] | None = None) -> tuple[str, str]:
    launch_value = _coalesce(
        event.get("launch_at"),
        event.get("request_ts"),
        event.get("launch_ts"),
        (matching_action or {}).get("launch_ts"),
        (matching_action or {}).get("latest_launch_ts"),
        event.get("decision_ts"),
        event.get("executed_ts"),
    )
    closed_value = _coalesce(
        event.get("closed_at"),
        (matching_action or {}).get("latest_stat_completed_at"),
        event.get("decision_ts"),
        event.get("executed_ts"),
    )
    launch_at = _format_dt(launch_value)
    closed_at = _format_dt(closed_value)
    test_period = str(event.get("test_period") or "").strip()
    if test_period and test_period != "—":
        parts = [part.strip() for part in test_period.split("→", 1)]
        if len(parts) == 2:
            left = parts[0] or launch_at
            right = parts[1] or closed_at
            return left, right
        if launch_at == "—" and closed_at == "—":
            return test_period, "—"
    return launch_at, closed_at


def _history_result_label(event: dict[str, Any]) -> str:
    direct_result = _coalesce(event.get("result"))
    if direct_result is not None:
        return str(direct_result).replace("_", " ").title()
    verdict = _coalesce(event.get("verdict"))
    if verdict is not None:
        return _result_label(str(verdict))
    decision_status = str(_coalesce(event.get("decision_status")) or "").lower()
    mapping = {
        "approved": "Approved for test",
        "rejected": "Rejected before test",
        "postponed": "Postponed",
    }
    if decision_status in mapping:
        return mapping[decision_status]
    fallback = _coalesce(event.get("decision_type"), event.get("event_type"), event.get("result"))
    return str(fallback).replace("_", " ").title() if fallback is not None else "—"


def _history_status_label(event: dict[str, Any]) -> str:
    direct_status = _coalesce(event.get("status"))
    lifecycle = str(_coalesce(event.get("lifecycle_state"), direct_status) or "").lower()
    decision_status = str(_coalesce(event.get("decision_status")) or "").lower()
    verdict = str(_coalesce(event.get("verdict")) or "")
    if lifecycle == "rejected" or decision_status == "rejected":
        return "Rejected"
    if lifecycle == "approved_for_stat_test" or decision_status == "approved":
        return "Approved"
    if verdict == "B_wins":
        return "Pending for approval"
    if verdict == "A_wins":
        return "Rejected"
    if verdict in {"insufficient_sample", "no_significant_difference"}:
        return "Pending of more data"
    if lifecycle == "active_winner":
        return "Approved"
    return str(_coalesce(event.get("status"), event.get("lifecycle_state"), event.get("decision_type")) or "—").replace("_", " ").title()


def _history_test_result(event: dict[str, Any], matching_action: dict[str, Any] | None) -> str:
    source_value = _coalesce(
        event.get("test_result"),
        event.get("conversion_lift"),
        (matching_action or {}).get("latest_conversion_lift"),
    )
    if source_value is None:
        return "—"
    return _format_percent(source_value)


def _history_guardrail_payload(event: dict[str, Any], matching_action: dict[str, Any] | None) -> tuple[bool | None, str, str]:
    guardrail_risk = _coalesce(event.get("guardrail_risk"), event.get("guardrail"), event.get("guardrail_breach"), (matching_action or {}).get("guardrail_breach"))
    if _is_missing(guardrail_risk):
        return None, "—", ""
    is_risk = bool(guardrail_risk)
    return is_risk, ("Risk detected" if is_risk else "No risks detected"), ("Risk detected in a monitored guardrail metric." if is_risk else "All monitored guardrails remained within threshold.")


def _build_history_rows(history: list[dict[str, Any]], integrated_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in history:
        proposal_id = str(event.get("proposal_id") or "").strip()
        matching_action = next((action for action in integrated_actions if str(action.get("proposal_id") or "").strip() == proposal_id), None)
        proposal_name = str((matching_action or {}).get("article_title") or event.get("action") or event.get("action_id") or proposal_id or "Action")
        reason_value = _coalesce(event.get("reason"), event.get("decision_reason"), event.get("post_test_decision_reason"))
        launch_at, closed_at = _coerce_history_period(event, matching_action)
        guardrail_risk, guardrail_label, guardrail_tooltip = _history_guardrail_payload(event, matching_action)
        rows.append(
            {
                "action": proposal_name,
                "proposal_name": proposal_name,
                "kpi_to_improve": _title_case_kpi(_coalesce((matching_action or {}).get("primary_kpi"), (matching_action or {}).get("recommended_kpi"), event.get("kpi_to_improve"), "")),
                "result": _history_result_label(event),
                "test_result": _history_test_result(event, matching_action),
                "guardrail_risk": guardrail_risk,
                "guardrail": guardrail_label,
                "guardrail_tooltip": guardrail_tooltip,
                "launch_at": launch_at,
                "closed_at": closed_at,
                "test_period": f"{launch_at} → {closed_at}" if launch_at != "—" or closed_at != "—" else "—",
                "reason": str(reason_value).replace("_", " ").title() if reason_value is not None else "—",
                "decision_reason": str(reason_value).replace("_", " ").title() if reason_value is not None else "—",
                "status": _history_status_label(event),
            }
        )
    return rows


def build_phase7_reporting_view_model(project_root: Path, run_date: str | None = None, mode: str | None = None) -> dict[str, Any]:
    resolved_mode = resolve_phase7_mode(mode)
    kpi_payload = _load_latest_phase6_kpi_status(project_root, resolved_mode)
    integrated = _safe_load_integrated_actions(project_root, run_date, resolved_mode) or {"actions": []}
    history = load_phase7_action_history(project_root, run_date=run_date, mode=resolved_mode)
    records = kpi_payload.get("records", [])
    completed_tests = [
        record for record in records
        if str(record.get("status") or "").lower() == "completed"
        and str(record.get("verdict") or "") != "insufficient_sample"
    ]
    winner_tests = [record for record in completed_tests if str(record.get("verdict") or "") == "B_wins"]
    guardrail_breaches = [record for record in completed_tests if bool(record.get("guardrail_breach"))]
    campaign_rows = _build_campaign_rows(records, integrated.get("actions", []), str(kpi_payload.get("generated_at") or ""))
    effective_run_date = str(
        run_date
        or kpi_payload.get("run_date")
        or kpi_payload.get("logical_date")
        or integrated.get("run_date")
        or ""
    )
    return {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "requested_run_date": run_date,
        "effective_run_date": effective_run_date,
        "poll_ms": PHASE7_REPORTING_POLL_MS,
        "kpi_status": kpi_payload,
        "history": history,
        "history_rows": _build_history_rows(history, integrated.get("actions", [])),
        "mode": resolved_mode,
        "warning": "SYNTHETIC DATA — NOT REAL RESULTS" if resolved_mode == "synthetic_demo" else None,
        "summary": {
            "test_count": int(kpi_payload.get("test_count", len(records))),
            "completed_test_count": len(completed_tests),
            "winner_test_count": len(winner_tests),
            "guardrail_breach_count": len(guardrail_breaches),
            "visible_history_count": len(history),
        },
        "kpi_chips": _build_kpi_chip_rows(records),
        "campaign_rows": campaign_rows,
    }


def _base_styles() -> str:
    return """
:root {
  --blue: #005090;
  --deep-blue: #104070;
  --green: #208040;
  --soft-green: #60a060;
  --gold: #e0b000;
  --red: #c01010;
  --ink: #14233d;
  --muted: #637084;
  --line: #dfe5ec;
  --surface: #ffffff;
  --canvas: #f4f6f9;
  --sidebar-width: 210px;
}
* { box-sizing: border-box; }
html { background: var(--canvas); }
body { margin: 0; background: var(--canvas); color: var(--ink); font-family: Inter, Arial, Helvetica, sans-serif; -webkit-font-smoothing: antialiased; }
button, textarea, select, input { font: inherit; }
button { cursor: pointer; }
a { color: inherit; }
.app-shell { min-height: 100vh; }
.sidebar { position: fixed; inset: 0 auto 0 0; width: var(--sidebar-width); background: var(--blue); color: #fff; z-index: 30; padding: 18px 14px 16px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 8px 0 26px rgba(16, 64, 112, .09); }
.logo-card { background: #fff; height: 68px; padding: 10px 12px; border-radius: 8px; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 14px rgba(6, 33, 58, .18); }
.logo-card img { display: block; width: 100%; max-height: 49px; object-fit: contain; }
.product-meta { padding: 14px 4px 15px; border-bottom: 1px solid rgba(255,255,255,.2); display: grid; gap: 3px; }
.product-meta strong { font-size: 11px; line-height: 1.35; }
.product-meta span { color: rgba(255,255,255,.84); font-size: 10px; }
.sidebar nav { padding-top: 19px; }
.sidebar-label { margin: 0 0 9px; color: #fff; font-size: 9px; line-height: 1; letter-spacing: .12em; font-weight: 800; }
.nav-item { position: relative; display: flex; width: 100%; min-height: 31px; align-items: center; gap: 8px; padding: 6px 8px; border: 0; border-radius: 6px; background: transparent; color: rgba(255,255,255,.84); text-align: left; font-size: 10px; line-height: 1.2; font-weight: 650; margin-bottom: 0; text-decoration: none; }
.nav-item:hover { color: #fff; background: rgba(255,255,255,.1); }
.nav-item.active { background: rgba(255,255,255,.18); color: #fff; box-shadow: inset 3px 0 0 #fff; }
.nav-dot { width: 15px; height: 15px; border: 1.5px solid currentColor; border-radius: 50%; display: grid; place-items: center; opacity: .9; flex: 0 0 auto; }
.nav-dot i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; opacity: 0; }
.nav-item.active .nav-dot i { opacity: 1; }
.feedback-panel { margin-top: 38px; padding: 14px 3px 2px; border-top: 1px solid rgba(255,255,255,.24); }
.stars { display: flex; gap: 3px; margin: 0 0 9px; }
.stars button { padding: 0; border: 0; background: transparent; color: rgba(255,255,255,.35); font-size: 16px; line-height: 1; }
.stars button.selected { color: #ffd253; }
.feedback-panel textarea { resize: none; display: block; width: 100%; height: 43px; border: 1px solid rgba(255,255,255,.3); background: rgba(8, 35, 61, .28); color: #fff; border-radius: 5px; padding: 8px 9px; font-size: 9px; outline: none; }
.feedback-panel textarea::placeholder { color: rgba(255,255,255,.48); }
.feedback-button { margin-top: 8px; width: 100%; min-height: 29px; border: 0; border-radius: 5px; background: var(--gold); color: #302600; font-size: 9px; font-weight: 850; box-shadow: inset 0 -1px 0 rgba(87, 65, 0, .18); }
.main-content { margin-left: var(--sidebar-width); min-height: 100vh; }
.synthetic-banner { height: 34px; padding: 9px 20px; background: var(--red); color: #fff; font-size: 11px; line-height: 16px; text-align: center; letter-spacing: .1em; font-weight: 800; }
.content-wrap { width: min(1510px, calc(100% - 64px)); margin: 0 auto; padding: 26px 0 54px; }
.dashboard-hero, .approval-header { background: var(--surface); border: 1px solid #e6ebf0; border-radius: 15px; padding: 28px 30px; box-shadow: 0 8px 28px rgba(28, 52, 79, .07); display: flex; align-items: flex-start; justify-content: space-between; gap: 30px; }
.eyebrow, .section-kicker { margin: 0 0 8px; color: var(--blue); font-size: 10px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
h1 { margin: 0; color: var(--deep-blue); font-size: clamp(28px, 2.7vw, 39px); line-height: 1.14; letter-spacing: -.035em; }
.intro { max-width: 830px; margin: 11px 0 0; color: #4d5c70; font-size: 14px; line-height: 1.55; }
.run-meta { margin: 12px 0 0; color: #7b8796; font-size: 11px; }
.run-meta span { padding: 0 4px; color: #b0b8c2; }
.info { position: relative; display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; padding: 0; border: 1px solid #a9b4c0; background: #fff; color: #617083; border-radius: 50%; font-size: 11px; font-weight: 800; text-decoration: none; }
.info::after, .risk-tip::after { content: attr(data-tip); position: absolute; z-index: 50; left: 50%; bottom: calc(100% + 10px); width: 260px; padding: 10px 12px; border-radius: 8px; background: #10233c; color: #fff; font-size: 10px; line-height: 1.45; font-weight: 500; text-align: left; transform: translateX(-50%) translateY(4px); opacity: 0; pointer-events: none; transition: .16s ease; box-shadow: 0 8px 22px rgba(0,0,0,.22); }
.info:hover::after, .info:focus::after, .risk-tip:hover::after { opacity: 1; transform: translateX(-50%) translateY(0); }
.dashboard-hero { align-items: center; }
.hero-controls { display: grid; justify-items: end; gap: 14px; min-width: 190px; }
.refresh-control { width: 190px; min-height: 82px; padding: 14px 18px; position: relative; border: 1px solid #bedac8; background: #eef8f2; border-radius: 12px; display: grid; align-content: center; }
.refresh-control strong { color: #17683d; font-size: 12px; white-space: nowrap; text-transform: uppercase; }
.refresh-control small { color: #537264; font-size: 10px; margin-top: 2px; }
.cta-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.cta-button { display: inline-flex; align-items: center; gap: 6px; padding: 9px 12px; border-radius: 8px; border: 1px solid #cfd8e1; background: #fff; color: #4e5c70; font-size: 10px; font-weight: 800; text-decoration: none; }
.cta-button.primary { border-color: var(--blue); background: var(--blue); color: #fff; }
.kpi-chips { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 16px 0 12px; }
.kpi-chips > div { min-height: 70px; padding: 14px 15px; background: #fff; border: 1px solid var(--line); border-radius: 11px; display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 10px; }
.chip-dot { width: 9px; height: 9px; border-radius: 50%; background: #aab4bf; box-shadow: 0 0 0 4px #eef1f4; }
.chip-dot.green { background: var(--green); box-shadow: 0 0 0 4px #e6f3eb; }
.chip-dot.gold { background: var(--gold); box-shadow: 0 0 0 4px #fbf3d8; }
.chip-dot.grey { background: #aab4bf; box-shadow: 0 0 0 4px #eef1f4; }
.kpi-chips p { margin: 0; color: #34445b; font-size: 12px; font-weight: 700; }
.kpi-chips p small { display: block; margin-top: 4px; color: #8a95a2; font-size: 9px; font-weight: 500; }
.kpi-chips strong { color: var(--green); font-size: 18px; }
.kpi-chips strong.pending { color: #9a7410; font-size: 11px; text-transform: uppercase; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.summary-grid article { position: relative; min-height: 132px; padding: 19px 18px; background: #fff; border: 1px solid var(--line); border-radius: 12px; }
.summary-grid p { width: calc(100% - 38px); margin: 0 0 10px; color: #4e5c6d; font-size: 11px; line-height: 1.35; font-weight: 700; }
.summary-grid strong { display: block; margin-bottom: 5px; color: var(--deep-blue); font-size: 30px; line-height: 1; }
.summary-grid small { color: #8993a0; font-size: 9px; }
.metric-icon { position: absolute; top: 17px; right: 16px; width: 27px; height: 27px; border-radius: 8px; display: grid; place-items: center; background: #eaf1f7; color: var(--blue); font-size: 15px; font-weight: 800; }
.metric-icon.success, .metric-icon.safe { background: #e8f4ec; color: var(--green); }
.panel { margin-top: 16px; padding: 22px 22px 12px; background: #fff; border: 1px solid var(--line); border-radius: 14px; box-shadow: 0 7px 24px rgba(26, 45, 70, .045); }
.section-heading, .list-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 22px; margin-bottom: 17px; }
.section-heading h2, .list-heading h2 { margin: 0; color: var(--deep-blue); font-size: 19px; letter-spacing: -.015em; }
.section-heading p:not(.section-kicker), .list-heading p:not(.section-kicker) { margin: 6px 0 0; color: #7b8794; font-size: 11px; }
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th { padding: 10px 10px; background: #f6f8fa; color: #718094; font-size: 9px; letter-spacing: .055em; text-transform: uppercase; text-align: left; white-space: nowrap; border-top: 1px solid #e9edf1; border-bottom: 1px solid #dde3e9; }
td { padding: 13px 10px; color: #405066; font-size: 10px; line-height: 1.35; vertical-align: middle; border-bottom: 1px solid #edf0f3; }
.proposal-cell { min-width: 235px; }
.proposal-cell a { display: block; color: var(--deep-blue); font-size: 11px; font-weight: 750; text-decoration: none; }
.proposal-cell a:hover { text-decoration: underline; }
.proposal-cell span { display: block; margin-top: 4px; color: #99a3af; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 8px; }
.pill { display: inline-flex; max-width: 130px; min-height: 23px; padding: 5px 8px; align-items: center; border-radius: 999px; background: #eef1f4; color: #596676; font-size: 8px; line-height: 1.2; font-weight: 800; }
.pill.positive { background: #e5f3ea; color: #17673c; }
.pill.negative { background: #f9e4e4; color: #9b1717; }
.pill.warning { background: #fbf1cc; color: #7c5c08; }
.pill.blue { background: #e4eef7; color: var(--blue); }
.risk-tip { position: relative; display: inline-flex; }
.period { min-width: 128px; }
.period span, .period small { display: block; white-space: nowrap; }
.period small { margin-top: 3px; color: #8893a0; }
.dash { color: #9ba5af; font-size: 16px; }
.quiet-button { padding: 8px 11px; border: 1px solid #ced7e0; border-radius: 7px; background: #fff; color: #657387; font-size: 10px; font-weight: 700; }
.history-panel { padding-bottom: 18px; }
.history-table { min-width: 1160px; }
.history-table td:first-child { min-width: 220px; color: var(--deep-blue); font-weight: 650; }
.history-table .reason-cell { min-width: 120px; color: #566579; font-weight: 650; }
.empty-state { padding: 18px; border: 1px dashed #cbd5e1; border-radius: 12px; color: #475569; background: #f8fafc; }
@media (max-width: 1180px) {
  :root { --sidebar-width: 200px; }
  .content-wrap { width: calc(100% - 36px); }
  .kpi-chips, .summary-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 760px) {
  :root { --sidebar-width: 0px; }
  .sidebar { position: static; width: 100%; min-height: auto; padding: 14px; }
  .sidebar nav { padding-top: 8px; display: flex; gap: 4px; overflow-x: auto; }
  .main-content { margin-left: 0; }
  .content-wrap { width: calc(100% - 24px); padding-top: 14px; }
  .dashboard-hero, .approval-header { padding: 20px; flex-direction: column; }
  .hero-controls { min-width: 0; width: 100%; justify-items: start; }
  .refresh-control { width: 100%; }
  .kpi-chips, .summary-grid { grid-template-columns: 1fr; }
  .section-heading, .list-heading { flex-direction: column; }
}
"""


def _render_sidebar(active: str) -> str:
    items = [
        (DASHBOARD_ROUTE, "Dashboard", "dashboard"),
        (TESTED_ACTIONS_ROUTE, "Tested Actions Approval", "tested"),
        (NEW_ACTIONS_ROUTE, "New Actions Approval", "new"),
    ]
    nav = "".join(
        f'<a class="nav-item {"active" if kind == active else ""}" href="{href}"><span class="nav-dot" aria-hidden="true"><i></i></span>{label}</a>'
        for href, label, kind in items
    )
    stars = "".join(
        f'<button class="selected" type="button" aria-label="{star} star rating">★</button>'
        for star in range(1, 6)
    )
    return f"""
<aside class="sidebar">
  <div>
    <div class="logo-card"><img src="/static/assets/images/logo.png" alt="VivaMarket" /></div>
    <div class="product-meta"><strong>Customer Churn Intelligence</strong><span>VivaMarket Brasil</span></div>
    <nav aria-label="Main navigation"><p class="sidebar-label">NAVIGATION</p>{nav}</nav>
  </div>
  <div class="feedback-panel"><p class="sidebar-label">FEEDBACK</p><div class="stars" aria-label="Rate this dashboard">{stars}</div><textarea aria-label="Optional feedback comments" placeholder="Optional comments…"></textarea><button class="feedback-button" type="button">Send feedback</button></div>
</aside>
"""


def _result_tone(value: str) -> str:
    text = str(value or "").lower()
    if text in {"new proposal wins", "approved", "approved for test"}:
        return "positive"
    if text in {"current action wins", "rejected", "rejected before test"}:
        return "negative"
    return "neutral"


def _test_result_tone(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("+"):
        return "positive"
    if text.startswith(("-", "−")):
        return "negative"
    return "neutral"


def _status_tone(value: str) -> str:
    text = str(value or "").lower()
    if text == "approved":
        return "positive"
    if text == "rejected":
        return "negative"
    if text == "pending for approval":
        return "warning"
    return "neutral"


def _guardrail_html(row: dict[str, Any]) -> str:
    label = str(row.get("guardrail") or row.get("guardrail_status") or "—")
    if label == "—":
        return '<span class="dash">—</span>'
    tone = "negative" if row.get("guardrail_risk") is True else "positive" if row.get("guardrail_risk") is False else "neutral"
    tooltip = html.escape(str(row.get("guardrail_tooltip") or ""))
    if tooltip:
        return f"<span class='risk-tip' data-tip='{tooltip}'><span class='pill {tone}'>{html.escape(label)}</span></span>"
    return f"<span class='pill {tone}'>{html.escape(label)}</span>"


def _render_campaign_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<tr><td colspan='7'>No campaign rows found.</td></tr>"
    rendered = []
    for row in rows:
        result_tone = _result_tone(row["result"])
        test_result = str(row["test_result"])
        test_tone = _test_result_tone(test_result)
        status_tone = _status_tone(row["status"])
        test_result_html = "<span class=\"dash\">—</span>" if test_result == "—" else f"<span class=\"pill {test_tone}\">{html.escape(test_result)}</span>"
        rendered.append(
            f"<tr>"
            f"<td class='proposal-cell'><a href='{html.escape(row['proposal_href'])}'>{html.escape(row['proposal_name'])}</a><span>{html.escape(row['proposal_id'])}</span></td>"
            f"<td>{html.escape(row['kpi_to_improve'])}</td>"
            f"<td><span class='pill {result_tone}'>{html.escape(row['result'])}</span></td>"
            f"<td>{test_result_html}</td>"
            f"<td>{_guardrail_html(row)}</td>"
            f"<td class='period'><span>{html.escape(row['launch_at'])}</span><small>{html.escape(row['closed_at'])}</small></td>"
            f"<td><span class='pill {status_tone}'>{html.escape(row['status'])}</span></td>"
            f"</tr>"
        )
    return "".join(rendered)


def _render_history_rows(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<div class='empty-state'>No visible Phase 7 history events yet.</div>"
    rendered = []
    for row in rows:
        result_tone = _result_tone(row["result"])
        test_result = str(row["test_result"])
        test_tone = _test_result_tone(test_result)
        status_text = row["status"]
        status_tone = _status_tone(status_text)
        test_result_html = "<span class=\"dash\">—</span>" if test_result == "—" else f"<span class=\"pill {test_tone}\">{html.escape(test_result)}</span>"
        rendered.append(
            f"<tr>"
            f"<td>{html.escape(row['action'])}</td>"
            f"<td>{html.escape(row['kpi_to_improve'])}</td>"
            f"<td><span class='pill {result_tone}'>{html.escape(row['result'])}</span></td>"
            f"<td>{test_result_html}</td>"
            f"<td>{_guardrail_html(row)}</td>"
            f"<td class='period'><span>{html.escape(row['launch_at'])}</span><small>{html.escape(row['closed_at'])}</small></td>"
            f"<td class='reason-cell'>{html.escape(row['reason'])}</td>"
            f"<td><span class='pill {status_tone}'>{html.escape(status_text)}</span></td>"
            f"</tr>"
        )
    return (
        "<table class='history-table'><thead><tr><th>Action</th><th>KPI to Improve</th><th>Result</th><th>Test Result</th><th>Guardrail</th><th>Test Period</th><th>Decision Reason</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(rendered)}</tbody></table>"
    )


def _render_synthetic_banner(view_model: dict[str, Any]) -> str:
    warning = view_model.get("warning")
    if not warning and view_model.get("mode") == "synthetic_demo":
        warning = SYNTHETIC_WARNING
    return f'<div class="synthetic-banner">{html.escape(str(warning))}</div>' if warning else ""

