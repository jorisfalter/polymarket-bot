/**
 * Copy Trading Dashboard - Smart Money & Paper Trading
 */

const API_BASE = "/api";
let currentView = "smartmoney";

// ==================== INITIALIZATION ====================

document.addEventListener("DOMContentLoaded", () => {
  initializeApp();
});

async function initializeApp() {
  // Load initial view
  fetchLeaderboard();
  loadWatchlist();
}

// ==================== VIEW SWITCHING ====================

function switchView(view) {
  currentView = view;

  // Update buttons
  document.querySelectorAll(".view-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });

  // Toggle views
  const smartmoneyView = document.getElementById("smartmoney-view");
  const paperView = document.getElementById("paper-view");

  if (view === "smartmoney") {
    smartmoneyView.style.display = "flex";
    paperView.style.display = "none";
    fetchLeaderboard();
    loadWatchlist();
  } else {
    smartmoneyView.style.display = "none";
    paperView.style.display = "flex";
    fetchPaperStats();
    fetchPaperPositions();
  }
}

// ==================== LEADERBOARD ====================

async function fetchLeaderboard() {
  const container = document.getElementById("leaderboard-table");
  const timePeriod = document.getElementById("lb-time-period")?.value || "all";
  const orderBy = document.getElementById("lb-order-by")?.value || "pnl";

  try {
    const params = new URLSearchParams({ time_period: timePeriod, order_by: orderBy, limit: "50" });
    const response = await fetch(`${API_BASE}/leaderboard?${params}`);
    const traders = await response.json();
    renderLeaderboard(traders);
  } catch (error) {
    console.error("Error fetching leaderboard:", error);
    container.innerHTML = '<div class="empty-state"><p>Failed to load leaderboard</p></div>';
  }
}

function renderLeaderboard(traders) {
  const container = document.getElementById("leaderboard-table");

  if (!traders || traders.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">💰</div>
        <p>No leaderboard data available</p>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="lb-header-row">
      <div class="lb-rank">#</div>
      <div class="lb-trader">Trader</div>
      <div class="lb-pnl">PnL</div>
      <div class="lb-volume">Volume</div>
      <div class="lb-markets">Markets</div>
      <div class="lb-winrate">Win Rate</div>
      <div class="lb-action">Watch</div>
    </div>
    ${traders.map((t, i) => `
      <div class="lb-row ${t.is_watched ? 'watched' : ''}">
        <div class="lb-rank">${t.rank || i + 1}</div>
        <div class="lb-trader">
          <a href="https://polymarket.com/profile/${t.address}" target="_blank" class="trader-link">${t.display_name || (t.address ? t.address.substring(0, 12) + '...' : 'Unknown')}</a>
        </div>
        <div class="lb-pnl ${t.pnl >= 0 ? 'positive' : 'negative'}">${t.pnl >= 0 ? '+' : ''}${formatCurrency(t.pnl)}</div>
        <div class="lb-volume">${formatCurrency(t.volume)}</div>
        <div class="lb-markets">${t.markets_traded}</div>
        <div class="lb-winrate">${t.win_rate ? (t.win_rate * 100).toFixed(0) + '%' : 'N/A'}</div>
        <div class="lb-action">
          <button class="watch-btn ${t.is_watched ? 'watching' : ''}" onclick="toggleWatch('${t.address}', this)">
            ${t.is_watched ? '👁 Watching' : '+ Watch'}
          </button>
        </div>
      </div>
    `).join('')}
  `;
}

async function toggleWatch(address, btn) {
  const isWatching = btn.classList.contains("watching");

  try {
    if (isWatching) {
      await fetch(`${API_BASE}/leaderboard/watch/${address}`, { method: "DELETE" });
      btn.classList.remove("watching");
      btn.textContent = "+ Watch";
    } else {
      await fetch(`${API_BASE}/leaderboard/watch/${address}`, { method: "POST" });
      btn.classList.add("watching");
      btn.textContent = "👁 Watching";
    }
    loadWatchlist();
  } catch (error) {
    console.error("Error toggling watch:", error);
  }
}

async function loadWatchlist() {
  try {
    const response = await fetch(`${API_BASE}/leaderboard/watching`);
    const data = await response.json();
    const wallets = data.wallets || [];

    const section = document.getElementById("watchlist-section");
    const container = document.getElementById("watchlist");

    if (wallets.length === 0) {
      section.style.display = "none";
      return;
    }

    section.style.display = "block";
    container.innerHTML = wallets
      .map(
        (w) => `
        <div class="watchlist-item">
          <a href="https://polymarket.com/profile/${w}" target="_blank" class="trader-link">👛 ${w.substring(0, 16)}...</a>
          <button class="unwatch-btn" onclick="unwatchTrader('${w}')">Remove</button>
        </div>
      `
      )
      .join("");
  } catch (error) {
    console.error("Error loading watchlist:", error);
  }
}

async function unwatchTrader(address) {
  try {
    await fetch(`${API_BASE}/leaderboard/watch/${address}`, { method: "DELETE" });
    loadWatchlist();
    if (currentView === "smartmoney") fetchLeaderboard();
  } catch (error) {
    console.error("Error unwatching trader:", error);
  }
}

// ==================== PAPER TRADING ====================

async function fetchPaperStats() {
  try {
    const response = await fetch(`${API_BASE}/paper-trader/stats`);
    const stats = await response.json();

    document.getElementById("paper-total-positions").textContent = stats.total_trades || 0;
    document.getElementById("paper-invested").textContent = `$${(stats.total_trades * 100).toLocaleString()}`;
    document.getElementById("paper-won").textContent = stats.won_trades || 0;
    document.getElementById("paper-lost").textContent = stats.lost_trades || 0;
    document.getElementById("paper-winrate").textContent = `${stats.win_rate?.toFixed(0) || 0}%`;

    const totalPnl = (stats.realized_pnl || 0) + (stats.unrealized_pnl || 0);
    const pnlEl = document.getElementById("paper-pnl");
    pnlEl.textContent = `${totalPnl >= 0 ? '+' : ''}$${totalPnl.toFixed(2)}`;
    pnlEl.classList.toggle("positive", totalPnl >= 0);
    pnlEl.classList.toggle("negative", totalPnl < 0);

    renderPaperHistory(stats.recent_trades || []);
  } catch (error) {
    console.error("Error fetching paper stats:", error);
  }
}

async function fetchPaperPositions() {
  const container = document.getElementById("paper-positions");

  try {
    const response = await fetch(`${API_BASE}/paper-trader/positions`);
    const data = await response.json();
    const positions = data.positions || [];

    if (positions.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">📄</div>
          <p>No open positions</p>
          <p class="empty-state-hint">Add traders to your watchlist in Smart Money tab to start copy-trading</p>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="paper-positions-header">
        <div class="pp-market">Market</div>
        <div class="pp-outcome">Position</div>
        <div class="pp-entry">Entry</div>
        <div class="pp-current">Current</div>
        <div class="pp-pnl">Unrealized P&L</div>
        <div class="pp-copied">Copied From</div>
      </div>
      ${positions.map(p => {
        const pnl = p.unrealized_pnl || 0;
        const pnlPct = p.entry_price > 0 ? ((p.current_price - p.entry_price) / p.entry_price * 100) : 0;
        return `
          <div class="paper-position-row">
            <div class="pp-market">
              <a href="https://polymarket.com/event/${p.market_slug}" target="_blank" class="market-link">
                ${p.market?.substring(0, 50) || 'Unknown'}...
              </a>
            </div>
            <div class="pp-outcome">${p.outcome}</div>
            <div class="pp-entry">${(p.entry_price * 100).toFixed(1)}¢</div>
            <div class="pp-current">${(p.current_price * 100).toFixed(1)}¢</div>
            <div class="pp-pnl ${pnl >= 0 ? 'positive' : 'negative'}">
              ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}
              <span class="pnl-pct">(${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(1)}%)</span>
            </div>
            <div class="pp-copied">
              <a href="https://polymarket.com/profile/${p.copied_from}" target="_blank" class="trader-link">
                ${p.copied_from_name?.substring(0, 12) || p.copied_from?.substring(0, 12)}...
              </a>
            </div>
          </div>
        `;
      }).join('')}
    `;
  } catch (error) {
    console.error("Error fetching paper positions:", error);
    container.innerHTML = '<div class="empty-state"><p>Failed to load positions</p></div>';
  }
}

function renderPaperHistory(trades) {
  const container = document.getElementById("paper-history");

  if (!trades || trades.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No trade history yet</p>
      </div>
    `;
    return;
  }

  container.innerHTML = trades.map(t => {
    const statusIcon = t.status === 'open' ? '🟡' : (t.status === 'won' ? '✅' : '❌');
    const pnlClass = t.pnl_usd >= 0 ? 'positive' : 'negative';

    return `
      <div class="paper-history-row ${t.status}">
        <div class="ph-status">${statusIcon}</div>
        <div class="ph-market">${t.market?.substring(0, 45) || 'Unknown'}...</div>
        <div class="ph-outcome">${t.outcome}</div>
        <div class="ph-entry">${(t.entry * 100).toFixed(1)}¢</div>
        <div class="ph-pnl ${t.status !== 'open' ? pnlClass : ''}">
          ${t.status === 'open' ? '--' : `${t.pnl_usd >= 0 ? '+' : ''}$${t.pnl_usd.toFixed(2)}`}
        </div>
        <div class="ph-copied">${t.copied_from?.substring(0, 10)}...</div>
      </div>
    `;
  }).join('');
}

async function updatePaperPrices() {
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '⏳ Updating...';

  try {
    await fetch(`${API_BASE}/paper-trader/update-prices`, { method: "POST" });
    await fetchPaperStats();
    await fetchPaperPositions();
  } catch (error) {
    console.error("Error updating paper prices:", error);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔄 Update Prices';
  }
}

async function scanPaperTrades() {
  const btn = event.target;
  btn.disabled = true;
  btn.textContent = '⏳ Scanning...';

  try {
    const response = await fetch(`${API_BASE}/paper-trader/scan`, { method: "POST" });
    const result = await response.json();

    if (result.new_trades > 0) {
      alert(`Found ${result.new_trades} new trades to copy!`);
    }

    await fetchPaperStats();
    await fetchPaperPositions();
  } catch (error) {
    console.error("Error scanning paper trades:", error);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔍 Scan for Trades';
  }
}

// ==================== UTILITIES ====================

function formatCurrency(value) {
  if (!value && value !== 0) return "--";
  if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
}
