/**
 * AI Agent Frontend
 * Shows the agent's thinking journal, portfolio, and performance
 */

async function fetchStatus() {
    try {
        const res = await fetch('/api/agent/status');
        const data = await res.json();
        renderStatus(data);
    } catch (e) {
        console.error('Failed to fetch agent status:', e);
    }
}

async function fetchThinking() {
    try {
        const res = await fetch('/api/agent/thinking?limit=20');
        const entries = await res.json();
        renderThinking(entries);
    } catch (e) {
        console.error('Failed to fetch thinking:', e);
    }
}

function renderStatus(data) {
    // Balance
    const bal = data.portfolio?.usdc_balance;
    document.getElementById('balance').textContent = bal != null ? `$${bal.toFixed(2)}` : '--';

    // Exposure
    const exp = data.portfolio?.total_exposure || 0;
    document.getElementById('exposure').textContent = `$${exp.toFixed(2)}`;

    // Positions
    document.getElementById('positions').textContent = `${data.portfolio?.open_positions || 0} / ${data.limits?.max_positions || 5}`;

    // P&L
    const perf = data.performance || {};
    const pnl = perf.total_pnl || 0;
    const pnlEl = document.getElementById('pnl');
    pnlEl.textContent = `$${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}`;
    pnlEl.className = `value ${pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`;

    // Status
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    if (data.enabled && data.has_api_key) {
        dot.className = 'status-dot active';
        text.textContent = 'LIVE';
    } else {
        dot.className = 'status-dot inactive';
        text.textContent = data.enabled ? 'NO KEY' : 'OFF';
    }

    // Model
    const model = data.model || '';
    document.getElementById('model-badge').textContent = model.includes('haiku') ? 'Haiku' : model.includes('sonnet') ? 'Sonnet' : model;

    // Theses
    const theses = data.theses?.active || [];
    renderTheses(theses);

    // Positions
    const positions = data.portfolio?.positions || [];
    const posSection = document.getElementById('positions-section');
    const posGrid = document.getElementById('positions-grid');
    if (positions.length > 0) {
        posSection.style.display = 'block';
        posGrid.innerHTML = positions.map(p => `
            <div class="position-card">
                <span class="market">${(p.market_question || '?').substring(0, 60)}</span>
                <span class="amount">$${(p.amount_usd || 0).toFixed(2)}</span>
            </div>
        `).join('');
    } else {
        posSection.style.display = 'none';
    }
}

function renderThinking(entries) {
    const panel = document.getElementById('thinking-panel');

    if (!entries || entries.length === 0) {
        panel.innerHTML = '<div class="no-thinking">Waiting for first cycle... The agent thinks every 5 minutes.</div>';
        return;
    }

    panel.innerHTML = entries.map(e => {
        const time = new Date(e.timestamp + 'Z').toLocaleString();
        const thinking = escapeHtml(e.thinking || '').substring(0, 800);
        const trades = e.trades || [];
        const watchlist = escapeHtml(e.watchlist_notes || '').substring(0, 200);
        const risk = escapeHtml(e.risk_assessment || '').substring(0, 200);

        let tradesHtml = '';
        if (trades.length > 0) {
            tradesHtml = '<div class="thinking-trades">' + trades.map(t =>
                `<div class="thinking-trade">
                    <span class="action">${t.action}</span> ${t.outcome} on "${(t.market_question || '?').substring(0, 50)}"
                    — $${(t.amount_usd || 0).toFixed(2)} @ ${((t.confidence || 0) * 100).toFixed(0)}% confidence
                    <div class="thesis">${escapeHtml(t.thesis || '')}</div>
                </div>`
            ).join('') + '</div>';
        }

        let metaHtml = '';
        if (watchlist || risk) {
            metaHtml = '<div class="thinking-meta">';
            if (watchlist) metaHtml += `<div class="watchlist">Watching: ${watchlist}</div>`;
            if (risk) metaHtml += `<div class="risk">Risk: ${risk}</div>`;
            metaHtml += '</div>';
        }

        return `<div class="thinking-entry">
            <div class="thinking-time">${time}</div>
            <div class="thinking-text">${thinking}</div>
            ${tradesHtml}
            ${metaHtml}
        </div>`;
    }).join('');
}

function renderTheses(theses) {
    const board = document.getElementById('thesis-board');
    if (!theses || theses.length === 0) {
        board.innerHTML = '<div style="color: var(--text-secondary); font-size: 13px; padding: 12px;">No active theses yet. The agent will create them when it spots patterns.</div>';
        return;
    }

    board.innerHTML = theses.map(t => {
        const conviction = t.conviction || 'medium';
        const history = t.history || [];
        const latestNote = history.length > 0 ? escapeHtml(history[history.length - 1].note || '') : '';
        const created = t.created ? t.created.substring(0, 10) : '?';
        const updates = history.length - 1;

        return `<div class="thesis-card">
            <div class="thesis-header">
                <span class="thesis-title">${escapeHtml(t.title || '')}</span>
                <span class="conviction-badge ${conviction}">${conviction}</span>
            </div>
            <div class="thesis-note">${latestNote.substring(0, 200)}</div>
            <div class="thesis-meta">Created ${created} | ${updates} update${updates !== 1 ? 's' : ''}</div>
        </div>`;
    }).join('');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initial load
fetchStatus();
fetchThinking();

// Auto-refresh every 30 seconds
setInterval(() => { fetchStatus(); fetchThinking(); }, 30000);
