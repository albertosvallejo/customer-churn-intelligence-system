import { ROUTES, buildHeaders, fetchJson, qs, setStoredToken, setVisibility, showToast, clearStoredToken, withRunDate, downloadCsv, renderPagination, resultTone, testResultTone, statusTone, guardrailTone } from './base.js?v=20260820r3';

let latestPayload = null;
let historyPage = 1;
let pendingDecisionRequest = null;

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
    const runDate = latestPayload?.run_date || 'latest';
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

function setAuthError(message) {
  const authError = qs('#auth-error');
  if (!authError) return;
  authError.textContent = message;
  setVisibility(authError, Boolean(message));
}

function requireStoredToken() {
  const token = qs('#phase7-token-input')?.value?.trim() || '';
  if (token) {
    setStoredToken(token);
    setAuthError('');
    return token;
  }
  if (buildHeaders({ withToken: true })['X-Phase7-Token']) {
    setAuthError('');
    return buildHeaders({ withToken: true })['X-Phase7-Token'];
  }
  setVisibility(qs('#auth-gate'), true);
  setAuthError('Phase 7 review token is required before submitting a decision.');
  qs('#phase7-token-input')?.focus();
  return '';
}

function handleWriteAuthFailure(response, payload) {
  clearStoredToken();
  setVisibility(qs('#auth-gate'), true);
  if (response.status === 503) {
    setAuthError(payload?.error || 'Phase 7 review token is not configured.');
    showToast(payload?.error || 'Phase 7 review token is not configured.', 'Write unavailable');
    return;
  }
  setAuthError(payload?.error || 'Invalid or expired Phase 7 review token.');
  showToast(payload?.error || 'Invalid or expired Phase 7 review token.', 'Authentication required');
}

function renderDecisionDrawer(row, decisionKind) {
  const drawer = qs('#decision-drawer');
  const isReject = decisionKind === 'reject';
  const previousAction = row.previous_action || {};
  if (!row.can_decide) {
    showToast(row.decision_blocker_message || 'Missing required decision context.', 'Decision blocked');
    return;
  }
  drawer.innerHTML = `
    <div>
      <strong>${isReject ? 'Reject winning proposal' : 'Accept winning proposal'}</strong>
      <p>${isReject ? 'Keep the current action and record the business reason.' : 'Promote the winning proposal and replace the current action.'}</p>
    </div>
    <label>Winning proposal<input type="text" value="${escapeHtml(row.proposal_name || '')}" disabled /></label>
    <label>Current action<input type="text" value="${escapeHtml(previousAction.article_title || '')}" disabled /></label>
    <label>Recommendation<textarea disabled>${escapeHtml(row.recommended_action || '—')}</textarea></label>
    <label>Business context<textarea disabled>${escapeHtml(row.business_context || '—')}</textarea></label>
    <label>Decision reason<textarea id="drawer-reason" placeholder="${isReject ? 'Explain why the current action should remain active…' : 'Add optional rollout context for the audit trail…'}"></textarea></label>
    <p id="drawer-reason-hint" class="form-hint ${isReject ? '' : 'is-hidden'}">A reason is required when rejecting the winning proposal.</p>
    <label>Decided by<input id="drawer-decided-by" type="text" placeholder="portfolio-operator" value="portfolio-operator" /></label>
    <div class="cta-row"><button id="drawer-submit" class="cta-button primary" type="button">${isReject ? 'Reject' : 'Accept'}</button><button id="drawer-cancel" class="cta-button" type="button">Cancel</button></div>
  `;
  drawer.classList.remove('is-hidden');

  const reasonInput = qs('#drawer-reason', drawer);
  const reasonHint = qs('#drawer-reason-hint', drawer);
  const syncValidationUi = () => {
    reasonHint.classList.toggle('is-hidden', !isReject || Boolean(reasonInput.value.trim()));
  };

  reasonInput.addEventListener('input', syncValidationUi);
  qs('#drawer-cancel', drawer).addEventListener('click', () => drawer.classList.add('is-hidden'));
  qs('#drawer-submit', drawer).addEventListener('click', async () => {
    if (isReject && !reasonInput.value.trim()) {
      syncValidationUi();
      return;
    }
    const token = requireStoredToken();
    if (!token) return;
    const body = {
      action_id: row.action_id,
      comparison_target_action_id: previousAction.action_id,
      comparison_outcome: isReject ? 'incumbent_keeps' : 'candidate_wins',
      decision_type: isReject ? 'keep_incumbent' : 'promote_challenger',
      decision_reason: reasonInput.value.trim() || 'Winning proposal accepted after tested-actions review',
      decided_by: qs('#drawer-decided-by', drawer).value.trim() || 'portfolio-operator',
      proposal_run_date: latestPayload?.run_date || undefined,
      previous_incumbent_status: isReject ? 'active' : 'replaced',
    };
    pendingDecisionRequest = body;
    const { response, payload } = await fetchJson(withRunDate(ROUTES.postTestDecision), {
      method: 'POST',
      headers: buildHeaders({ withToken: true, json: true }),
      body: JSON.stringify(body)
    });
    if (!response.ok) {
      if (response.status === 401 || response.status === 503) {
        handleWriteAuthFailure(response, payload);
      } else {
        showToast(payload?.error || `HTTP ${response.status}`, 'Submit failed');
      }
      syncValidationUi();
      return;
    }
    pendingDecisionRequest = null;
    showToast(isReject ? 'Current action kept' : 'Winning proposal adopted', 'State refreshed');
    drawer.classList.add('is-hidden');
    await loadTestedActions();
  });

  syncValidationUi();
}

function renderTestedActions(payload) {
  latestPayload = payload;
  setVisibility(qs('#synthetic-banner'), Boolean(payload?.warning));
  if (payload?.warning) qs('#synthetic-banner').textContent = payload.warning;
  qs('#run-meta').textContent = `Run date: ${payload?.run_date || 'latest'} · Rendered at: ${payload?.generated_at || 'n/a'}`;
  qs('#queue-count').textContent = payload?.post_test_pending_count ?? 0;
  qs('#tested-pending-pill').textContent = `${payload?.post_test_pending_count ?? 0} pending`;

  const rows = payload?.pending_post_test_decisions || [];
  qs('#tested-rows').innerHTML = rows.map((row) => `
    <tr>
      <td class="proposal-cell"><a href="#proposal">${escapeHtml(row.proposal_name || '—')}</a><span>${escapeHtml(row.previous_action?.status_label || 'Current action')}</span></td>
      <td>${escapeHtml(row.kpi_to_improve || '—')}</td>
      <td><span class="pill ${resultTone(row.result)}">${escapeHtml(row.result || '—')}</span></td>
      <td>${String(row.test_result || '—') === '—' ? '<span class="dash">—</span>' : `<span class="pill ${testResultTone(row.test_result)}">${escapeHtml(row.test_result)}</span>`}</td>
      <td><span class="pill ${guardrailTone(row.guardrail_risk)}" title="${escapeHtml(row.guardrail_tooltip || '')}">${escapeHtml(row.guardrail || (row.guardrail_risk === true ? 'Risk detected' : row.guardrail_risk === false ? 'No risks detected' : '—'))}</span></td>
      <td><span>${escapeHtml(row.launch_at || '—')}</span><br /><small>${escapeHtml(row.closed_at || '—')}</small></td>
      <td><span class="pill ${statusTone(row.status)}">${escapeHtml(row.status || '—')}</span></td>
      <td>
        <div class="row-actions">
          <button class="cta-button primary" type="button" data-open-decision="accept:${escapeHtml(row.action_id)}" ${row.can_decide ? '' : 'disabled'}>Accept</button>
          <button class="cta-button" type="button" data-open-decision="reject:${escapeHtml(row.action_id)}" ${row.can_decide ? '' : 'disabled'}>Reject</button>
        </div>
        ${row.can_decide ? '' : `<p class="form-hint decision-blocker">${escapeHtml(row.decision_blocker_message || 'Decision blocked')}</p>`}
      </td>
    </tr>
  `).join('');

  setVisibility(qs('#tested-panel'), true);
  setVisibility(qs('#tested-empty'), rows.length === 0);
  const historyRows = payload?.history_rows || [];
  renderHistory(historyRows);
  bindHistoryInteractions(historyRows);

  document.querySelectorAll('[data-open-decision]').forEach((button) => {
    button.addEventListener('click', () => {
      const [kind, actionId] = String(button.getAttribute('data-open-decision') || '').split(':');
      const row = rows.find((item) => item.action_id === actionId);
      if (row) renderDecisionDrawer(row, kind);
    });
  });
}

async function loadTestedActions() {
  const loading = qs('#view-loading');
  const error = qs('#view-error');
  setVisibility(loading, true);
  setVisibility(error, false);

  const { response, payload } = await fetchJson(withRunDate(ROUTES.testedData), { headers: buildHeaders({ withToken: true }) });
  setVisibility(loading, false);

  if (response.status === 401 || response.status === 503) {
    if (response.status === 401) {
      clearStoredToken();
      setVisibility(qs('#auth-gate'), true);
      setAuthError(payload?.error || 'Invalid or expired Phase 7 review token.');
    } else {
      setVisibility(qs('#auth-gate'), true);
      setAuthError(payload?.error || 'Phase 7 review token is not configured.');
    }
    return;
  }

  if (!response.ok) {
    qs('#view-error-message').textContent = payload?.error || `HTTP ${response.status}`;
    setVisibility(error, true);
    return;
  }

  setVisibility(qs('#auth-gate'), false);
  setAuthError('');
  setVisibility(qs('#tested-notice'), true);
  renderTestedActions(payload);
}

function bindAuthGate() {
  qs('#phase7-token-submit')?.addEventListener('click', async () => {
    const token = qs('#phase7-token-input')?.value?.trim() || '';
    if (!token) {
      setAuthError('Phase 7 review token is required before submitting a decision.');
      return;
    }
    setStoredToken(token);
    setAuthError('');
    if (pendingDecisionRequest) {
      const { response, payload } = await fetchJson(withRunDate(ROUTES.postTestDecision), {
        method: 'POST',
        headers: buildHeaders({ withToken: true, json: true }),
        body: JSON.stringify(pendingDecisionRequest)
      });
      if (!response.ok) {
        handleWriteAuthFailure(response, payload);
        return;
      }
      pendingDecisionRequest = null;
      showToast('Winning proposal decision submitted', 'State refreshed');
      qs('#decision-drawer')?.classList.add('is-hidden');
    }
    void loadTestedActions();
  });
}

window.addEventListener('DOMContentLoaded', () => {
  bindAuthGate();
  setVisibility(qs('#auth-gate'), false);
  void loadTestedActions();
});
