/**
 * AI Agent Dashboard — live trading console.
 */

const STRAT_LABELS = { 'AI-AGENT': 'AI Agent', 'TEST': 'Test' };

// Signal-type detection from journal entry's reason field. The agent's
// "strategy" field is always AI-AGENT; the actual signal lives in `reason`.
const SIGNAL_PATTERNS = [
    { key: 'asymmetric',   label: '♻️ Asymmetric Bet',  re: /asymmetric|paris.weather|insider.signal/i },
    { key: 'daily_repeat', label: '🔁 Daily Repeating',  re: /daily.repeat|infinite.money|trump.insult/i },
    { key: 'near_resolve', label: '🎯 Near-Resolution',  re: /near.resolution|resolution.arb|80.99|mispricing/i },
    { key: 'inconsist',    label: '⚖️ Inconsistencies',  re: /inconsistenc|temporal.arb|hierarchy.arb/i },
    { key: 'stock_arb',    label: '📈 Stock Arb',         re: /stock.arb|spy|qqq|s&p/i },
    { key: 'smart_money',  label: '🐳 Smart Money',       re: /smart.money|leaderboard|copy.trad/i },
    { key: 'auditor',      label: '🏛️ Auditor Pattern',  re: /auditor|kpmg|deloitte|earnings.insider/i },
    { key: 'conviction',   label: '🎤 Own Conviction',    re: /conviction|own.thesis|narrative/i },
];

function detectSignal(reason) {
    if (!reason) return { key: 'other', label: '❓ Other' };
    for (const p of SIGNAL_PATTERNS) {
        if (p.re.test(reason)) return p;
    }
    return { key: 'other', label: '❓ Other' };
}

function fmtMoney(v, opts = {}) {
    if (v == null || isNaN(v)) return '--';
    const sign = v >= 0 ? (opts.sign ? '+' : '') : '';
    return `${sign}$${v.toFixed(2)}`;
}
function fmtPct(v) { if (v == null || isNaN(v)) return '--'; return `${(v * 100).toFixed(0)}%`; }
function pnlClass(v) { if (v == null) return ''; return v > 0 ? 'pnl-positive' : v < 0 ? 'pnl-negative' : ''; }

function shortTime(iso) {
    if (!iso) return '?';
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    return d.toLocaleDateString('en-GB', { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

function relativeTime(iso) {
    if (!iso) return '';
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    const diffMs = Date.now() - d.getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function classifyBook(price) {
    if (price > 0 && price <= 0.03) return 'moonshot';
    if (price >= 0.80) return 'core';
    return 'opportunistic';
}

let _allTheses = [];
let _thesisFilter = 'high'; // default: only high+extreme conviction

async function fetchAll() {
    try {
        const [status, journal, summary] = await Promise.all([
            fetch('/api/agent/status').then(r => r.json()),
            fetch('/api/agent/journal?limit=20').then(r => r.json()),
            fetch('/api/agent/daily-summary').then(r => r.json()),
        ]);
        renderHeadline(summary, status);
        renderPositions(status.portfolio?.positions || []);
        renderSignalBreakdown(journal);
        renderEntries(journal.enters || []);
        renderExits(journal.exits || []);
        _allTheses = status.theses?.active || [];
        renderTheses();
        const thinking = await fetch('/api/agent/thinking?limit=5').then(r => r.json());
        renderThinking(thinking || []);
        document.getElementById('last-update').textContent = `Updated ${new Date().toLocaleTimeString('en-GB')}`;
    } catch (e) {
        console.error('Fetch failed:', e);
    }
}

function renderHeadline(summary, status) {
    const p24 = summary.pnl_24h || {};
    const lt = summary.lifetime || {};
    const pnl24 = p24.pnl_usd || 0;
    const pnlLt = lt.total_pnl || 0;
    const winrate = lt.win_rate || 0;
    const exposure = summary.exposure || 0;
    const balance = summary.balance || 0;
    const positions = (summary.open_positions || []).length;
    const maxPos = status.limits?.max_positions || 30;
    const maxExp = status.limits?.max_total_exposure || 100;

    const el24 = document.getElementById('pnl-24h');
    el24.textContent = fmtMoney(pnl24, { sign: true });
    el24.className = `value ${pnlClass(pnl24)}`;
    const elLt = document.getElementById('pnl-lifetime');
    elLt.textContent = fmtMoney(pnlLt, { sign: true });
    elLt.className = `value ${pnlClass(pnlLt)}`;
    document.getElementById('winrate').textContent = lt.trades ? `${(winrate * 100).toFixed(0)}% (${lt.wins}W/${lt.losses}L)` : '--';
    document.getElementById('exposure').textContent = `$${exposure.toFixed(2)} / $${maxExp}`;
    document.getElementById('positions').textContent = `${positions} / ${maxPos}`;
    document.getElementById('balance').textContent = `$${balance.toFixed(2)}`;
}

function renderPositions(positions) {
    const el = document.getElementById('positions-list');
    document.getElementById('positions-count').textContent = positions.length;
    if (!positions.length) { el.innerHTML = '<div class="empty">No open positions.</div>'; return; }
    const sorted = [...positions].sort((a, b) => (b.amount_usd || 0) - (a.amount_usd || 0));
    el.innerHTML = sorted.map(p => {
        const q = escapeHtml((p.market_question || '?').substring(0, 75));
        const amt = (p.amount_usd || 0).toFixed(2);
        const price = p.price || 0;
        const priceDisplay = price > 1 ? `${price.toFixed(1)}¢` : `${(price * 100).toFixed(1)}¢`;
        const book = classifyBook(price > 1 ? price / 100 : price);
        const bookEmoji = { core: '📘', moonshot: '🚀', opportunistic: '🎯' }[book];
        return `<div class="position-row">
            <div class="market">${q}<div class="meta">${bookEmoji} ${book}</div></div>
            <div class="price">${priceDisplay}</div>
            <div class="stake">$${amt}</div>
        </div>`;
    }).join('');
}

function renderSignalBreakdown(journal) {
    const el = document.getElementById('strategy-table');
    const exits = journal.exits || [];
    const opens = journal.enters || [];

    // Group exits by detected signal type
    const byKey = {};
    for (const e of exits) {
        const sig = detectSignal(e.reason || '');
        if (!byKey[sig.key]) byKey[sig.key] = { label: sig.label, pnl: 0, trades: 0, wins: 0, open: 0 };
        const pnl = e.pnl_usd;
        if (pnl != null) {
            byKey[sig.key].pnl += pnl;
            byKey[sig.key].trades += 1;
            if (pnl > 0) byKey[sig.key].wins += 1;
        }
    }
    // Count open positions per signal
    const openTokens = new Set(opens.filter(e => !exits.find(x => x.token_id === e.token_id)).map(e => e.token_id));
    for (const e of opens) {
        if (!openTokens.has(e.token_id)) continue;
        const sig = detectSignal(e.reason || '');
        if (!byKey[sig.key]) byKey[sig.key] = { label: sig.label, pnl: 0, trades: 0, wins: 0, open: 0 };
        byKey[sig.key].open += 1;
    }

    const rows = Object.values(byKey).filter(r => r.trades || r.open).sort((a, b) => b.pnl - a.pnl);
    if (!rows.length) { el.innerHTML = '<div class="empty">No closed trades yet.</div>'; return; }
    let html = `<div class="strat-row header">
        <div>Signal</div>
        <div style="text-align:right">P&amp;L</div>
        <div style="text-align:right">Win</div>
        <div style="text-align:right">Open</div>
    </div>`;
    html += rows.map(r => `<div class="strat-row">
        <div class="name">${r.label}</div>
        <div class="pnl ${pnlClass(r.pnl)}">${fmtMoney(r.pnl, { sign: true })}</div>
        <div class="winrate">${r.trades ? `${Math.round(r.wins / r.trades * 100)}% (${r.wins}/${r.trades})` : '–'}</div>
        <div class="open">${r.open}</div>
    </div>`).join('');
    el.innerHTML = html;
}

function renderEntries(entries) {
    const el = document.getElementById('entries-list');
    document.getElementById('entries-count').textContent = entries.length;
    if (!entries.length) { el.innerHTML = '<div class="empty">No entries yet.</div>'; return; }
    el.innerHTML = entries.slice(0, 12).map(e => {
        const q = escapeHtml((e.market_question || '?').substring(0, 70));
        const reason = escapeHtml((e.reason || '').substring(0, 100));
        const amt = (e.amount_usd || 0).toFixed(2);
        const ts = shortTime(e.timestamp);
        const sig = detectSignal(e.reason || '');
        return `<div class="trade-row entry">
            <div class="ts">${ts}</div>
            <div class="market"><span class="strategy-tag">${sig.label}</span>${q}<div class="thesis">${reason}</div></div>
            <div class="amount">$${amt}</div>
        </div>`;
    }).join('');
}

function renderExits(exits) {
    const el = document.getElementById('exits-list');
    document.getElementById('exits-count').textContent = exits.length;
    if (!exits.length) { el.innerHTML = '<div class="empty">No exits yet.</div>'; return; }
    el.innerHTML = exits.slice(0, 12).map(e => {
        const q = escapeHtml((e.market_question || '?').substring(0, 70));
        const exitReason = escapeHtml((e.exit_reason || e.reason || '').substring(0, 100));
        const pnl = e.pnl_usd;
        const ts = shortTime(e.timestamp);
        let pnlText, rowClass;
        if (pnl == null) { pnlText = 'unresolved'; rowClass = 'exit-unknown'; }
        else if (pnl > 0) { pnlText = `+$${pnl.toFixed(2)}`; rowClass = 'exit-win'; }
        else { pnlText = `$${pnl.toFixed(2)}`; rowClass = 'exit-loss'; }
        return `<div class="trade-row ${rowClass}">
            <div class="ts">${ts}</div>
            <div class="market">${q}<div class="thesis">${exitReason}</div></div>
            <div class="amount">${pnlText}</div>
        </div>`;
    }).join('');
}

function setThesisFilter(f) {
    _thesisFilter = f;
    document.querySelectorAll('.thesis-controls button').forEach(b => b.classList.toggle('active', b.dataset.filter === f));
    renderTheses();
}

function renderTheses() {
    const el = document.getElementById('thesis-list');
    document.getElementById('thesis-count').textContent = _allTheses.length;
    let theses = _allTheses;
    if (_thesisFilter === 'high') {
        theses = theses.filter(t => {
            const c = (t.conviction || '').toLowerCase();
            return c === 'high' || c === 'extreme';
        });
    } else if (_thesisFilter === 'recent') {
        theses = [...theses].sort((a, b) => (b.updated || b.created || '').localeCompare(a.updated || a.created || '')).slice(0, 10);
    }
    if (!theses.length) {
        el.innerHTML = `<div class="empty">No ${_thesisFilter === 'all' ? '' : _thesisFilter + ' '}theses.</div>`;
        return;
    }
    // Sort by updated desc
    theses = [...theses].sort((a, b) => (b.updated || b.created || '').localeCompare(a.updated || a.created || ''));
    el.innerHTML = theses.map(t => {
        const conviction = (t.conviction || 'medium').toLowerCase();
        const history = t.history || [];
        const latestNote = history.length ? escapeHtml(history[history.length - 1].note || '') : '';
        const updated = t.updated || t.created;
        const created = t.created;
        return `<div class="thesis-row">
            <div>
                <div class="title">${escapeHtml(t.title || '')}</div>
                <div class="note">${latestNote.substring(0, 150)}</div>
                <div class="meta">Updated ${relativeTime(updated)} · created ${shortTime(created)}</div>
            </div>
            <div class="conv ${conviction}">${conviction}</div>
        </div>`;
    }).join('');
}

function renderThinking(entries) {
    const el = document.getElementById('thinking-list');
    if (!entries.length) { el.innerHTML = '<div class="empty">Waiting for next cycle...</div>'; return; }
    el.innerHTML = entries.slice(0, 5).map(e => {
        const ts = shortTime(e.timestamp);
        const text = e.thinking || '';
        const points = parseThinking(text);
        let body;
        if (points.length >= 3) {
            body = '<div class="thinking-points">' + points.map(p => {
                const isExposure = /current.exposure|exposure:|deployed/i.test(p.label);
                return `<div class="thinking-point ${isExposure ? 'exposure' : ''}">
                    <div class="label">${escapeHtml(p.label)}</div>
                    <div class="body">${escapeHtml(p.body)}</div>
                </div>`;
            }).join('') + '</div>';
        } else {
            body = `<div class="thinking-fallback">${escapeHtml(text)}</div>`;
        }
        return `<div class="thinking-entry">
            <div class="thinking-time">${ts}</div>
            ${body}
        </div>`;
    }).join('');
}

/**
 * Parse the agent's "1. INSIDER: ... 2. SMART MONEY: ..." structure into
 * an array of { label, body }. Falls back to the raw string if not parseable.
 */
function parseThinking(text) {
    if (!text) return [];
    // Split on points like "1. ", "2. ", "3b. ", "8. " — match number + optional letter + dot + space
    // Then capture everything until the next such marker.
    const regex = /(\d+[a-z]?\.\s+)([A-Z][A-Z\s\-/&]+:)\s*([^]*?)(?=(?:\s*\d+[a-z]?\.\s+[A-Z][A-Z\s\-/&]+:)|$)/g;
    const points = [];
    let m;
    while ((m = regex.exec(text)) !== null) {
        const num = m[1].trim().replace(/\.$/, '');
        const label = num + ' ' + m[2].replace(':', '').trim();
        const body = m[3].trim();
        if (body) points.push({ label, body });
    }
    // Also extract a CURRENT EXPOSURE block if present and not already captured
    const expMatch = text.match(/current.exposure[:\s]+([^]*?)(?=\n\n|$)/i);
    if (expMatch && !points.some(p => /exposure/i.test(p.label))) {
        points.push({ label: 'CURRENT EXPOSURE', body: expMatch[1].trim() });
    }
    return points;
}

async function triggerCycle() {
    const btn = event.target;
    btn.disabled = true; btn.textContent = '⏳ Running...';
    try {
        await fetch('/api/agent/run', { method: 'POST' });
        await fetchAll();
    } catch (e) { alert('Failed: ' + e.message); }
    btn.disabled = false; btn.textContent = '⚡ Run Cycle Now';
}

async function triggerTriage() {
    const btn = event.target;
    btn.disabled = true; btn.textContent = '⏳ Triaging...';
    try {
        const r = await fetch('/api/agent/triage-failures?limit=100', { method: 'POST' });
        const data = await r.json();
        const summary = data.summary || {};
        const modes = summary.by_mode || {};
        const lines = [`Triaged ${data.triaged || 0} failures.`];
        if (Object.keys(modes).length) {
            lines.push('\nBy mode:');
            for (const [m, c] of Object.entries(modes).sort((a, b) => b[1] - a[1])) {
                lines.push(`  ${m}: ${c}`);
            }
        }
        const inv = data.needs_investigation || [];
        if (inv.length) {
            lines.push(`\n${inv.length} unknown failure(s) need investigation:`);
            inv.slice(0, 5).forEach(i => lines.push(`  • ${i.market_question?.substring(0, 60)}`));
        } else if (data.triaged > 0) {
            lines.push('\n✅ All failures now caught by current pre-flight.');
        }
        alert(lines.join('\n'));
        btn.textContent = '✅ Done';
        setTimeout(() => { btn.textContent = '🔧 Triage Failures'; btn.disabled = false; }, 3000);
    } catch (e) {
        alert('Failed: ' + e.message);
        btn.disabled = false; btn.textContent = '🔧 Triage Failures';
    }
}

async function triggerSummary() {
    const btn = event.target;
    btn.disabled = true; btn.textContent = '⏳ Sending...';
    try {
        await fetch('/api/agent/daily-summary', { method: 'POST' });
        btn.textContent = '✅ Sent';
        setTimeout(() => { btn.textContent = '📰 Send Daily Summary'; btn.disabled = false; }, 2000);
    } catch (e) { alert('Failed: ' + e.message); btn.disabled = false; btn.textContent = '📰 Send Daily Summary'; }
}

fetchAll();
setInterval(fetchAll, 30000);
