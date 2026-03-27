/**
 * Strategy Engine Frontend
 * Auto-refreshes status and trade journal every 15 seconds
 */

async function fetchStatus() {
    try {
        const res = await fetch('/api/strategy/status');
        const data = await res.json();
        renderStatus(data);
    } catch (e) {
        console.error('Failed to fetch status:', e);
    }
}

async function fetchJournal() {
    try {
        const res = await fetch('/api/strategy/journal?limit=50');
        const entries = await res.json();
        renderJournal(entries);
    } catch (e) {
        console.error('Failed to fetch journal:', e);
    }
}

function renderStatus(data) {
    // Balance
    const balance = data.current_state?.usdc_balance;
    document.getElementById('balance').textContent = balance != null ? `$${balance.toFixed(2)}` : '--';

    // Performance
    const perf = data.performance || {};
    const pnl = perf.total_pnl || 0;
    const pnlEl = document.getElementById('perf-pnl');
    pnlEl.textContent = `$${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}`;
    pnlEl.className = `value ${pnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`;
    document.getElementById('perf-trades').textContent = perf.trades || 0;
    document.getElementById('perf-winrate').textContent = perf.trades ? `${(perf.win_rate * 100).toFixed(0)}%` : '--';

    // Exposure
    const exposure = data.current_state?.total_exposure || 0;
    const maxExposure = data.risk_limits?.max_total_exposure || 100;
    document.getElementById('perf-exposure').textContent = `$${exposure.toFixed(0)}`;

    // Risk bars
    const exposurePct = Math.min((exposure / maxExposure) * 100, 100);
    const exposureFill = document.getElementById('exposure-fill');
    exposureFill.style.width = `${exposurePct}%`;
    exposureFill.className = `risk-fill ${exposurePct > 80 ? 'red' : exposurePct > 50 ? 'yellow' : 'green'}`;
    document.getElementById('exposure-text').textContent = `$${exposure.toFixed(0)} / $${maxExposure}`;

    const positions = data.current_state?.open_positions || 0;
    const maxPositions = data.risk_limits?.max_positions || 5;
    const posPct = (positions / maxPositions) * 100;
    const posFill = document.getElementById('positions-fill');
    posFill.style.width = `${posPct}%`;
    posFill.className = `risk-fill ${posPct > 80 ? 'red' : posPct > 50 ? 'yellow' : 'green'}`;
    document.getElementById('positions-text').textContent = `${positions} / ${maxPositions}`;

    // Strategy statuses
    const strategies = data.strategies || {};
    setStrategyStatus('insider', strategies.insider_signal);
    setStrategyStatus('arb', strategies.resolution_arb);

    // Insider queue
    document.getElementById('insider-queue').textContent = data.insider_queue_size || 0;

    // Last arb scan
    if (data.last_arb_scan) {
        const ago = timeSince(new Date(data.last_arb_scan + 'Z'));
        document.getElementById('arb-last-scan').textContent = ago;
        document.getElementById('last-arb-scan').textContent = `Last arb scan: ${ago}`;
    }
}

function setStrategyStatus(id, enabled) {
    const el = document.getElementById(`${id}-status`);
    if (enabled) {
        el.textContent = 'ACTIVE';
        el.className = 'status active';
    } else {
        el.textContent = 'OFF';
        el.className = 'status inactive';
    }
}

function renderJournal(entries) {
    const tbody = document.getElementById('journal-body');
    if (!entries || entries.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color: var(--text-secondary); padding: 40px;">No trades yet. The strategy engine is running...</td></tr>';
        return;
    }

    tbody.innerHTML = entries.map(e => {
        const time = new Date(e.timestamp + 'Z').toLocaleString();
        const stratClass = e.strategy === 'INSIDER-SIGNAL' ? 'insider' : 'arb';
        const stratLabel = e.strategy === 'INSIDER-SIGNAL' ? 'INSIDER' : 'ARB';
        const actionClass = e.action === 'ENTER' ? 'enter' : 'exit';
        const market = (e.market_question || '').substring(0, 50);
        const price = e.price ? `${(e.price * 100).toFixed(1)}c` : '--';
        const amount = e.amount_usd ? `$${e.amount_usd.toFixed(2)}` : '--';
        let pnl = '';
        if (e.action === 'EXIT' && e.pnl_usd != null) {
            const cls = e.pnl_usd >= 0 ? 'pnl-positive' : 'pnl-negative';
            pnl = `<span class="${cls}">$${e.pnl_usd >= 0 ? '+' : ''}${e.pnl_usd.toFixed(2)}</span>`;
        }
        const reason = (e.reason || e.exit_reason || '').substring(0, 40);

        return `<tr>
            <td style="white-space:nowrap; font-size:12px;">${time}</td>
            <td><span class="tag ${stratClass}">${stratLabel}</span></td>
            <td><span class="tag ${actionClass}">${e.action}</span></td>
            <td title="${e.market_question || ''}">${market}</td>
            <td style="font-family:'JetBrains Mono',monospace;">${price}</td>
            <td style="font-family:'JetBrains Mono',monospace;">${amount}</td>
            <td>${pnl}</td>
            <td style="font-size:11px; color: var(--text-secondary);" title="${e.reason || ''}">${reason}</td>
        </tr>`;
    }).join('');
}

function timeSince(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

// Initial load
fetchStatus();
fetchJournal();

// Auto-refresh every 15 seconds
setInterval(() => { fetchStatus(); fetchJournal(); }, 15000);
