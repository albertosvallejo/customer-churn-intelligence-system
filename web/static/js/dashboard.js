import { ROUTES, fetchJson, qs, setVisibility, downloadCsv, renderPagination, withRunDate, resultTone, testResultTone, statusTone, guardrailTone } from './base.js?v=20260820r3';

let latestPayload = null;
let historyPage = 1;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function historyRowHtml(row) {
  return `
    <tr>
      <td>${escapeHtml(row.action || row.proposal_name || '—')}</td>
      <td>${escapeHtml(row.kpi_to_improve || '—')}</td>
      <td><span class="pill ${resultTone(row.result)}">${escapeHtml(row.result || '—')}</span></td>
      <td><span class="pill ${String(row.test_result || '—') === '—' ? 'neutral' : testResultTone(row.test_result)}">${escapeHtml(row.test_result || '—')}</span></td>
      <td><span class="pill ${String(row.guardrail || row.guardrail_status || '—') === '—' ? 'neutral' : guardrailTone(row.guardrail_risk)}" title="${escapeHtml(row.guardrail_tooltip || '')}">${escapeHtml(row.guardrail || row.guardrail_status || '—')}</span></td>
      <td>${escapeHtml(row.test_period || '—')}</td>
      <td>${escapeHtml(row.decision_reason || row.reason || '—')}</td>
      <td><span class="pill ${statusTone(row.status)}">${escapeHtml(row.status || '—')}</span></td>
    </tr>
  `;
}

function renderHistory(rows) {
  historyPage = renderPagination({
    rows,
    pageSize: 5,
    page: historyPage,
    body: qs('#history-rows'),
    pager: qs('#history-pagination'),
    renderRow: historyRowHtml,
  });
  setVisibility(qs('#history-panel'), true);
  setVisibility(qs('#history-empty'), rows.length === 0);
}

function bindHistoryInteractions(rows) {
  qs('#history-pagination')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-page]');
    if (!button) return;
    historyPage = Number(button.getAttribute('data-page')) || 1;
    renderHistory(rows);
  });

  qs('#history-export')?.addEventListener('click', () => {
    const runDate = latestPayload?.requested_run_date || latestPayload?.kpi_status?.run_date || 'latest';
    downloadCsv(`phase7_history_${runDate}.csv`, [
      ['Action', 'KPI to Improve', 'Result', 'Test Result', 'Guardrail', 'Test Period', 'Decision Reason', 'Status'],
      ...rows.map((row) => [
        row.action || row.proposal_name || '—',
        row.kpi_to_improve || '—',
        row.result || '—',
        row.test_result || '—',
        row.guardrail || row.guardrail_status || '—',
        row.test_period || '—',
        row.decision_reason || row.reason || '—',
        row.status || '—',
      ]),
    ]);
  });
}

function renderDashboard(payload) {
  latestPayload = payload;
  const warning = payload?.warning;
  setVisibility(qs('#synthetic-banner'), Boolean(warning));
  if (warning) qs('#synthetic-banner').textContent = warning;

  const effectiveRunDate = payload?.effective_run_date || payload?.requested_run_date || 'latest';
  qs('#run-meta').textContent = `Snapshot date: ${effectiveRunDate} · KPI artifact generated at ${payload?.kpi_status?.generated_at || payload?.generated_at || 'n/a'}`;
  qs('#poll-meta').textContent = payload?.poll_ms ? `Auto-refresh every ${Math.max(1, Math.round(payload.poll_ms / 60000))} minutes` : 'Auto-refresh not configured';

  const kpiChips = qs('#kpi-chips');
  const chips = payload?.kpi_chips || [];
  kpiChips.innerHTML = chips.map((chip) => `
    <div class="kpi-chip ${chip.state ? `is-${escapeHtml(chip.state)}` : ''}">
      <span class="chip-dot ${escapeHtml(chip.tone || '')}"></span>
      <div class="kpi-chip-copy">
        <span class="kpi-chip-label">${escapeHtml(chip.kpi)}</span>
        <small class="kpi-chip-subtitle">${escapeHtml(chip.subtitle)}</small>
      </div>
      <strong class="kpi-chip-value ${chip.pending ? 'pending' : ''} ${chip.empty ? 'empty' : ''}">${escapeHtml(chip.value)}</strong>
    </div>
  `).join('');
  setVisibility(kpiChips, chips.length > 0);

  const summary = payload?.summary || {};
  document.querySelector('[data-summary="test_count"]').textContent = summary.test_count ?? '—';
  document.querySelector('[data-summary="completed_test_count"]').textContent = summary.completed_test_count ?? '—';
  document.querySelector('[data-summary="winner_test_count"]').textContent = summary.winner_test_count ?? '—';
  document.querySelector('[data-summary="guardrail_breach_count"]').textContent = summary.guardrail_breach_count ?? '—';
  setVisibility(qs('#summary-grid'), true);

  const campaignRows = payload?.campaign_rows || [];
  qs('#campaign-rows').innerHTML = campaignRows.map((row) => `
    <tr>
      <td class="proposal-cell"><a href="#proposal">${escapeHtml(row.proposal_name || row.action || '—')}</a><span>${escapeHtml(row.proposal_id || row.action_id || '—')}</span></td>
      <td>${escapeHtml(row.kpi_to_improve || '—')}</td>
      <td><span class="pill ${resultTone(row.result)}">${escapeHtml(row.result || '—')}</span></td>
      <td>${String(row.test_result || '—') === '—' ? '<span class="dash">—</span>' : `<span class="pill ${testResultTone(row.test_result)}">${escapeHtml(row.test_result)}</span>`}</td>
      <td><span class="pill ${guardrailTone(row.guardrail_risk)}" title="${escapeHtml(row.guardrail_tooltip || '')}">${escapeHtml(row.guardrail || (row.guardrail_risk === true ? 'Risk detected' : row.guardrail_risk === false ? 'No risks detected' : '—'))}</span></td>
      <td><span>${escapeHtml(row.launch_at || row.launched_at || '—')}</span><br /><small>${escapeHtml(row.closed_at || '—')}</small></td>
      <td><span class="pill ${statusTone(row.status)}">${escapeHtml(row.status || '—')}</span></td>
    </tr>
  `).join('');
  setVisibility(qs('#campaign-panel'), true);
  setVisibility(qs('#campaign-empty'), campaignRows.length === 0);

  const historyRows = payload?.history_rows || [];
  renderHistory(historyRows);
  bindHistoryInteractions(historyRows);
}

async function loadDashboard() {
  const loading = qs('#dashboard-loading');
  const error = qs('#dashboard-error');
  const unauthorized = qs('#dashboard-unauthorized');
  setVisibility(loading, true);
  setVisibility(error, false);
  setVisibility(unauthorized, false);

  const { response, payload } = await fetchJson(withRunDate(ROUTES.dashboardData));

  setVisibility(loading, false);

  if (response.status === 401) {
    setVisibility(unauthorized, true);
    return;
  }

  if (!response.ok) {
    qs('#dashboard-error-message').textContent = payload?.error || `HTTP ${response.status}`;
    setVisibility(error, true);
    return;
  }

  renderDashboard(payload);
}

qs('#dashboard-retry')?.addEventListener('click', () => { void loadDashboard(); });
window.addEventListener('DOMContentLoaded', () => {
  void loadDashboard();
});
