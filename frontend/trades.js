/**
 * Trade Tracker - Frontend Application
 * Real-time position monitoring with auto-sell tracking
 */

const API_BASE = "/api";
let tradesData = [];
let selectedMarket = null;
let priceUpdateInterval = null;
let autoSellerStatus = null;

// ==================== INITIALIZATION ====================

document.addEventListener("DOMContentLoaded", () => {
  initializeApp();
});

async function initializeApp() {
  // Initial data load
  await Promise.all([refreshTrades(), fetchAutoSellerStatus()]);

  // Auto-refresh every 10 seconds
  priceUpdateInterval = setInterval(refreshTrades, 10000);

  // Enter key in search
  document.getElementById("market-search")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") searchMarkets();
  });

  // Side change updates token ID
  document.getElementById("trade-side")?.addEventListener("change", updateTokenId);
}

async function fetchAutoSellerStatus() {
  try {
    const response = await fetch(`${API_BASE}/trades/auto-seller/status`);
    autoSellerStatus = await response.json();
    updateAutoSellerIndicator();
  } catch (error) {
    console.error("Error fetching auto-seller status:", error);
    autoSellerStatus = { ready: false };
  }
}

function updateAutoSellerIndicator() {
  const indicator = document.getElementById("auto-seller-indicator");
  if (!indicator) return;

  if (autoSellerStatus?.ready) {
    indicator.innerHTML = `<span class="pulse green"></span> AUTO-SELL READY`;
    indicator.className = "auto-seller-indicator ready";
  } else {
    indicator.innerHTML = `<span class="pulse orange"></span> MANUAL MODE`;
    indicator.className = "auto-seller-indicator manual";
    indicator.title = "Add POLY_PRIVATE_KEY to .env to enable auto-sell";
  }
}

// ==================== DATA FETCHING ====================

async function refreshTrades() {
  try {
    const response = await fetch(`${API_BASE}/trades`);
    const data = await response.json();
    tradesData = data.trades || [];
    renderTrades();
    renderStats(data.stats);
    document.getElementById("last-update").textContent = formatTime(new Date().toISOString());
  } catch (error) {
    console.error("Error fetching trades:", error);
  }
}

// ==================== RENDERING ====================

function renderStats(stats) {
  if (!stats) return;

  document.getElementById("stat-total").textContent = stats.total_trades || 0;
  document.getElementById("stat-active").textContent = stats.active_trades || 0;
  document.getElementById("stat-targets").textContent = stats.targets_hit || 0;
  document.getElementById("stat-invested").textContent = formatCurrency(stats.total_invested_usd);

  const pnl = stats.total_pnl_usd || 0;
  const pnlEl = document.getElementById("stat-pnl");
  const pnlCard = document.getElementById("stat-pnl-card");

  pnlEl.textContent = `${pnl >= 0 ? '+' : ''}${formatCurrency(pnl)}`;
  pnlCard.classList.remove("positive", "negative");
  pnlCard.classList.add(pnl >= 0 ? "positive" : "negative");
}

function renderTrades() {
  const container = document.getElementById("trades-list");

  if (!tradesData || tradesData.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">🎯</div>
        <p>No trades being tracked</p>
        <p style="font-size: 0.8rem; margin-top: 8px; opacity: 0.7;">
          Click "Add Trade" to start tracking a position
        </p>
      </div>
    `;
    return;
  }

  container.innerHTML = tradesData.map(trade => createTradeCard(trade)).join("");
}

function createTradeCard(trade) {
  const progressPct = Math.min(Math.max(trade.progress_pct || 0, 0), 150);
  const pnlClass = trade.pnl_usd >= 0 ? "positive" : "negative";
  const statusClass = getStatusClass(trade.status);
  const statusIcon = getStatusIcon(trade.status);

  // Build Polymarket link
  const marketLink = trade.market_slug
    ? `https://polymarket.com/event/${trade.market_slug}`
    : "#";

  // Calculate marker positions for the progress bar
  const entryPct = 0;
  const targetPct = 100;
  const currentPct = progressPct;

  return `
    <div class="trade-card ${statusClass}" onclick="showTradeDetail('${trade.id}')">
      <div class="trade-header">
        <div class="trade-market">
          <span class="trade-question">${escapeHtml(trade.market_question || trade.market_slug)}</span>
          <a href="${marketLink}" target="_blank" class="polymarket-link-icon" onclick="event.stopPropagation()" title="View on Polymarket">↗</a>
        </div>
        <div class="trade-status">
          <span class="status-badge ${statusClass}">${statusIcon} ${trade.status.toUpperCase()}</span>
          ${trade.auto_sell ? '<span class="autosell-badge">AUTO</span>' : ''}
        </div>
      </div>

      <div class="trade-prices">
        <div class="price-item entry">
          <span class="price-label">Entry</span>
          <span class="price-value">${trade.entry_price.toFixed(1)}¢</span>
        </div>
        <div class="price-item current">
          <span class="price-label">Current</span>
          <span class="price-value ${pnlClass}">${trade.current_price.toFixed(1)}¢</span>
        </div>
        <div class="price-item target">
          <span class="price-label">Target</span>
          <span class="price-value">${trade.target_price.toFixed(1)}¢</span>
        </div>
      </div>

      <div class="trade-progress">
        <div class="progress-bar">
          <div class="progress-fill ${trade.target_hit ? 'target-hit' : ''}" style="width: ${Math.min(progressPct, 100)}%"></div>
          ${progressPct > 100 ? `<div class="progress-overflow" style="width: ${Math.min(progressPct - 100, 50)}%"></div>` : ''}
          <div class="progress-marker entry" style="left: 0%"></div>
          <div class="progress-marker current" style="left: ${Math.min(currentPct, 100)}%"></div>
          <div class="progress-marker target" style="left: 100%"></div>
        </div>
        <div class="progress-labels">
          <span class="progress-label">Entry</span>
          <span class="progress-label current">${progressPct.toFixed(0)}%</span>
          <span class="progress-label">Target</span>
        </div>
      </div>

      <div class="trade-details">
        <div class="detail-item">
          <span class="detail-label">Side</span>
          <span class="detail-value side-${trade.side.toLowerCase()}">${trade.side}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Shares</span>
          <span class="detail-value">${formatNumber(trade.shares)}</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Position</span>
          <span class="detail-value">${formatCurrency(trade.position_value_usd)}</span>
        </div>
        <div class="detail-item pnl">
          <span class="detail-label">P&L</span>
          <span class="detail-value ${pnlClass}">
            ${trade.pnl_usd >= 0 ? '+' : ''}${formatCurrency(trade.pnl_usd)}
            <span class="pnl-pct">(${trade.pnl_pct >= 0 ? '+' : ''}${trade.pnl_pct.toFixed(1)}%)</span>
          </span>
        </div>
      </div>

      ${trade.notes ? `<div class="trade-notes">${escapeHtml(trade.notes)}</div>` : ''}
    </div>
  `;
}

function getStatusClass(status) {
  switch (status) {
    case "monitoring": return "monitoring";
    case "target_hit": return "target-hit";
    case "sold": return "sold";
    case "stopped": return "stopped";
    default: return "";
  }
}

function getStatusIcon(status) {
  switch (status) {
    case "monitoring": return "🟢";
    case "target_hit": return "🎯";
    case "sold": return "✅";
    case "stopped": return "⏹️";
    default: return "⚪";
  }
}

// ==================== ADD TRADE MODAL ====================

function openAddTradeModal() {
  document.getElementById("add-trade-modal").classList.add("active");
  document.getElementById("market-search").focus();
}

function closeAddTradeModal() {
  document.getElementById("add-trade-modal").classList.remove("active");
  resetTradeForm();
}

async function searchMarkets() {
  const query = document.getElementById("market-search").value.trim();
  if (!query) return;

  const container = document.getElementById("market-search-results");
  container.innerHTML = '<div class="loading"><div class="spinner"></div><span>Searching...</span></div>';

  try {
    const response = await fetch(`${API_BASE}/trades/search/markets?q=${encodeURIComponent(query)}&limit=10`);
    const markets = await response.json();

    if (markets.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>No markets found</p></div>';
      return;
    }

    container.innerHTML = markets.map(m => `
      <div class="market-result-item" onclick="selectMarket(${escapeHtml(JSON.stringify(m))})">
        <div class="market-result-question">${escapeHtml(m.question)}</div>
        <div class="market-result-meta">
          <span>Outcomes: ${(m.outcomes || ['Yes', 'No']).join(' / ')}</span>
          ${m.outcome_prices?.length ? `<span>Prices: ${m.outcome_prices.map(p => (parseFloat(p) * 100).toFixed(1) + '¢').join(' / ')}</span>` : ''}
        </div>
      </div>
    `).join("");
  } catch (error) {
    container.innerHTML = `<div class="empty-state"><p>Search failed: ${error.message}</p></div>`;
  }
}

function selectMarket(market) {
  selectedMarket = market;

  // Show form
  document.getElementById("trade-form").style.display = "block";
  document.getElementById("market-search-results").innerHTML = "";

  // Populate form
  document.getElementById("selected-market").innerHTML = `
    <div class="selected-market-name">${escapeHtml(market.question)}</div>
  `;
  document.getElementById("trade-slug").value = market.slug || "";
  document.getElementById("trade-condition-id").value = market.condition_id || "";
  document.getElementById("trade-question").value = market.question || "";

  // Set initial token ID based on side
  updateTokenId();

  // Pre-fill current price if available
  if (market.outcome_prices?.length) {
    const side = document.getElementById("trade-side").value;
    const priceIdx = side === "YES" ? 0 : 1;
    const currentPrice = parseFloat(market.outcome_prices[priceIdx] || 0) * 100;
    document.getElementById("trade-entry").value = currentPrice.toFixed(1);
  }
}

function updateTokenId() {
  if (!selectedMarket) return;

  const side = document.getElementById("trade-side").value;
  const tokenIdx = side === "YES" ? 0 : 1;
  const tokenId = selectedMarket.clob_token_ids?.[tokenIdx] || "";
  document.getElementById("trade-token-id").value = tokenId;

  // Update entry price too
  if (selectedMarket.outcome_prices?.length) {
    const priceIdx = side === "YES" ? 0 : 1;
    const currentPrice = parseFloat(selectedMarket.outcome_prices[priceIdx] || 0) * 100;
    document.getElementById("trade-entry").value = currentPrice.toFixed(1);
  }
}

function resetTradeForm() {
  selectedMarket = null;
  document.getElementById("trade-form").style.display = "none";
  document.getElementById("market-search").value = "";
  document.getElementById("market-search-results").innerHTML = "";
  document.getElementById("trade-entry").value = "";
  document.getElementById("trade-target").value = "";
  document.getElementById("trade-shares").value = "";
  document.getElementById("trade-notes").value = "";
}

async function submitTrade() {
  const tokenId = document.getElementById("trade-token-id").value;
  const slug = document.getElementById("trade-slug").value;
  const conditionId = document.getElementById("trade-condition-id").value;
  const question = document.getElementById("trade-question").value;
  const side = document.getElementById("trade-side").value;
  const entry = parseFloat(document.getElementById("trade-entry").value);
  const target = parseFloat(document.getElementById("trade-target").value);
  const shares = parseFloat(document.getElementById("trade-shares").value);
  const autoSell = document.getElementById("trade-autosell").value === "true";
  const notes = document.getElementById("trade-notes").value;

  if (!tokenId || !entry || !target || !shares) {
    alert("Please fill in all required fields");
    return;
  }

  if (target <= entry) {
    alert("Target price must be greater than entry price");
    return;
  }

  try {
    const params = new URLSearchParams({
      market_slug: slug,
      token_id: tokenId,
      condition_id: conditionId,
      side: side,
      entry_price: entry,
      target_price: target,
      shares: shares,
      market_question: question,
      auto_sell: autoSell,
      notes: notes,
    });

    const response = await fetch(`${API_BASE}/trades?${params}`, { method: "POST" });

    if (!response.ok) {
      throw new Error("Failed to add trade");
    }

    closeAddTradeModal();
    await refreshTrades();
  } catch (error) {
    alert(`Error adding trade: ${error.message}`);
  }
}

// ==================== TRADE DETAIL MODAL ====================

function showTradeDetail(tradeId) {
  const trade = tradesData.find(t => t.id === tradeId);
  if (!trade) return;

  const pnlClass = trade.pnl_usd >= 0 ? "positive" : "negative";
  const marketLink = trade.market_slug
    ? `https://polymarket.com/event/${trade.market_slug}`
    : "#";

  document.getElementById("trade-detail-body").innerHTML = `
    <div class="modal-header">
      <div class="modal-title">
        ${escapeHtml(trade.market_question || trade.market_slug)}
        <a href="${marketLink}" target="_blank" class="polymarket-btn">View on Polymarket ↗</a>
      </div>
      <div class="status-badge ${getStatusClass(trade.status)}" style="margin-top: 8px;">
        ${getStatusIcon(trade.status)} ${trade.status.toUpperCase()}
      </div>
    </div>

    <div class="modal-section">
      <h3>Position Details</h3>
      <div class="detail-grid">
        <div class="detail-item-box">
          <div class="detail-label">Side</div>
          <div class="detail-value side-${trade.side.toLowerCase()}">${trade.side}</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">Shares</div>
          <div class="detail-value">${formatNumber(trade.shares)}</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">Entry Price</div>
          <div class="detail-value">${trade.entry_price.toFixed(2)}¢</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">Current Price</div>
          <div class="detail-value ${pnlClass}">${trade.current_price.toFixed(2)}¢</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">Target Price</div>
          <div class="detail-value highlight">${trade.target_price.toFixed(2)}¢</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">Progress</div>
          <div class="detail-value">${trade.progress_pct.toFixed(1)}%</div>
        </div>
      </div>
    </div>

    <div class="modal-section">
      <h3>P&L</h3>
      <div class="detail-grid">
        <div class="detail-item-box">
          <div class="detail-label">Entry Value</div>
          <div class="detail-value">${formatCurrency(trade.entry_value_usd)}</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">Current Value</div>
          <div class="detail-value ${pnlClass}">${formatCurrency(trade.position_value_usd)}</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">Unrealized P&L</div>
          <div class="detail-value ${pnlClass}">${trade.pnl_usd >= 0 ? '+' : ''}${formatCurrency(trade.pnl_usd)}</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">P&L %</div>
          <div class="detail-value ${pnlClass}">${trade.pnl_pct >= 0 ? '+' : ''}${trade.pnl_pct.toFixed(2)}%</div>
        </div>
      </div>
    </div>

    <div class="modal-section">
      <h3>Settings</h3>
      <div class="detail-grid">
        <div class="detail-item-box">
          <div class="detail-label">Auto-Sell</div>
          <div class="detail-value">${trade.auto_sell ? '✅ Enabled' : '❌ Disabled'}</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">Token ID</div>
          <div class="detail-value" style="font-size: 0.7rem; word-break: break-all;">${trade.token_id.substring(0, 20)}...</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">Created</div>
          <div class="detail-value">${formatTime(trade.created_at)}</div>
        </div>
        <div class="detail-item-box">
          <div class="detail-label">Updated</div>
          <div class="detail-value">${formatTime(trade.updated_at)}</div>
        </div>
      </div>
    </div>

    ${trade.notes ? `
      <div class="modal-section">
        <h3>Notes</h3>
        <div class="narrative-box">${escapeHtml(trade.notes)}</div>
      </div>
    ` : ''}

    <div class="modal-actions">
      ${trade.status === "monitoring" ? `
        <button class="action-btn danger" onclick="deleteTrade('${trade.id}')">Delete</button>
        ${autoSellerStatus?.ready
          ? `<button class="action-btn secondary" onclick="executeSell('${trade.id}')">Execute Sell</button>`
          : `<button class="action-btn secondary" onclick="markSoldManual('${trade.id}')">Mark Sold</button>`
        }
      ` : ''}
      ${trade.status === "target_hit" ? `
        ${autoSellerStatus?.ready
          ? `<button class="action-btn primary" onclick="executeSell('${trade.id}')">Execute Sell Now</button>`
          : `<button class="action-btn primary" onclick="markSoldManual('${trade.id}')">Mark Sold</button>`
        }
      ` : ''}
      <button class="action-btn" onclick="closeTradeDetailModal()">Close</button>
    </div>
  `;

  document.getElementById("trade-detail-modal").classList.add("active");
}

function closeTradeDetailModal() {
  document.getElementById("trade-detail-modal").classList.remove("active");
}

async function deleteTrade(tradeId) {
  if (!confirm("Are you sure you want to delete this trade?")) return;

  try {
    await fetch(`${API_BASE}/trades/${tradeId}`, { method: "DELETE" });
    closeTradeDetailModal();
    await refreshTrades();
  } catch (error) {
    alert(`Error deleting trade: ${error.message}`);
  }
}

async function markSoldManual(tradeId) {
  try {
    await fetch(`${API_BASE}/trades/${tradeId}/sell?manual=true`, { method: "POST" });
    closeTradeDetailModal();
    await refreshTrades();
  } catch (error) {
    alert(`Error marking trade as sold: ${error.message}`);
  }
}

async function executeSell(tradeId) {
  if (!confirm("Execute sell order on Polymarket?")) return;

  const trade = tradesData.find(t => t.id === tradeId);
  const btn = document.querySelector('.modal-actions .action-btn.primary, .modal-actions .action-btn.secondary');
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Executing...";
  }

  try {
    const response = await fetch(`${API_BASE}/trades/${tradeId}/sell`, { method: "POST" });
    const result = await response.json();

    if (!response.ok) {
      throw new Error(result.detail || "Sell failed");
    }

    if (result.execution === "auto") {
      alert(`Sell executed!\n\nShares: ${result.shares_sold}\nPrice: ${result.price?.toFixed(2)}¢\nOrder ID: ${result.order_id}`);
    } else {
      alert("Trade marked as sold (manual mode)");
    }

    closeTradeDetailModal();
    await refreshTrades();
  } catch (error) {
    alert(`Sell failed: ${error.message}`);
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Execute Sell";
    }
  }
}

// ==================== UTILITIES ====================

function formatCurrency(value) {
  if (value === null || value === undefined) return "--";
  if (Math.abs(value) >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
  if (Math.abs(value) >= 1000) return `$${(value / 1000).toFixed(1)}K`;
  return `$${value.toFixed(2)}`;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "--";
  return new Intl.NumberFormat().format(Math.round(value));
}

function formatTime(isoString) {
  if (!isoString) return "--";
  const date = new Date(isoString);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function escapeHtml(text) {
  if (!text) return "";
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Close modals on outside click
document.getElementById("add-trade-modal")?.addEventListener("click", (e) => {
  if (e.target.id === "add-trade-modal") closeAddTradeModal();
});
document.getElementById("trade-detail-modal")?.addEventListener("click", (e) => {
  if (e.target.id === "trade-detail-modal") closeTradeDetailModal();
});

// Close modals on Escape key
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeAddTradeModal();
    closeTradeDetailModal();
  }
});
