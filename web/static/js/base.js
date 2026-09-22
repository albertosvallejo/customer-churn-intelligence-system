export const ROUTES = {
  dashboard: '/customer-churn/dashboard',
  dashboardData: '/customer-churn/dashboard/data',
  tested: '/customer-churn/tested-actions-approval',
  testedData: '/customer-churn/tested-actions-approval/data',
  newActions: '/customer-churn/new-actions-testing',
  newActionsData: '/customer-churn/new-actions-testing/data',
  decision: '/phase7/actions/decision',
  postTestDecision: '/phase7/actions/post-test-decision'
};

export const TOKEN_STORAGE_KEY = 'phase7_review_token';

export function getStoredToken() {
  return window.sessionStorage.getItem(TOKEN_STORAGE_KEY) || '';
}

export function setStoredToken(token) {
  window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearStoredToken() {
  window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function buildHeaders({ withToken = false, json = false } = {}) {
  const headers = {};
  if (json) headers['Content-Type'] = 'application/json';
  if (withToken) {
    const token = getStoredToken();
    if (token) headers['X-Phase7-Token'] = token;
  }
  return headers;
}

export async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload = null;
  try { payload = await response.json(); } catch (_) { payload = null; }
  return { response, payload };
}

export function showToast(message, detail = 'State refreshed') {
  const toast = document.getElementById('toast');
  if (!toast) return;
  const messageNode = toast.querySelector('.toast-message');
  const detailNode = toast.querySelector('small');
  if (messageNode) messageNode.textContent = message;
  if (detailNode) detailNode.textContent = detail;
  toast.classList.add('is-visible');
  window.clearTimeout(showToast._timer);
  showToast._timer = window.setTimeout(() => toast.classList.remove('is-visible'), 2600);
}

export function setVisibility(element, visible) {
  if (!element) return;
  element.classList.toggle('is-hidden', !visible);
}

export function qs(selector, root = document) {
  return root.querySelector(selector);
}

export function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

export function currentRunDate() {
  return new URLSearchParams(window.location.search).get('run_date') || '';
}

export function withRunDate(url) {
  const runDate = currentRunDate();
  if (!runDate) return url;
  const target = new URL(url, window.location.origin);
  target.searchParams.set('run_date', runDate);
  return `${target.pathname}${target.search}`;
}

export function notImplemented(name) {
  return () => {
    console.warn(`${name} not implemented yet.`);
  };
}

function csvEscape(value) {
  const text = String(value ?? '');
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function downloadCsv(filename, rows) {
  const content = rows.map((row) => row.map(csvEscape).join(',')).join('\n');
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function resultTone(value) {
  const text = String(value || '').toLowerCase();
  if (text === 'new proposal wins' || text === 'approved' || text === 'approved for test') return 'positive';
  if (text === 'current action wins' || text === 'rejected' || text === 'rejected before test') return 'negative';
  return 'neutral';
}

export function testResultTone(value) {
  const text = String(value || '').trim();
  if (text.startsWith('+')) return 'positive';
  if (text.startsWith('-') || text.startsWith('−')) return 'negative';
  return 'neutral';
}

export function statusTone(value) {
  const text = String(value || '').toLowerCase();
  if (text === 'approved') return 'positive';
  if (text === 'rejected') return 'negative';
  if (text === 'pending for approval') return 'warning';
  return 'neutral';
}

export function guardrailTone(value) {
  if (value === true) return 'negative';
  if (value === false) return 'positive';
  return 'neutral';
}

export function renderPagination({ rows, pageSize = 5, page = 1, body, pager, renderRow }) {
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(Math.max(page, 1), totalPages);
  const start = (safePage - 1) * pageSize;
  const slice = rows.slice(start, start + pageSize);
  body.innerHTML = slice.map(renderRow).join('');
  if (!pager) return safePage;
  pager.innerHTML = totalPages <= 1 ? '' : `
    <button type="button" class="pagination-button" data-page="${safePage - 1}" aria-label="Show previous page" ${safePage === 1 ? 'disabled' : ''}>Previous</button>
    <span class="pagination-status" aria-live="polite">Page ${safePage} of ${totalPages}</span>
    <button type="button" class="pagination-button" data-page="${safePage + 1}" aria-label="Show next page" ${safePage === totalPages ? 'disabled' : ''}>Next</button>
  `;
  pager.classList.toggle('is-hidden', totalPages <= 1);
  return safePage;
}
