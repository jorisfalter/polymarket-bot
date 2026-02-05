/**
 * Polymarket Insider Detector - Frontend Application
 * Real-time monitoring dashboard for suspicious trading activity
 */

const API_BASE = "/api";
let currentFilter = "all";
let currentView = "alerts";
let alertsData = [];
let activityData = [];
let signalStats = {};

// ==================== INITIALIZATION ====================

document.addEventListener("DOMContentLoaded", () => {
  initializeApp();
});

async function initializeApp() {
  // Set up filter tabs
  document.querySelectorAll(".filter-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document
        .querySelectorAll(".filter-tab")
        .forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      currentFilter = tab.dataset.severity;
      renderAlerts();
    });
  });

  // Initial data load
  await refreshData();

  // Auto-refresh every 30 seconds
  setInterval(refreshData, 30000);
}

// ==================== DATA FETCHING ====================

async function refreshData() {
  try {
    await Promise.all([
      fetchStats(),
      fetchAlerts(),
      fetchSuspiciousMarkets(),
      fetchWalletClusters(),
      fetchActivity(),
      fetchSignalStats(),
    ]);
  } catch (error) {
    console.error("Error refreshing data:", error);
  }
}

// ==================== VIEW SWITCHING ====================

function switchView(view) {
  currentView = view;

  // Update buttons
  document.querySelectorAll(".view-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === view);
  });

  // All view IDs
  const views = ["alerts-view", "activity-view", "signals-view", "backtest-view", "smartmoney-view"];
  const viewMap = {
    alerts: "alerts-view",
    activity: "activity-view",
    signals: "signals-view",
    backtest: "backtest-view",
    smartmoney: "smartmoney-view",
  };

  views.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = id === viewMap[view] ? "flex" : "none";
  });

  // Refresh data for the view
  if (view === "activity") renderActivity();
  if (view === "signals") renderSignalStats();
  if (view === "backtest") loadBacktestCases();
  if (view === "smartmoney") { fetchLeaderboard(); loadWatchlist(); }
}

async function fetchStats() {
  try {
    const response = await fetch(`${API_BASE}/stats`);
    const stats = await response.json();

    document.getElementById("total-alerts").textContent =
      stats.total_alerts_24h || 0;
    document.getElementById("critical-alerts").textContent =
      stats.critical_alerts_24h || 0;
    document.getElementById("suspicious-volume").textContent = formatCurrency(
      stats.total_suspicious_volume_24h
    );
    document.getElementById("avg-score").textContent =
      stats.avg_suspicion_score || 0;
    document.getElementById("clusters-detected").textContent =
      stats.wallet_clusters_detected || 0;
    document.getElementById("last-scan").textContent = formatTime(
      stats.last_scan
    );
  } catch (error) {
    console.error("Error fetching stats:", error);
  }
}

async function fetchAlerts() {
  try {
    const response = await fetch(`${API_BASE}/alerts?limit=100`);
    alertsData = await response.json();
    renderAlerts();
  } catch (error) {
    console.error("Error fetching alerts:", error);
    document.getElementById("alert-list").innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📡</div>
                <p>Connecting to detection engine...</p>
            </div>
        `;
  }
}

async function fetchSuspiciousMarkets() {
  try {
    const response = await fetch(`${API_BASE}/markets/suspicious?limit=8`);
    const markets = await response.json();
    renderMarkets(markets);
  } catch (error) {
    console.error("Error fetching markets:", error);
  }
}

async function fetchWalletClusters() {
  try {
    const response = await fetch(`${API_BASE}/clusters`);
    const clusters = await response.json();
    renderClusters(clusters);
  } catch (error) {
    console.error("Error fetching clusters:", error);
  }
}

async function fetchActivity() {
  try {
    const response = await fetch(`${API_BASE}/activity?limit=200`);
    activityData = await response.json();
    if (currentView === "activity") renderActivity();
  } catch (error) {
    console.error("Error fetching activity:", error);
  }
}

async function fetchSignalStats() {
  try {
    const response = await fetch(`${API_BASE}/activity/stats`);
    signalStats = await response.json();
    if (currentView === "signals") renderSignalStats();
  } catch (error) {
    console.error("Error fetching signal stats:", error);
  }
}

// ==================== RENDERING ====================

function renderAlerts() {
  const container = document.getElementById("alert-list");

  // Filter alerts
  let filtered = alertsData;
  if (currentFilter !== "all") {
    filtered = alertsData.filter((a) => a.severity === currentFilter);
  }

  if (filtered.length === 0) {
    container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🔍</div>
                <p>No ${
                  currentFilter === "all" ? "" : currentFilter
                } alerts detected yet</p>
                <p style="font-size: 0.8rem; margin-top: 8px; opacity: 0.7;">
                    The scanner is monitoring for suspicious activity...
                </p>
            </div>
        `;
    return;
  }

  container.innerHTML = filtered
    .map((alert) => createAlertCard(alert))
    .join("");
}

function createAlertCard(alert) {
  const trade = alert.trade;
  const wallet = alert.wallet;
  const flags = alert.flags.slice(0, 3); // Show first 3 flags

  // Build Polymarket link - use slug if available, otherwise search URL
  const marketLink = trade.market_slug
    ? `https://polymarket.com/event/${trade.market_slug}`
    : `https://polymarket.com/markets?_q=${encodeURIComponent((trade.market_question || '').slice(0, 50))}`;

  return `
        <div class="alert-item ${alert.severity}" onclick="showAlertDetail('${
    alert.id
  }')">
            <div class="alert-severity">
                <span class="severity-badge ${alert.severity}">${
    alert.severity
  }</span>
                <span class="suspicion-score" style="color: ${getSeverityColor(
                  alert.severity
                )}">${Math.round(alert.suspicion_score)}</span>
            </div>
            <div class="alert-content">
                <div class="alert-header">
                    <div class="alert-market">
                        ${truncate(trade.market_question, 80)}
                        <a href="${marketLink}" target="_blank" class="polymarket-link-icon" onclick="event.stopPropagation()" title="Open on Polymarket">↗</a>
                    </div>
                    <div class="alert-time">${formatTimeAgo(
                      alert.created_at
                    )}</div>
                </div>
                <div class="alert-flags">
                    ${flags
                      .map((flag) => `<span class="flag-tag">${flag}</span>`)
                      .join("")}
                </div>
                <div class="alert-trade-info">
                    <div class="trade-detail">
                        <span class="label">Side:</span>
                        <span class="value ${trade.side.toLowerCase()}">${
    trade.side
  }</span>
                    </div>
                    <div class="trade-detail">
                        <span class="label">Size:</span>
                        <span class="value">${formatCurrency(
                          trade.notional_usd
                        )}</span>
                    </div>
                    <div class="trade-detail">
                        <span class="label">Price:</span>
                        <span class="value">${trade.price.toFixed(1)}¢</span>
                    </div>
                    <div class="trade-detail">
                        <span class="label">Potential:</span>
                        <span class="value">${
                          trade.potential_return_pct
                            ? `+${trade.potential_return_pct.toFixed(0)}%`
                            : "--"
                        }</span>
                    </div>
                    <div class="trade-detail">
                        <span class="label">Markets:</span>
                        <span class="value">${wallet.unique_markets}</span>
                    </div>
                </div>
            </div>
        </div>
    `;
}

function renderMarkets(markets) {
  const container = document.getElementById("market-list");

  if (markets.length === 0) {
    container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📊</div>
                <p>No suspicious markets yet</p>
            </div>
        `;
    return;
  }

  container.innerHTML = markets
    .map(
      (market) => `
        <div class="market-item">
            <div class="market-name">${truncate(market.question, 60)}</div>
            <div class="market-stats">
                <span class="market-stat">
                    <span class="value">${market.alert_count}</span> alerts
                </span>
                <span class="market-stat">
                    <span class="value">${formatCurrency(
                      market.total_suspicious_volume
                    )}</span>
                </span>
                <span class="market-stat severity-badge ${market.max_severity}">
                    ${market.max_severity}
                </span>
            </div>
        </div>
    `
    )
    .join("");
}

function renderClusters(clusters) {
  const container = document.getElementById("cluster-list");

  if (clusters.length === 0) {
    container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🕸️</div>
                <p>No coordinated activity detected</p>
            </div>
        `;
    return;
  }

  container.innerHTML = clusters
    .map(
      (cluster) => `
        <div class="cluster-item">
            <div class="cluster-header">
                <span class="cluster-wallets">🕸️ ${
                  cluster.wallet_count
                } wallets</span>
                <span class="cluster-correlation">${(
                  cluster.correlation_score * 100
                ).toFixed(0)}% correlated</span>
            </div>
            <div class="cluster-stats">
                Volume: ${formatCurrency(
                  cluster.total_volume
                )} • Detected: ${formatTimeAgo(cluster.first_detected)}
            </div>
        </div>
    `
    )
    .join("");
}

function renderActivity() {
  const container = document.getElementById("activity-list");

  if (!activityData || activityData.length === 0) {
    container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📊</div>
                <p>No activity scanned yet</p>
                <p style="font-size: 0.8rem; margin-top: 8px; opacity: 0.7;">
                    Click "Force Scan" to analyze trades
                </p>
            </div>
        `;
    return;
  }

  container.innerHTML = activityData
    .map((entry) => {
      const scoreClass =
        entry.total_score >= 80
          ? "critical"
          : entry.total_score >= 60
          ? "high"
          : entry.total_score >= 40
          ? "medium"
          : "low";

      // Build Polymarket link - use slug if available, otherwise search URL
      const marketLink = entry.market_slug
        ? `https://polymarket.com/event/${entry.market_slug}`
        : `https://polymarket.com/markets?_q=${encodeURIComponent((entry.market || '').slice(0, 50))}`;

      return `
            <div class="activity-item ${entry.is_alert ? "is-alert" : ""}">
                <div class="activity-main">
                    <div class="activity-market">
                        ${
                          marketLink
                            ? `<a href="${marketLink}" target="_blank" class="market-link" title="View on Polymarket">${
                                entry.market || "Unknown Market"
                              }</a>
                               <a href="${marketLink}" target="_blank" class="polymarket-link-icon" title="Open on Polymarket">↗</a>`
                            : entry.market || "Unknown Market"
                        }
                    </div>
                    <div class="activity-meta">
                        <span>${entry.side} ${formatCurrency(
        entry.notional_usd
      )}</span>
                        <span>@ ${entry.price?.toFixed(1) || 0}¢</span>
                        <span>
                            <a href="https://polymarket.com/profile/${
                              entry.trader_full || entry.trader
                            }" 
                               target="_blank" 
                               class="trader-link"
                               title="View trader profile on Polymarket">
                                👛 ${entry.trader}
                            </a>
                        </span>
                        <span>📈 ${entry.wallet_trades} trades / ${
        entry.wallet_markets
      } markets</span>
                    </div>
                    <div class="activity-signals">
                        ${(entry.signals || [])
                          .map(
                            (s) => `
                            <span class="signal-chip ${
                              s.score > 0 ? "active" : ""
                            }" data-tooltip="${getSignalTooltip(s)}">
                                ${s.signal.split(" ")[0]} 
                                <span class="score">${
                                  s.score > 0 ? "+" + s.score : "0"
                                }</span>
                            </span>
                        `
                          )
                          .join("")}
                    </div>
                </div>
                <div class="activity-score">
                    <span class="score-value ${scoreClass}">${
        entry.total_score
      }</span>
                    <span class="score-label">${
                      entry.is_alert ? "ALERT" : "score"
                    }</span>
                </div>
            </div>
        `;
    })
    .join("");
}

function getSignalTooltip(signal) {
  const descriptions = {
    "🐣 Fresh Wallet": "Low-activity wallet making large bets",
    "💰 Position Size": "Unusually large bet size",
    "🎯 Market Diversity": "Focused betting on few markets",
    "📈 Volume Spike": "Unusual volume spike detected",
    "🏆 Win Rate": "Suspiciously high win rate",
    "⏰ Timing": "Trade close to market resolution",
    "🎲 Extreme Odds": "Betting on low probability outcome",
  };

  const desc = descriptions[signal.signal] || signal.signal;
  const details = signal.details ? ` | ${signal.details}` : "";
  const threshold = signal.threshold ? ` | Threshold: ${signal.threshold}` : "";

  // Escape HTML entities for safe attribute usage
  return escapeHtml(`${desc}${details}${threshold}`);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function renderSignalStats() {
  const container = document.getElementById("signal-stats");

  if (!signalStats || signalStats.total_scanned === 0) {
    container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🔬</div>
                <p>No data for analysis yet</p>
                <p style="font-size: 0.8rem; margin-top: 8px; opacity: 0.7;">
                    Scan some trades first to see signal statistics
                </p>
            </div>
        `;
    return;
  }

  const breakdown = signalStats.signal_breakdown || [];
  const maxTriggers = Math.max(...breakdown.map((s) => s.times_triggered), 1);

  container.innerHTML = `
        <div class="stats-overview">
            <div class="overview-stat">
                <div class="value">${signalStats.total_scanned}</div>
                <div class="label">Trades Scanned</div>
            </div>
            <div class="overview-stat">
                <div class="value">${signalStats.alerts_generated}</div>
                <div class="label">Alerts Generated</div>
            </div>
            <div class="overview-stat">
                <div class="value">${signalStats.alert_rate}</div>
                <div class="label">Alert Rate</div>
            </div>
            <div class="overview-stat">
                <div class="value">${signalStats.avg_score}</div>
                <div class="label">Avg Score</div>
            </div>
        </div>
        
        <h3 style="margin-bottom: 16px; color: var(--text-secondary);">Signal Breakdown</h3>
        <div class="signal-breakdown">
            <div class="signal-row header">
                <div>Signal</div>
                <div>Trigger Frequency</div>
                <div>Rate</div>
                <div>Avg Score</div>
            </div>
            ${breakdown
              .map(
                (signal) => `
                <div class="signal-row">
                    <div class="signal-name">${signal.signal}</div>
                    <div class="signal-bar-container">
                        <div class="signal-bar" style="width: ${
                          (signal.times_triggered / maxTriggers) * 100
                        }%"></div>
                    </div>
                    <div class="signal-rate">${signal.trigger_rate}</div>
                    <div class="signal-avg">+${
                      signal.avg_score_when_triggered
                    }</div>
                </div>
            `
              )
              .join("")}
        </div>
        
        <h3 style="margin: 24px 0 16px; color: var(--text-secondary);">Recent Markets Scanned</h3>
        <div style="display: flex; flex-wrap: wrap; gap: 8px;">
            ${(signalStats.recent_markets || [])
              .map(
                (m) => `
                <span class="flag-tag">${m}</span>
            `
              )
              .join("")}
        </div>
    `;
}

// ==================== MODAL ====================

function showAlertDetail(alertId) {
  const alert = alertsData.find((a) => a.id === alertId);
  if (!alert) return;

  const trade = alert.trade;
  const wallet = alert.wallet;

  // Build Polymarket link - use slug if available, otherwise search URL
  const marketLink = trade.market_slug
    ? `https://polymarket.com/event/${trade.market_slug}`
    : `https://polymarket.com/markets?_q=${encodeURIComponent((trade.market_question || '').slice(0, 50))}`;

  document.getElementById("modal-body").innerHTML = `
        <div class="modal-header">
            <div class="modal-title">
                ${trade.market_question}
                <a href="${marketLink}" target="_blank" class="polymarket-btn" title="View on Polymarket">View on Polymarket ↗</a>
            </div>
            <div class="severity-badge ${
              alert.severity
            }" style="display: inline-block; margin-top: 8px;">
                ${alert.severity.toUpperCase()} SEVERITY
            </div>
        </div>
        
        <div class="modal-section">
            <h3>📝 Analysis</h3>
            <div class="narrative-box">${alert.narrative}</div>
        </div>
        
        <div class="modal-section">
            <h3>💰 Trade Details</h3>
            <div class="detail-grid">
                <div class="detail-item">
                    <div class="detail-label">Side</div>
                    <div class="detail-value ${
                      trade.side === "BUY" ? "highlight" : "danger"
                    }">${trade.side}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Notional</div>
                    <div class="detail-value highlight">${formatCurrency(
                      trade.notional_usd
                    )}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Shares</div>
                    <div class="detail-value">${formatNumber(
                      trade.shares
                    )}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Price</div>
                    <div class="detail-value">${trade.price.toFixed(1)}¢</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Potential Return</div>
                    <div class="detail-value highlight">${
                      trade.potential_return_pct
                        ? `+${trade.potential_return_pct.toFixed(0)}%`
                        : "--"
                    }</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Timestamp</div>
                    <div class="detail-value">${formatTime(
                      trade.timestamp
                    )}</div>
                </div>
            </div>
        </div>
        
        <div class="modal-section">
            <h3>👛 Wallet Profile</h3>
            <div class="detail-grid">
                <div class="detail-item">
                    <div class="detail-label">Address</div>
                    <div class="detail-value" style="font-size: 0.75rem;">
                        <a href="https://polymarket.com/@${
                          wallet.address
                        }" target="_blank" style="color: var(--accent-secondary);">
                            ${truncate(wallet.address, 20)}
                        </a>
                    </div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Total Trades</div>
                    <div class="detail-value ${
                      wallet.total_trades < 10 ? "danger" : ""
                    }">${wallet.total_trades}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Unique Markets</div>
                    <div class="detail-value ${
                      wallet.unique_markets < 5 ? "danger" : ""
                    }">${wallet.unique_markets}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Lifetime Volume</div>
                    <div class="detail-value">${formatCurrency(
                      wallet.total_volume_usd
                    )}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Win Rate</div>
                    <div class="detail-value ${
                      wallet.win_rate > 0.8 ? "highlight" : ""
                    }">
                        ${
                          wallet.win_rate
                            ? `${(wallet.win_rate * 100).toFixed(0)}%`
                            : "N/A"
                        }
                    </div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Wallet Score</div>
                    <div class="detail-value danger">${
                      wallet.suspicion_score
                    }</div>
                </div>
            </div>
        </div>
        
        <div class="modal-section">
            <h3>🚩 Flags</h3>
            <div class="alert-flags">
                ${alert.flags
                  .map((flag) => `<span class="flag-tag">${flag}</span>`)
                  .join("")}
            </div>
        </div>
        
        <div class="modal-section">
            <h3>📊 Insider Probability</h3>
            <div style="display: flex; align-items: center; gap: 16px;">
                <div style="flex: 1; height: 8px; background: var(--bg-tertiary); border-radius: 4px; overflow: hidden;">
                    <div style="width: ${
                      alert.insider_probability * 100
                    }%; height: 100%; background: linear-gradient(90deg, var(--accent-primary), ${
    alert.insider_probability > 0.7
      ? "var(--severity-critical)"
      : "var(--accent-secondary)"
  });"></div>
                </div>
                <span style="font-family: var(--font-mono); font-size: 1.2rem; font-weight: 700; color: ${getSeverityColor(
                  alert.severity
                )};">
                    ${(alert.insider_probability * 100).toFixed(0)}%
                </span>
            </div>
        </div>
    `;

  document.getElementById("alert-modal").classList.add("active");
}

function closeModal() {
  document.getElementById("alert-modal").classList.remove("active");
}

// Close modal on outside click
document.getElementById("alert-modal")?.addEventListener("click", (e) => {
  if (e.target.id === "alert-modal") {
    closeModal();
  }
});

// Close modal on Escape key
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeModal();
  }
});

// ==================== ACTIONS ====================

async function triggerScan() {
  const btn = document.querySelector(".scan-btn");
  btn.innerHTML =
    '<span class="spinner" style="width: 16px; height: 16px; border-width: 2px;"></span> Scanning...';
  btn.disabled = true;

  try {
    await fetch(`${API_BASE}/scan`, { method: "POST" });

    // Wait a bit then refresh
    setTimeout(async () => {
      await refreshData();
      btn.innerHTML = '<span class="scan-icon">⚡</span> Force Scan';
      btn.disabled = false;
    }, 3000);
  } catch (error) {
    console.error("Error triggering scan:", error);
    btn.innerHTML = '<span class="scan-icon">⚡</span> Force Scan';
    btn.disabled = false;
  }
}

// ==================== BACKTEST ====================

let backtestCasesLoaded = false;

async function loadBacktestCases() {
  if (backtestCasesLoaded) return;
  const container = document.getElementById("backtest-cases");
  try {
    const response = await fetch(`${API_BASE}/backtest/cases`);
    const cases = await response.json();
    backtestCasesLoaded = true;

    if (cases.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>No known cases configured</p></div>';
      return;
    }

    container.innerHTML = cases
      .map(
        (c) => `
        <div class="backtest-case-card" id="case-${c.id}">
          <div class="case-header">
            <div class="case-name">${escapeHtml(c.name)}</div>
            <button class="run-backtest-btn" onclick="runBacktestCase('${c.id}')">Run Backtest</button>
          </div>
          <div class="case-description">${escapeHtml(c.description)}</div>
          <div class="case-meta">
            <span>Expected min score: ${c.expected_min_score}</span>
            <span>Signals: ${c.expected_signals.join(", ")}</span>
          </div>
          <div class="case-result" id="case-result-${c.id}"></div>
        </div>
      `
      )
      .join("");
  } catch (error) {
    console.error("Error loading backtest cases:", error);
    container.innerHTML = '<div class="empty-state"><p>Failed to load cases</p></div>';
  }
}

async function runBacktestCase(caseId) {
  const resultEl = document.getElementById(`case-result-${caseId}`);
  const btn = document.querySelector(`#case-${caseId} .run-backtest-btn`);
  btn.disabled = true;
  btn.textContent = "Running...";
  resultEl.innerHTML = '<div class="loading"><div class="spinner"></div><span>Analyzing trades...</span></div>';
  resultEl.style.display = "block";

  try {
    const response = await fetch(`${API_BASE}/backtest/case/${caseId}`, { method: "POST" });
    const result = await response.json();
    renderBacktestResult(resultEl, result);
  } catch (error) {
    resultEl.innerHTML = `<div class="backtest-error">Error: ${error.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Run Backtest";
  }
}

async function searchBacktestMarkets() {
  const input = document.getElementById("backtest-search-input");
  const query = input.value.trim();
  if (!query) return;

  const container = document.getElementById("backtest-search-results");
  container.innerHTML = '<div class="loading"><div class="spinner"></div><span>Searching...</span></div>';

  try {
    const response = await fetch(`${API_BASE}/backtest/search?q=${encodeURIComponent(query)}&limit=20`);
    const markets = await response.json();

    if (markets.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>No resolved markets found</p></div>';
      return;
    }

    container.innerHTML = markets
      .map(
        (m) => `
        <div class="backtest-market-item">
          <div class="market-question">${escapeHtml(m.question || "Unknown")}</div>
          <div class="market-meta">
            <span>Volume: ${formatCurrency(m.volume)}</span>
            ${m.conditionId ? `<button class="run-backtest-btn small" onclick="runMarketBacktest('${m.conditionId}', '${escapeHtml(m.question || "")}', '${escapeHtml(m.slug || "")}')">Backtest</button>` : ""}
          </div>
        </div>
      `
      )
      .join("");
  } catch (error) {
    container.innerHTML = `<div class="backtest-error">Search failed: ${error.message}</div>`;
  }
}

async function searchEarningsMarkets() {
  const container = document.getElementById("backtest-search-results");
  container.innerHTML = '<div class="loading"><div class="spinner"></div><span>Searching earnings markets...</span></div>';

  try {
    const response = await fetch(`${API_BASE}/markets/earnings?limit=20`);
    const markets = await response.json();

    if (markets.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>No earnings markets found</p></div>';
      return;
    }

    container.innerHTML = markets
      .map(
        (m) => `
        <div class="backtest-market-item">
          <div class="market-question">${escapeHtml(m.question || "Unknown")}</div>
          <div class="market-meta">
            <span>Volume: ${formatCurrency(m.volume)}</span>
            ${m.conditionId ? `<button class="run-backtest-btn small" onclick="runMarketBacktest('${m.conditionId}', '${escapeHtml(m.question || "")}', '${escapeHtml(m.slug || "")}')">Backtest</button>` : ""}
          </div>
        </div>
      `
      )
      .join("");
  } catch (error) {
    container.innerHTML = `<div class="backtest-error">Search failed: ${error.message}</div>`;
  }
}

async function runMarketBacktest(conditionId, question, slug) {
  const resultEl = document.getElementById("backtest-result");
  resultEl.style.display = "block";
  resultEl.innerHTML = '<div class="loading"><div class="spinner"></div><span>Backtesting market...</span></div>';

  try {
    const params = new URLSearchParams({ condition_id: conditionId, question, slug });
    const response = await fetch(`${API_BASE}/backtest/market?${params}`, { method: "POST" });
    const result = await response.json();
    renderBacktestResult(resultEl, result);
  } catch (error) {
    resultEl.innerHTML = `<div class="backtest-error">Backtest failed: ${error.message}</div>`;
  }
}

// Allow Enter key in search input
document.addEventListener("DOMContentLoaded", () => {
  const searchInput = document.getElementById("backtest-search-input");
  if (searchInput) {
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") searchBacktestMarkets();
    });
  }
});

function renderBacktestResult(container, result) {
  if (result.error) {
    container.innerHTML = `<div class="backtest-error">Error: ${escapeHtml(result.error)}</div>`;
    return;
  }

  const verdictClass = result.passed === true ? "pass" : result.passed === false ? "fail" : "neutral";
  const verdictText = result.passed === true ? "PASS" : result.passed === false ? "FAIL" : "COMPLETE";

  container.innerHTML = `
    <div class="backtest-summary">
      <div class="backtest-summary-header">
        <div>
          <div class="backtest-market-title">${escapeHtml(result.market_question || result.case_name || "Market")}</div>
          ${result.case_name ? `<div class="backtest-case-label">${escapeHtml(result.case_name)}</div>` : ""}
        </div>
        <div class="verdict ${verdictClass}">${verdictText}</div>
      </div>
      <div class="backtest-stats">
        <div class="backtest-stat">
          <div class="value">${result.total_trades}</div>
          <div class="label">Total Trades</div>
        </div>
        <div class="backtest-stat">
          <div class="value">${result.trades_analyzed}</div>
          <div class="label">Analyzed</div>
        </div>
        <div class="backtest-stat">
          <div class="value">${(result.suspicious_trades || []).length}</div>
          <div class="label">Suspicious</div>
        </div>
        <div class="backtest-stat">
          <div class="value" style="color: ${result.top_score >= 60 ? 'var(--severity-critical)' : result.top_score >= 40 ? 'var(--severity-medium)' : 'var(--text-secondary)'};">${result.top_score}</div>
          <div class="label">Top Score</div>
        </div>
        <div class="backtest-stat">
          <div class="value">${result.duration_seconds?.toFixed(1) || 0}s</div>
          <div class="label">Duration</div>
        </div>
      </div>
      ${(result.suspicious_trades || []).length > 0 ? `
        <h4 style="margin: 16px 0 8px; color: var(--text-secondary);">Top Suspicious Trades</h4>
        <div class="backtest-trades">
          ${result.suspicious_trades.slice(0, 10).map((t) => `
            <div class="backtest-trade-item ${t.is_alert ? 'is-alert' : ''}">
              <div class="bt-trade-main">
                <a href="https://polymarket.com/profile/${t.trader}" target="_blank" class="trader-link">👛 ${t.trader.substring(0, 12)}...</a>
                <span>${t.side} ${formatCurrency(t.notional_usd)} @ ${t.price?.toFixed(1) || 0}¢</span>
                <span>📈 ${t.wallet_trades} trades / ${t.wallet_markets} markets</span>
              </div>
              <div class="bt-trade-signals">
                ${(t.signals || []).filter(s => s.score > 0).map(s => `<span class="signal-chip active">${s.signal.split(' ')[0]} +${s.score}</span>`).join('')}
              </div>
              <div class="activity-score">
                <span class="score-value ${t.score >= 80 ? 'critical' : t.score >= 60 ? 'high' : t.score >= 40 ? 'medium' : 'low'}">${t.score}</span>
                ${t.severity ? `<span class="score-label">${t.severity.toUpperCase()}</span>` : ''}
              </div>
            </div>
          `).join('')}
        </div>
      ` : '<p style="color: var(--text-muted); margin-top: 16px;">No suspicious trades found.</p>'}
    </div>
  `;
}

// ==================== SMART MONEY ====================

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
    // Refresh leaderboard to update watch buttons
    if (currentView === "smartmoney") fetchLeaderboard();
  } catch (error) {
    console.error("Error unwatching trader:", error);
  }
}

// ==================== UTILITIES ====================

function formatCurrency(value) {
  if (!value && value !== 0) return "--";
  if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
}

function formatNumber(value) {
  if (!value && value !== 0) return "--";
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

function formatTimeAgo(isoString) {
  if (!isoString) return "--";
  const date = new Date(isoString);
  const now = new Date();
  const seconds = Math.floor((now - date) / 1000);

  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function truncate(str, length) {
  if (!str) return "";
  return str.length > length ? str.substring(0, length) + "..." : str;
}

function getSeverityColor(severity) {
  const colors = {
    critical: "var(--severity-critical)",
    high: "var(--severity-high)",
    medium: "var(--severity-medium)",
    low: "var(--severity-low)",
  };
  return colors[severity] || colors.low;
}
