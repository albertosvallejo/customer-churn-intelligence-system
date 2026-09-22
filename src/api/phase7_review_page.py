import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from api.phase7_reporting_page import (
    DASHBOARD_ROUTE,
    NEW_ACTIONS_ROUTE,
    TESTED_ACTIONS_ROUTE,
    _base_styles,
    _fmt,
    _format_dt,
    _format_percent,
    _render_history_rows,
    _render_sidebar,
    _render_synthetic_banner,
    _result_label,
    _status_label,
    _title_case_kpi,
)
from evidence.phase7_artifacts import SYNTHETIC_WARNING, resolve_phase7_mode
from evidence.phase7_integration import (
    build_phase7_post_test_decision_queue,
    load_integrated_actions,
    load_phase7_action_history,
)


TECHNICAL_REFRESH_TOOLTIP = (
    "This page refreshes after the same user submits a decision. "
    "There is no automatic polling on approval pages."
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _proposal_title(action: Dict[str, Any]) -> str:
    title = str(action.get("article_title") or "").strip()
    return title or str(action.get("proposal_id") or action.get("action_id") or "Untitled proposal")


def _proposal_recommended_action(action: Dict[str, Any]) -> str:
    return str(action.get("recommended_action") or "").strip() or "—"


def _business_label_for_kpi(value: str) -> str:
    mapping = {
        "checkout_completion_rate": "Checkout completion",
        "cart_recovery_rate": "Cart recovery",
        "average_order_value_lift": "Average order value",
    }
    key = str(value or "").strip()
    return mapping.get(key, _title_case_kpi(key)) if key else "—"


def _proposal_source(action: Dict[str, Any]) -> str:
    return str(action.get("source_name") or "").strip() or "Unknown source"


def _status_from_action(action: Dict[str, Any]) -> str:
    lifecycle = str(action.get("lifecycle_state") or "").lower()
    latest_verdict = str(action.get("latest_verdict") or "")
    if lifecycle == "active_winner":
        return "Approved"
    if lifecycle == "stat_test_completed" and latest_verdict == "B_wins":
        return "Pending for approval"
    if lifecycle == "rejected" or latest_verdict == "A_wins":
        return "Rejected"
    if lifecycle in {"approved_for_stat_test", "pending_review"}:
        return "Approved"
    return "Pending of more data"


def _result_from_action(action: Dict[str, Any]) -> str:
    latest_verdict = str(action.get("latest_verdict") or "")
    if latest_verdict:
        return _result_label(latest_verdict)
    return "Not enough data yet"


def _test_result_from_action(action: Dict[str, Any]) -> str:
    result = _result_from_action(action)
    if result == "Not enough data yet":
        return "—"
    return _format_percent(action.get("latest_conversion_lift") or action.get("conversion_lift"))


def _guardrail_tooltip(action: Dict[str, Any]) -> str:
    if bool(action.get("guardrail_breach")):
        return "Risk detected in a monitored guardrail metric."
    return "All monitored guardrails remained within threshold."


def _build_tested_action_rows(post_test_queue: Dict[str, Any], integrated_actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for pending in post_test_queue.get("pending_decisions", []):
        action = next((row for row in integrated_actions if row.get("action_id") == pending.get("action_id")), {})
        candidate_incumbents = pending.get("candidate_incumbents") or []
        previous_action = candidate_incumbents[0] if candidate_incumbents else {}
        allowed_comparison_outcomes = pending.get("allowed_comparison_outcomes") or []
        allowed_decisions_by_comparison_outcome = pending.get("allowed_decisions_by_comparison_outcome") or {}
        missing_fields: List[str] = []
        if not candidate_incumbents:
            missing_fields.append("current action comparison")
        if not allowed_comparison_outcomes:
            missing_fields.append("comparison outcome options")
        if not any(allowed_decisions_by_comparison_outcome.values()):
            missing_fields.append("decision options")
        can_decide = not missing_fields
        rows.append(
            {
                "action_id": pending.get("action_id"),
                "proposal_name": _proposal_title(action or pending),
                "proposal_id": pending.get("proposal_id") or action.get("proposal_id") or "—",
                "proposal_href": "#proposal",
                "kpi_to_improve": _business_label_for_kpi(str(action.get("primary_kpi") or action.get("recommended_kpi") or "")),
                "result": _result_from_action(action),
                "test_result": _test_result_from_action(action),
                "guardrail_risk": bool(action.get("guardrail_breach")),
                "guardrail_tooltip": _guardrail_tooltip(action),
                "launch_at": _format_dt(action.get("launch_ts") or action.get("latest_launch_ts")),
                "closed_at": _format_dt(action.get("latest_stat_completed_at") or action.get("latest_stat_ts") or action.get("lifecycle_updated_at")),
                "status": _status_from_action(action),
                "business_context": str(action.get("summary_for_business") or "").strip() or "No business context available.",
                "recommended_action": _proposal_recommended_action(action),
                "can_decide": can_decide,
                "missing_fields": missing_fields,
                "decision_blocker_message": "Missing required decision context: " + ", ".join(missing_fields) if missing_fields else "",
                "previous_action": {
                    "action_id": previous_action.get("action_id"),
                    "article_title": previous_action.get("article_title"),
                    "status_label": str(previous_action.get("status_label") or "Current action"),
                    "summary": str(previous_action.get("summary") or "").strip(),
                },
                "candidate_incumbents": candidate_incumbents,
                "allowed_comparison_outcomes": allowed_comparison_outcomes,
                "allowed_decisions_by_comparison_outcome": allowed_decisions_by_comparison_outcome,
            }
        )
    return rows


def _build_new_action_rows(integrated_actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for action in integrated_actions:
        if action.get("approval_status") != "pending_review":
            continue
        recommended_action = _proposal_recommended_action(action)
        lifecycle_state = str(action.get("lifecycle_state") or "pending_review")
        missing_fields: List[str] = []
        if recommended_action == "—":
            missing_fields.append("recommended action")
        can_review = not missing_fields
        rows.append(
            {
                "action_id": action.get("action_id"),
                "proposal_id": action.get("proposal_id"),
                "title": _proposal_title(action),
                "source": _proposal_source(action),
                "summary": str(action.get("summary_for_business") or "").strip() or "No summary available.",
                "recommended_action": recommended_action,
                "lifecycle_state": lifecycle_state,
                "lifecycle_label": lifecycle_state.replace("_", " ").title(),
                "business_kpi": _business_label_for_kpi(str(action.get("primary_kpi") or action.get("recommended_kpi") or "")),
                "can_review": can_review,
                "decision_blocker_message": "Missing required proposal context: " + ", ".join(missing_fields) if missing_fields else "",
            }
        )
    return rows


def _build_history_rows_from_integrated(history: List[Dict[str, Any]], integrated_actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from api.phase7_reporting_page import _build_history_rows

    return _build_history_rows(history, integrated_actions)


def build_phase7_review_page_view_model(project_root: Path, run_date: str | None = None, mode: str | None = None) -> Dict[str, Any]:
    resolved_mode = resolve_phase7_mode(mode)
    integrated = load_integrated_actions(project_root, run_date, resolved_mode)
    post_test_queue = build_phase7_post_test_decision_queue(
        project_root,
        run_date,
        resolved_mode,
        integrated_actions_payload=integrated,
    )
    history = load_phase7_action_history(project_root, run_date=run_date, mode=resolved_mode)
    pending_pre_test_actions = _build_new_action_rows(integrated.get("actions", []))
    pending_post_test_actions = _build_tested_action_rows(post_test_queue, integrated.get("actions", []))
    return {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "run_date": integrated["run_date"],
        "mode": resolved_mode,
        "warning": "SYNTHETIC DATA — NOT REAL RESULTS" if resolved_mode == "synthetic_demo" else None,
        "pre_test_pending_count": len(pending_pre_test_actions),
        "post_test_pending_count": len(pending_post_test_actions),
        "pending_pre_test_actions": pending_pre_test_actions,
        "pending_post_test_decisions": pending_post_test_actions,
        "history_rows": _build_history_rows_from_integrated(history, integrated.get("actions", [])),
    }


def _render_tested_action_table_rows(rows: List[Dict[str, Any]]) -> str:
    rendered: List[str] = []
    for row in rows:
        result_tone = "positive" if row["result"] == "New proposal wins" else "neutral"
        test_result = str(row["test_result"])
        test_tone = "positive" if test_result.startswith("+") else ("negative" if test_result.startswith("-") else "neutral")
        status_tone = "warning" if "approval" in row["status"].lower() else "neutral"
        incumbent_options = "".join(
            f"<option value='{html.escape(str(candidate.get('action_id') or ''))}'>{html.escape(str(candidate.get('action_id') or ''))} · {html.escape(str(candidate.get('article_title') or ''))}</option>"
            for candidate in row["candidate_incumbents"]
        )
        outcome_options = "".join(
            f"<option value='{html.escape(str(value))}'>{html.escape(str(value).replace('_', ' ').title())}</option>"
            for value in row["allowed_comparison_outcomes"]
        )
        decisions_json = html.escape(json.dumps(row["allowed_decisions_by_comparison_outcome"]))
        test_result_html = "<span class=\"dash\">—</span>" if test_result == "—" else f"<span class=\"pill {test_tone}\">{html.escape(test_result)}</span>"
        rendered.append(
            f"<tr data-action-id='{html.escape(str(row['action_id']))}' data-decisions='{decisions_json}'>"
            f"<td class='proposal-cell'><a href='{html.escape(row['proposal_href'])}'>{html.escape(row['proposal_name'])}</a><span>{html.escape(str(row['proposal_id']))}</span></td>"
            f"<td>{html.escape(row['kpi_to_improve'])}</td>"
            f"<td><span class='pill {result_tone}'>{html.escape(row['result'])}</span></td>"
            f"<td>{test_result_html}</td>"
            f"<td><span class='risk-tip' data-tip='{html.escape(row['guardrail_tooltip'])}'><span class='pill {'negative' if row['guardrail_risk'] else 'positive'}'>{'Risk detected' if row['guardrail_risk'] else 'No risks detected'}</span></span></td>"
            f"<td class='period'><span>{html.escape(row['launch_at'])}</span><small>{html.escape(row['closed_at'])}</small></td>"
            f"<td><span class='pill {status_tone}'>{html.escape(row['status'])}</span></td>"
            f"<td><div class='row-actions'><button class='accept' type='button' data-kind='accept'>Accept</button><button class='reject-link' type='button' data-kind='open-reject'>Reject</button></div>"
            f"<div class='inline-form'><label>Incumbent<select name='comparison_target_action_id'>{incumbent_options}</select></label><label>Outcome<select name='comparison_outcome'>{outcome_options}</select></label><label>Decision<select name='decision_type'></select></label><input name='decided_by' type='text' value='dashboard-review' placeholder='decided_by' /><textarea name='decision_reason' placeholder='Decision reason'></textarea></div>"
            f"<div class='status' data-role='result'></div></td>"
            f"</tr>"
        )
    return "".join(rendered) if rendered else "<tr><td colspan='8'>No tested actions are pending approval.</td></tr>"


def _render_new_action_cards(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "<div class='empty-state'>No proposals are waiting to enter statistical test.</div>"
    rendered = []
    for row in rows:
        rendered.append(
            f"<article class='proposal-card' data-action-id='{html.escape(str(row['action_id']))}'>"
            f"<div class='proposal-top'><div class='id-group'><span>{html.escape(str(row['action_id']))}</span><span>{html.escape(str(row['proposal_id']))}</span></div><span class='pill blue'>Ready for review</span></div>"
            f"<h3>{html.escape(row['title'])}</h3>"
            f"<p class='source'>Source: <strong>{html.escape(row['source'])}</strong> <span>·</span> Lifecycle: {html.escape(str(row['lifecycle_state']))}</p>"
            f"<p class='proposal-summary'>{html.escape(row['summary'])}</p>"
            f"<div class='recommendation'><span>Recommended action</span><p>{html.escape(row['recommended_action'])}</p></div>"
            f"<label class='decision-note'><span>Decision reason <small>Optional for approval</small></span><textarea name='decision_reason' placeholder='Add context for the audit trail…'></textarea></label>"
            f"<input name='decided_by' type='text' value='dashboard-review' placeholder='decided_by' />"
            f"<div class='proposal-actions'><button class='primary' type='button' data-status='approved'>Approve for test</button><button class='secondary' type='button' data-status='postponed'>Postpone</button><button class='danger' type='button' data-status='rejected'>Reject</button><span class='reject-hint'>A reason is required to reject</span></div>"
            f"<div class='status' data-role='result'></div></article>"
        )
    return "".join(rendered)


def _review_page_styles() -> str:
    return _base_styles() + """
.approval-header { align-items: center; }
.queue-count { flex: 0 0 auto; min-width: 140px; min-height: 82px; padding: 14px 18px; border-radius: 12px; background: #f6f1df; border: 1px solid #eadba5; display: flex; align-items: center; gap: 13px; }
.queue-count span { color: #8f6b0a; font-size: 32px; font-weight: 800; }
.queue-count p { margin: 0; color: #735d25; font-size: 10px; line-height: 1.4; font-weight: 750; text-transform: uppercase; letter-spacing: .045em; }
.notice { margin-top: 15px; padding: 13px 16px; display: flex; align-items: center; gap: 12px; border: 1px solid #cfe3d6; border-radius: 10px; background: #f0f8f3; color: #275d3c; }
.notice > span { width: 25px; height: 25px; display: grid; place-items: center; border-radius: 50%; background: #dcefe3; font-size: 12px; font-weight: 900; }
.notice strong { font-size: 11px; }
.notice p { margin: 3px 0 0; color: #668071; font-size: 10px; }
.row-actions { display: flex; gap: 6px; }
.row-actions button { padding: 7px 9px; border-radius: 6px; font-size: 9px; font-weight: 750; }
.row-actions .accept, .proposal-actions .primary { border: 1px solid var(--green); background: var(--green); color: #fff; }
.row-actions .reject-link { border: 1px solid #d7a6a6; background: #fff; color: var(--red); }
.inline-form { display: grid; gap: 8px; margin-top: 10px; }
.inline-form label { color: #536174; font-size: 9px; font-weight: 750; }
.inline-form select, .inline-form textarea, .inline-form input, .decision-note textarea, .proposal-card input { width: 100%; margin-top: 5px; border: 1px solid #ccd5df; border-radius: 6px; background: #fff; color: #405066; padding: 7px 8px; font-size: 9px; }
.inline-form textarea, .decision-note textarea { min-height: 48px; resize: vertical; }
.danger { border: 1px solid var(--red); background: var(--red); color: #fff; }
.danger:disabled { cursor: not-allowed; opacity: .38; }
.secondary { border: 1px solid #bac4cf; background: #fff; color: #536174; }
.toast { position: fixed; z-index: 90; right: 24px; top: 52px; min-width: 310px; padding: 13px 17px 13px 45px; border-radius: 10px; background: #10233c; color: #fff; box-shadow: 0 14px 36px rgba(9, 27, 49, .3); font-size: 11px; font-weight: 700; opacity: 0; pointer-events: none; transition: opacity .18s ease; }
.toast.show { opacity: 1; }
.toast > span { position: absolute; left: 15px; top: 13px; width: 20px; height: 20px; display: grid; place-items: center; border-radius: 50%; background: var(--green); }
.toast small { display: block; margin-top: 3px; color: #a9b7c8; font-size: 9px; font-weight: 500; }
.list-heading { margin: 24px 2px 14px; align-items: end; }
.filter-control { padding: 8px 11px; border: 1px solid #d4dce4; background: #fff; border-radius: 8px; color: #69778a; font-size: 10px; }
.proposal-list { display: grid; gap: 14px; }
.proposal-card { background: #fff; border: 1px solid #dde4eb; border-radius: 14px; padding: 22px 24px; box-shadow: 0 6px 22px rgba(29, 50, 74, .045); }
.proposal-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.id-group { display: flex; gap: 6px; }
.id-group span { padding: 5px 8px; border-radius: 999px; background: #edf3fa; color: var(--blue); font-size: 8px; font-weight: 800; }
.proposal-card h3 { margin: 14px 0 7px; color: var(--deep-blue); font-size: 16px; line-height: 1.35; }
.source { margin: 0 0 13px; color: #85909e; font-size: 10px; }
.source strong { color: #657386; }
.source span { padding: 0 4px; }
.proposal-summary { margin: 0 0 13px; max-width: 1100px; color: #405067; font-size: 11px; line-height: 1.5; }
.recommendation { padding: 11px 13px; border-left: 3px solid var(--blue); background: #f3f7fa; border-radius: 0 8px 8px 0; }
.recommendation span { color: var(--blue); font-size: 8px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.recommendation p { margin: 4px 0 0; color: #58677a; font-size: 10px; line-height: 1.45; }
.decision-note { display: grid; margin-top: 14px; }
.decision-note > span { margin-bottom: 6px; color: #536176; font-size: 9px; font-weight: 800; }
.decision-note small { margin-left: 4px; color: #9ca5b0; font-weight: 500; }
.proposal-actions { display: flex; gap: 8px; align-items: center; margin-top: 12px; flex-wrap: wrap; }
.reject-hint { color: #9aa4af; font-size: 8px; }
"""


def _review_page_script(kind: str, config: Dict[str, str]) -> str:
    return f"""
<script>
window.__CUSTOMER_CHURN_REVIEW__ = {json.dumps(config)};
(function () {{
  const cfg = window.__CUSTOMER_CHURN_REVIEW__;
  const toast = document.getElementById('toast');
  function showToast(message) {{
    if (!toast) return;
    toast.querySelector('.toast-message').textContent = message;
    toast.classList.add('show');
    window.setTimeout(() => toast.classList.remove('show'), 2600);
  }}
  async function refreshPageData() {{
    const response = await fetch(cfg.dataUrl, {{ headers: {{ Accept: 'application/json' }} }});
    if (!response.ok) throw new Error('Refresh failed');
    const payload = await response.json();
    showToast('State refreshed.');
    return payload;
  }}
  function bindTestedRows() {{
    document.querySelectorAll('tr[data-action-id]').forEach(function (row) {{
      const decisions = JSON.parse(row.getAttribute('data-decisions') || '{{}}');
      const outcomeSelect = row.querySelector('select[name="comparison_outcome"]');
      const decisionSelect = row.querySelector('select[name="decision_type"]');
      function syncDecisions() {{
        const selectedOutcome = outcomeSelect.value;
        const allowed = decisions[selectedOutcome] || [];
        decisionSelect.innerHTML = allowed.map(function (value) {{ return `<option value="${{value}}">${{String(value).replace(/_/g, ' ')}}</option>`; }}).join('');
      }}
      if (outcomeSelect && decisionSelect) {{ outcomeSelect.addEventListener('change', syncDecisions); syncDecisions(); }}
      row.querySelector('[data-kind="accept"]').addEventListener('click', async function () {{
        const body = {{
          action_id: row.getAttribute('data-action-id'),
          proposal_run_date: cfg.runDate,
          comparison_target_action_id: row.querySelector('select[name="comparison_target_action_id"]').value,
          comparison_outcome: row.querySelector('select[name="comparison_outcome"]').value,
          decision_type: row.querySelector('select[name="decision_type"]').value || 'promote_challenger',
          previous_incumbent_status: 'replaced',
          decision_reason: row.querySelector('textarea[name="decision_reason"]').value || 'Approved after tested-actions review',
          decided_by: row.querySelector('input[name="decided_by"]').value || 'dashboard-review',
        }};
        const response = await fetch(cfg.postTestDecisionUrl, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json', 'X-Phase7-Token': cfg.token }}, body: JSON.stringify(body) }});
        if (!response.ok) throw new Error(await response.text());
        await refreshPageData();
        window.location.reload();
      }});
      row.querySelector('[data-kind="open-reject"]').addEventListener('click', async function () {{
        const reason = window.prompt('Reject reason (Worse performance / Guardrail risk / Operational constraints / Other)', 'Worse performance') || 'Worse performance';
        let note = '';
        if (reason !== 'Worse performance') note = window.prompt('Decision note', '') || '';
        if (reason !== 'Worse performance' && !note.trim()) return;
        const outcome = reason === 'Worse performance' ? 'incumbent_keeps' : 'inconclusive';
        const decisionType = reason === 'Worse performance' ? 'keep_incumbent' : 'retire_candidate';
        const response = await fetch(cfg.postTestDecisionUrl, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json', 'X-Phase7-Token': cfg.token }}, body: JSON.stringify({{
          action_id: row.getAttribute('data-action-id'),
          proposal_run_date: cfg.runDate,
          comparison_target_action_id: row.querySelector('select[name="comparison_target_action_id"]').value,
          comparison_outcome: outcome,
          decision_type: decisionType,
          previous_incumbent_status: null,
          decision_reason: note || reason,
          decided_by: row.querySelector('input[name="decided_by"]').value || 'dashboard-review',
        }}) }});
        if (!response.ok) throw new Error(await response.text());
        await refreshPageData();
        window.location.reload();
      }});
    }});
  }}
  function bindNewActionCards() {{
    document.querySelectorAll('.proposal-card[data-action-id]').forEach(function (card) {{
      card.querySelectorAll('[data-status]').forEach(function (button) {{
        button.addEventListener('click', async function () {{
          const status = button.getAttribute('data-status');
          const reason = card.querySelector('textarea[name="decision_reason"]').value.trim();
          if (status === 'rejected' && !reason) return;
          const response = await fetch(cfg.decisionUrl, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json', 'X-Phase7-Token': cfg.token }}, body: JSON.stringify({{
            action_id: card.getAttribute('data-action-id'),
            proposal_run_date: cfg.runDate,
            decision_status: status,
            decision_reason: reason || (status === 'approved' ? 'Approved for test' : status === 'postponed' ? 'Postponed for later review' : 'Rejected'),
            decided_by: card.querySelector('input[name="decided_by"]').value || 'dashboard-review',
          }}) }});
          if (!response.ok) throw new Error(await response.text());
          await refreshPageData();
          window.location.reload();
        }});
      }});
    }});
  }}
  try {{
    if ({json.dumps(kind)} === 'tested') bindTestedRows();
    if ({json.dumps(kind)} === 'new') bindNewActionCards();
  }} catch (error) {{ console.error(error); }}
}})();
</script>
"""

