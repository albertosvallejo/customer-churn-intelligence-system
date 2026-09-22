import { ROUTES, buildHeaders, fetchJson, qs, setStoredToken, setVisibility, showToast, clearStoredToken, withRunDate } from './base.js?v=20260820r3';

let latestPayload = null;

function ensureAuthGate() {
  const gate = qs('#auth-gate');
  if (!gate || gate.childElementCount > 0) return gate;
  gate.innerHTML = `
    <section class="panel auth-panel auth-panel-modal">
      <div class="section-heading"><div><p class="section-kicker">ACCESS</p><h2>Operator token required</h2><p>Enter the current Phase 7 review token to continue to the protected proposal queue.</p></div></div>
      <div class="auth-form"><input id="phase7-token-input" type="password" placeholder="Phase 7 token" /><button id="phase7-token-submit" class="cta-button primary" type="button">Unlock</button></div>
      <p id="auth-error" class="form-hint is-hidden">Invalid or expired token.</p>
    </section>
  `;
  bindAuthGate();
  return gate;
}

function showAuthGate() {
  const gate = ensureAuthGate();
  setVisibility(gate, true);
}

function hideAuthGate() {
  const gate = qs('#auth-gate');
  if (gate) setVisibility(gate, false);
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
  showAuthGate();
  setAuthError('Phase 7 review token is required before recording a proposal decision.');
  qs('#phase7-token-input')?.focus();
  return '';
}

function handleWriteAuthFailure(response, payload) {
  clearStoredToken();
  showAuthGate();
  if (response.status === 503) {
    setAuthError(payload?.error || 'Phase 7 review token is not configured.');
    showToast(payload?.error || 'Phase 7 review token is not configured.', 'Write unavailable');
    return;
  }
  setAuthError(payload?.error || 'Invalid or expired Phase 7 review token.');
  showToast(payload?.error || 'Invalid or expired Phase 7 review token.', 'Authentication required');
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
}

function renderNewActions(payload) {
  latestPayload = payload;
  setVisibility(qs('#synthetic-banner'), Boolean(payload?.warning));
  if (payload?.warning) qs('#synthetic-banner').textContent = payload.warning;
  qs('#run-meta').textContent = `Snapshot date: ${payload?.run_date || 'latest'} · Rendered at: ${payload?.generated_at || 'n/a'}`;
  qs('#queue-count').textContent = payload?.pre_test_pending_count ?? 0;
  qs('#proposal-pending-count').textContent = `${payload?.pre_test_pending_count ?? 0} pending`;

  const rows = payload?.pending_pre_test_actions || [];
  qs('#proposal-list').innerHTML = rows.map((row) => `
    <article class="proposal-card ${row.can_review ? '' : 'is-blocked'}">
      <div class="section-heading">
        <div>
          <p class="section-kicker">NEW PROPOSAL</p>
          <h2>${escapeHtml(row.title || row.article_title || 'Untitled proposal')}</h2>
          <p class="proposal-meta">${escapeHtml(row.source || row.source_name || 'Unknown source')} · ${escapeHtml(row.lifecycle_label || 'Pending review')}</p>
        </div>
        <span class="pill info">Pending review</span>
      </div>
      <p class="proposal-summary-copy">${escapeHtml(row.summary || 'No summary available.')}</p>
      <div class="proposal-detail-grid">
        <div class="detail-card"><p class="section-kicker">BUSINESS KPI</p><p>${escapeHtml(row.business_kpi || 'To be confirmed')}</p></div>
        <div class="detail-card"><p class="section-kicker">RECOMMENDED ACTION</p><p>${escapeHtml(row.recommended_action || 'Recommendation pending definition')}</p></div>
      </div>
      ${row.can_review ? '' : `<p class="form-hint decision-blocker">${escapeHtml(row.decision_blocker_message || 'Missing required proposal context.')}</p>`}
      <label class="decision-note"><span>Decision reason <small>Optional for approval</small></span><textarea data-reason="${escapeHtml(row.action_id)}" placeholder="Add context for the audit trail…"></textarea></label>
      <p class="form-hint is-hidden" data-reason-hint="${escapeHtml(row.action_id)}">A reason is required to reject or postpone.</p>
      <div class="cta-row">
        <button class="cta-button primary" type="button" data-action="approve" data-action-id="${escapeHtml(row.action_id)}" ${row.can_review ? '' : 'disabled'}>Approve for test</button>
        <button class="cta-button" type="button" data-action="postpone" data-action-id="${escapeHtml(row.action_id)}" ${row.can_review ? '' : 'disabled'}>Postpone</button>
        <button class="cta-button" type="button" data-action="reject" data-action-id="${escapeHtml(row.action_id)}" ${row.can_review ? '' : 'disabled'}>Reject</button>
      </div>
    </article>
  `).join('');

  setVisibility(qs('#proposal-heading'), true);
  setVisibility(qs('#proposal-list'), rows.length > 0);
  setVisibility(qs('#proposal-empty'), rows.length === 0);

  document.querySelectorAll('[data-action-id]').forEach((button) => {
    button.addEventListener('click', async () => {
      const actionId = button.getAttribute('data-action-id');
      const verb = button.getAttribute('data-action');
      const reason = document.querySelector(`[data-reason="${actionId}"]`)?.value?.trim() || '';
      const hint = document.querySelector(`[data-reason-hint="${actionId}"]`);
      if ((verb === 'reject' || verb === 'postpone') && !reason) {
        hint?.classList.remove('is-hidden');
        return;
      }
      hint?.classList.add('is-hidden');
      if (!button.disabled) {
        const token = requireStoredToken();
        if (!token) return;
      }
      const body = {
        action_id: actionId,
        decision_status: verb === 'approve' ? 'approved' : verb === 'reject' ? 'rejected' : 'postponed',
        decision_reason: reason || (verb === 'approve' ? 'Approved from portfolio dashboard' : ''),
        decided_by: 'portfolio-operator',
        proposal_run_date: latestPayload?.run_date || undefined
      };
      const { response, payload } = await fetchJson(withRunDate(ROUTES.decision), {
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
        return;
      }
      showToast('New action decision recorded', 'State refreshed');
      await loadNewActions();
    });
  });
}

async function loadNewActions() {
  const loading = qs('#view-loading');
  const error = qs('#view-error');
  setVisibility(loading, true);
  setVisibility(error, false);

  const { response, payload } = await fetchJson(withRunDate(ROUTES.newActionsData), { headers: buildHeaders({ withToken: true }) });
  setVisibility(loading, false);

  if (response.status === 401 || response.status === 503) {
    if (response.status === 401) {
      clearStoredToken();
      showAuthGate();
      setAuthError(payload?.error || 'Invalid or expired Phase 7 review token.');
    } else {
      showAuthGate();
      setAuthError(payload?.error || 'Phase 7 review token is not configured.');
    }
    return;
  }

  if (!response.ok) {
    qs('#view-error-message').textContent = payload?.error || `HTTP ${response.status}`;
    setVisibility(error, true);
    return;
  }

  hideAuthGate();
  setAuthError('');
  renderNewActions(payload);
}

function bindAuthGate() {
  qs('#phase7-token-submit')?.addEventListener('click', () => {
    const token = qs('#phase7-token-input')?.value?.trim() || '';
    if (!token) {
      setAuthError('Phase 7 review token is required before recording a proposal decision.');
      return;
    }
    setStoredToken(token);
    setAuthError('');
    void loadNewActions();
  });
}

window.addEventListener('DOMContentLoaded', () => {
  hideAuthGate();
  void loadNewActions();
});
