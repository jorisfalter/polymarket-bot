/**
 * AI Agent Dashboard — live trading console.
 * Pulls /api/agent/status, /journal, /strategy-summary, /thinking, /daily-summary.
 */

const STRAT_LABELS = {
    'AI-AGENT': 'AI Agent',
    'TEST': 'Test',
};

function fmtMoney(v, opts = {}) {
    if (v == null || isNaN(v)) return '--';
    const sign = v >= 0 ? (opts.sign ? '+' : '') : '';
    return `${sign}$${v.toFixed(2)}`;
}

function fmtPct(v) {
    if (v == null || isNaN(v)) return '--';
    return `${(v * 100).toFixed(0)}%`;
}

function pnlClass(v) {
    if (v == null) return '';
    return v > 0 ? 'pnl-positive' : v < 0 ? 'pnl-negative' : '';
}

function shortTime(iso) {
    if (!iso) return '?';
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    return d.toLocaleDateString('en-GB', { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
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

async function fetchAll() {
    try {
        const [status, journal, strategy, summary] = await Promise.all([
            fetch('/api/agent/status').then(r => r.json()),
            fetch('/api/agent/journal?limit=15').then(r => r.json()),
            fetch('/api/agent/strategy-summary').then(r => r.json()),
            fetch('/api/agent/daily-summary').then(r => r.json()),
        ]);
        renderHeadline(summary, status);
        renderPositions(status.portfolio?.positions || []);
        renderStrategies(strategy);
        renderEntries(journal.enters || []);
        renderExits(journal.exits || []);
        renderTheses(status.theses?.active || []);
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
    if (!positions.length) {
        el.innerHTML = '<div class="empty">No open positions.</div>';
        return;
    }
    // Sort by amount_usd desc
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

function renderStrategies(data) {
    const el = document.getElementById('strategy-table');
    const rows = data.by_strategy || [];
    if (!rows.length) {
        el.innerHTML = '<div class="empty">No closed trades yet.</div>';
        return;
    }
    rows.sort((a, b) => b.pnl - a.pnl);
    let html = `<div class="strat-row header">
        <div>Strategy</div>
        <div style="text-align:right">P&amp;L</div>
        <div style="text-align:right">Win Rate</div>
        <div style="text-align:right">Open</div>
    </div>`;
    html += rows.map(r => `<div class="strat-row">
        <div class="name">${escapeHtml(STRAT_LABELS[r.name] || r.name)}</div>
        <div class="pnl ${pnlClass(r.pnl)}">${fmtMoney(r.pnl, { sign: true })}</div>
        <div class="winrate">${fmtPct(r.win_rate)} (${r.wins}/${r.trades})</div>
        <div class="open">${r.open_positions}</div>
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
        const strat = e.strategy || '?';
        return `<div class="trade-row entry">
            <div class="ts">${ts}</div>
            <div class="market"><span class="strategy-tag">${strat}</span>${q}<div class="thesis">${reason}</div></div>
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
        const strat = e.strategy || '?';
        let pnlText, rowClass;
        if (pnl == null) {
            pnlText = 'unresolved';
            rowClass = 'exit-unknown';
        } else if (pnl > 0) {
            pnlText = `+$${pnl.toFixed(2)}`;
            rowClass = 'exit-win';
        } else {
            pnlText = `$${pnl.toFixed(2)}`;
            rowClass = 'exit-loss';
        }
        return `<div class="trade-row ${rowClass}">
            <div class="ts">${ts}</div>
            <div class="market"><span class="strategy-tag">${strat}</span>${q}<div class="thesis">${exitReason}</div></div>
            <div class="amount">${pnlText}</div>
        </div>`;
    }).join('');
}

function renderTheses(theses) {
    const el = document.getElementById('thesis-list');
    document.getElementById('thesis-count').textContent = theses.length;
    if (!theses.length) { el.innerHTML = '<div class="empty">No active theses.</div>'; return; }
    el.innerHTML = theses.map(t => {
        const conviction = (t.conviction || 'medium').toLowerCase();
        const history = t.history || [];
        const latestNote = history.length ? escapeHtml(history[history.length - 1].note || '') : '';
        return `<div class="thesis-card">
            <div><span class="title">${escapeHtml(t.title || '')}</span><span class="conv ${conviction}">${conviction}</span></div>
            <div class="note">${latestNote.substring(0, 200)}</div>
        </div>`;
    }).join('');
}

function renderThinking(entries) {
    const el = document.getElementById('thinking-list');
    if (!entries.length) { el.innerHTML = '<div class="empty">Waiting for next cycle...</div>'; return; }
    el.innerHTML = entries.slice(0, 5).map(e => {
        const ts = shortTime(e.timestamp);
        const text = escapeHtml(e.thinking || '').substring(0, 1500);
        return `<div class="thinking-entry">
            <div class="thinking-time">${ts}</div>
            <div class="thinking-text">${text}</div>
        </div>`;
    }).join('');
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

async function triggerSummary() {
    const btn = event.target;
    btn.disabled = true; btn.textContent = '⏳ Sending...';
    try {
        await fetch('/api/agent/daily-summary', { method: 'POST' });
        btn.textContent = '✅ Sent';
        setTimeout(() => { btn.textContent = '📰 Send Daily Summary'; btn.disabled = false; }, 2000);
    } catch (e) { alert('Failed: ' + e.message); btn.disabled = false; btn.textContent = '📰 Send Daily Summary'; }
}

// Initial + auto-refresh every 30s
fetchAll();
setInterval(fetchAll, 30000);
