'use strict';
const $ = id => document.getElementById(id);
const money = (value, currency = 'GBP') => new Intl.NumberFormat('en-GB', {style:'currency',currency}).format(value / 100);
const time = value => new Intl.DateTimeFormat('en-GB', {hour:'2-digit',minute:'2-digit',day:'2-digit',month:'short'}).format(new Date(value));
const element = (tag, className, text) => { const el = document.createElement(tag); if(className) el.className = className; if(text !== undefined) el.textContent = text; return el; };
let accounts = [], summary = null, offset = 0, lastRequest = null, draft = null, busy = false;
const pageSize = 8;
let pending = null;
try { pending = JSON.parse(sessionStorage.getItem('clearledger-pending') || 'null'); } catch { /* A new request can still be made if browser storage is unavailable. */ }

function savePending(value) {
  pending = value;
  try { value ? sessionStorage.setItem('clearledger-pending', JSON.stringify(value)) : sessionStorage.removeItem('clearledger-pending'); } catch { /* In-memory retry remains available. */ }
  $('retry-pending').hidden = !pending;
}
function notify(message, error = false) { $('notice').textContent = message; $('notice').className = `notice${error ? ' error' : ''}`; $('notice').hidden = false; }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers:{'Content-Type':'application/json', ...options.headers}});
  const body = await response.json();
  if(!response.ok) {
    const message = body.error?.message || (Array.isArray(body.detail) ? body.detail.map(e => e.msg).join('; ') : 'Request failed. Please try again.');
    const error = new Error(message); error.status = response.status; throw error;
  }
  return {body, replayed:response.headers.get('Idempotent-Replayed') === 'true'};
}
function renderSummary() {
  if(!summary) return;
  const item = summary.currencies.find(c => c.currency === $('currency').value);
  $('total-balance').textContent = money(item?.balance_minor || 0, $('currency').value);
  $('volume').textContent = money(item?.volume_minor || 0, $('currency').value);
  $('transfer-count').textContent = summary.transfer_count;
  $('integrity').textContent = summary.integrity.balanced ? '● Ledger balanced' : 'Ledger needs attention';
  $('integrity').className = `pill${summary.integrity.balanced ? '' : ' integrity-error'}`;
}
