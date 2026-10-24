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
function renderAccounts() {
  $('account-count').textContent = accounts.length;
  $('accounts').replaceChildren();
  if(!accounts.length) $('accounts').append(element('p','muted','No accounts yet. Create one to get started.'));
  accounts.forEach((account, i) => {
    const card = element('button','account-card'); card.type = 'button'; card.setAttribute('aria-label',`View ${account.name} statement`);
    const top = element('div','account-card-top');
    const name = element('div','account-name'); name.append(element('span','account-icon',['▦','◇','⇄'][i%3]),element('span','',account.name));
    top.append(name,element('span','account-code',account.id.slice(-8).toUpperCase()));
    const bottom = element('div','account-card-bottom'); bottom.append(element('span','account-amount',money(account.balance_minor,account.currency)),element('span','account-currency',`${account.currency} · Available ↗`));
    card.append(top,bottom); card.onclick = () => showStatement(account); $('accounts').append(card);
  });
  const current = $('source').value;
  $('source').replaceChildren(...accounts.map(a => new Option(`${a.name} · ${money(a.balance_minor,a.currency)}`,a.id)));
  if(accounts.some(a => a.id === current)) $('source').value = current;
  renderDestinations();
}
function renderDestinations() {
  const current = $('destination').value;
  const source = accounts.find(a => a.id === $('source').value);
  $('amount-currency').textContent = source?.currency || 'GBP';
  const choices = accounts.filter(a => a.id !== source?.id && a.currency === source?.currency);
  $('destination').replaceChildren(...choices.map(a => new Option(a.name,a.id)));
  if(choices.some(a => a.id === current)) $('destination').value = current;
  $('submit-transfer').disabled = busy || !choices.length;
}
function showJournal(journal) {
  $('detail-title').textContent = 'Journal details'; $('detail-body').replaceChildren();
  const meta = element('p','detail-meta',`${journal.reference} · ${time(journal.created_at)}\n${journal.id}`);
  meta.style.whiteSpace = 'pre-line'; $('detail-body').append(meta);
  journal.postings.forEach(p => {
    const row = element('div','detail-posting'); const name = element('div','',p.account_name);
    name.append(element('small','',p.amount_minor < 0 ? 'Debit · funds out' : 'Credit · funds in'));
    row.append(name,element('strong',p.amount_minor < 0 ? 'negative' : 'positive',money(p.amount_minor,journal.currency)));
    $('detail-body').append(row);
  });
  const sum = journal.postings.reduce((s,p) => s + p.amount_minor,0);
  $('detail-body').append(element('p','detail-meta',`Net movement: ${money(sum,journal.currency)} · ${journal.status} · Immutable journal`));
  $('details').showModal();
}
async function showStatement(account) {
  try {
    const {body} = await api(`/api/accounts/${encodeURIComponent(account.id)}/entries?limit=100`);
    $('detail-title').textContent = account.name; $('detail-body').replaceChildren(element('div','detail-amount',money(body.balance_minor,account.currency)),element('p','detail-meta','Latest 100 entries, including the demo opening balance.'));
    if(!body.items.length) $('detail-body').append(element('p','muted','No entries yet.'));
    body.items.forEach(entry => { const row = element('div','detail-posting'); const name = element('div','',entry.reference); name.append(element('small','',time(entry.created_at))); row.append(name,element('strong',entry.amount_minor < 0 ? 'negative' : 'positive',money(entry.amount_minor,account.currency))); $('detail-body').append(row); });
    $('details').showModal();
  } catch(error) { notify(error.message,true); }
}
function renderTransfers(data) {
  $('transfers').replaceChildren();
  if(!data.items.length) { const row = element('tr'); const cell = element('td','empty','No transfers yet. Your first transfer will appear here.'); cell.colSpan = 6; row.append(cell); $('transfers').append(row); }
  data.items.forEach(journal => {
    const row = element('tr'), reference = element('td');
    reference.append(element('div','cell-main',journal.reference),element('div','cell-sub',journal.id.slice(0,8)));
    const path = element('td'); path.append(element('div','cell-main',journal.postings[0].account_name),element('div','muted',`→ ${journal.postings[1].account_name}`));
    const status = element('td'); status.append(element('span','posted','● Posted'));
    const action = element('td'), button = element('button','row-details','↗'); button.setAttribute('aria-label',`View journal ${journal.reference}`); button.onclick = () => showJournal(journal); action.append(button);
    row.append(reference,path,element('td','amount-cell',money(journal.postings[1].amount_minor,journal.currency)),status,element('td','',time(journal.created_at)),action); $('transfers').append(row);
  });
  $('page-info').textContent = data.total ? `${offset+1}–${Math.min(offset+pageSize,data.total)} of ${data.total} transfers` : '0 transfers';
  $('previous').disabled = offset === 0; $('next').disabled = offset + pageSize >= data.total;
}
async function refresh() {
  const [a,s,t] = await Promise.all([api('/api/accounts'),api('/api/summary'),api(`/api/transfers?limit=${pageSize}&offset=${offset}`)]);
  accounts = a.body.items; summary = s.body; renderAccounts(); renderSummary(); renderTransfers(t.body);
}
