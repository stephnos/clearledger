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
