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

  // Show/hide views
  document.getElementById("alerts-view").style.display =
    view === "alerts" ? "flex" : "none";
  document.getElementById("activity-view").style.display =
    view === "activity" ? "flex" : "none";
  document.getElementById("signals-view").style.display =
    view === "signals" ? "flex" : "none";

  // Refresh data for the view
  if (view === "activity") renderActivity();
  if (view === "signals") renderSignalStats();
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

  // Build Polymarket link if slug is available
  const marketLink = trade.market_slug
    ? `https://polymarket.com/event/${trade.market_slug}`
    : null;

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
                        ${
                          marketLink
                            ? `<a href="${marketLink}" target="_blank" class="polymarket-link-icon" onclick="event.stopPropagation()" title="Open on Polymarket">↗</a>`
                            : ""
                        }
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

      // Build Polymarket link if slug is available
      const marketLink = entry.market_slug
        ? `https://polymarket.com/event/${entry.market_slug}`
        : null;

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
    "🐣 Fresh Wallet":
      "Detects new or low-activity wallets making significant bets. Fresh wallets are suspicious when making large trades.",
    "💰 Position Size":
      "Flags unusually large bets relative to the trader's history or absolute thresholds.",
    "🎯 Market Diversity":
      "Low market diversity suggests focused betting, which may indicate informed trading.",
    "📈 Volume Spike":
      "Detects unusual trading volume spikes using statistical analysis (Z-score).",
    "🏆 Win Rate":
      "Identifies traders with suspiciously high win rates that may indicate insider information.",
    "⏰ Timing":
      "Flags trades placed close to expected market resolution, especially at extreme odds.",
    "🎲 Extreme Odds":
      'Betting on low probability outcomes offers high risk/reward - insiders often bet on "unlikely" outcomes they know will happen.',
  };

  const desc = descriptions[signal.signal] || signal.signal;
  const details = signal.details ? `\n\nCurrent: ${signal.details}` : "";
  const threshold = signal.threshold ? `\nThreshold: ${signal.threshold}` : "";

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

  // Build Polymarket link if slug is available
  const marketLink = trade.market_slug
    ? `https://polymarket.com/event/${trade.market_slug}`
    : null;

  document.getElementById("modal-body").innerHTML = `
        <div class="modal-header">
            <div class="modal-title">
                ${trade.market_question}
                ${
                  marketLink
                    ? `<a href="${marketLink}" target="_blank" class="polymarket-btn" title="View on Polymarket">View on Polymarket ↗</a>`
                    : ""
                }
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
