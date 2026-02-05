# Polymarket Insider Detector

A real-time surveillance system that monitors Polymarket for unusual trading patterns that may indicate insider information.

## What It Does

Monitors Polymarket 24/7 and flags trades that exhibit patterns consistent with insider knowledge. The philosophy: **"You don't need to predict the future, you need to track suspicious behavior."**

### Detection Signals

| Signal | Description | Weight |
|---|---|---|
| Fresh Wallet | Low activity wallets making significant bets | High |
| Whale Bets | Large position sizes ($5K+) | Medium |
| Low Diversity | Trading in very few unique markets | High |
| Volume Spike | Market experiencing abnormal volume (Z-score) | Medium |
| Win Rate Anomaly | Unusually high historical win rate (>85%) | Medium |
| Timing | Trades close to expected resolution | Medium |
| Extreme Odds | Betting on low-probability outcomes (<20c) | High |
| Coordinated Trading | Multiple wallets trading in sync | Critical |

Severity is capped based on trade size — a $28 bet can never be CRITICAL regardless of other signals. Minimum notional thresholds: $5k for CRITICAL, $2k for HIGH, $500 for MEDIUM, $100 for any alert.

## Tech Stack

- **Backend**: Python (FastAPI, APScheduler, httpx, numpy/scipy for analysis)
- **Frontend**: Vanilla HTML/CSS/JS (no build step, served as static files by FastAPI)
- **Deployment**: Docker on Hetzner, auto-deployed via GitHub Actions on push to `main`

## Project Structure

```
polymarket/
├── backend/                    # Python backend (FastAPI)
│   ├── __init__.py
│   ├── config.py               # All settings and thresholds (pydantic-settings, reads .env)
│   ├── models.py               # Pydantic data models (Trade, WalletProfile, SuspiciousTrade, etc.)
│   ├── polymarket_client.py    # Async API client for Polymarket (Gamma, CLOB, Data APIs)
│   ├── detectors.py            # Detection engine — scoring and signal analysis per trade
│   ├── notifications.py        # Sends alerts via Postmark (email) and/or webhook (n8n/Zapier)
│   └── main.py                 # FastAPI app — API routes, scheduler, scan loop, deduplication
├── frontend/                   # Vanilla JS dashboard (no framework, no build step)
│   ├── index.html              # Dashboard page structure
│   ├── styles.css              # Styling (dark theme)
│   └── app.js                  # Dashboard logic — fetches /api/* and renders alerts, stats, charts
├── .github/
│   └── workflows/
│       └── deploy.yml          # GitHub Actions: SSH into Hetzner, git pull, docker compose up
├── run.py                      # Quick-start script — checks deps, launches uvicorn
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Python 3.11-slim, installs deps, copies backend + frontend
├── docker-compose.yml          # Runs the app on localhost:8000 with healthcheck
├── deploy.sh                   # Manual deployment script (installs Docker, sets up /opt/polymarket-insider)
├── Caddyfile                   # Example Caddy reverse proxy config (optional, not used in docker-compose)
└── .env                        # Environment variables (not committed) — API keys, notification config
```

### Backend Files

| File | What it does |
|---|---|
| `config.py` | Central configuration. All thresholds, API URLs, notification settings, and severity cap values. Uses pydantic-settings so everything can be overridden via `.env` or environment variables. |
| `models.py` | Pydantic models for `Trade`, `WalletProfile`, `SuspiciousTrade`, `InsiderAlert`, `MarketSnapshot`, `WalletCluster`, and `DashboardStats`. Defines the data shapes used everywhere. |
| `polymarket_client.py` | Async HTTP client that talks to Polymarket's three APIs (Gamma for market metadata, CLOB for trades/orderbook, Data for user history). Handles auth when API keys are configured, falls back to public endpoints. |
| `detectors.py` | The core detection engine. Analyzes each trade against multiple signals (fresh wallet, whale bet, volume spike, win rate, timing, extreme odds). Produces a 0-100 suspicion score and severity level. Caps severity based on trade size. Also detects wallet clusters (coordinated trading). |
| `notifications.py` | Sends alerts via Postmark (styled HTML email) and/or a generic webhook (JSON payload for n8n/Zapier/Make). Filters by minimum severity. |
| `main.py` | The FastAPI application. Serves the frontend as static files, runs a scheduled scan every 5 minutes via APScheduler, exposes REST API endpoints. Handles trade deduplication using composite keys. |

### Frontend Files

| File | What it does |
|---|---|
| `index.html` | Single-page dashboard with header, stats cards, severity filter tabs, alert feed, and sections for suspicious markets and wallet clusters. |
| `styles.css` | Dark-themed styling. |
| `app.js` | Fetches data from `/api/alerts`, `/api/stats`, `/api/clusters`, etc. Renders alert cards with signal breakdowns, Polymarket links, and auto-refreshes every 30 seconds. |

## Quick Start

### Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the server (with auto-reload)
python run.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### Docker

```bash
docker compose up -d --build
```

## Configuration

All settings live in `backend/config.py` and can be overridden via `.env`:

```bash
# Detection thresholds
MIN_NOTIONAL_ALERT=1000           # Minimum $ bet to track
WHALE_THRESHOLD_USD=5000          # Large bet threshold
FRESH_WALLET_MAX_TRADES=5         # "Low activity wallet" definition
WIN_RATE_SUSPICIOUS_THRESHOLD=0.85
VOLUME_SPIKE_ZSCORE=2.5           # Standard deviations for anomaly

# Severity caps (small bets can't be high severity)
MIN_NOTIONAL_CRITICAL=5000
MIN_NOTIONAL_HIGH=2000
MIN_NOTIONAL_MEDIUM=500
MIN_NOTIONAL_LOW=100

# Notifications — Postmark (email)
POSTMARK_API_TOKEN=your-token
POSTMARK_FROM_EMAIL=alerts@yourdomain.com
ALERT_EMAIL=you@example.com
NOTIFICATION_MIN_SEVERITY=medium

# Notifications — Webhook
WEBHOOK_URL=https://your-n8n-instance.com/webhook/xxxxx

# Dashboard URL (used in email links)
DASHBOARD_URL=https://your-domain.com
```

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/alerts` | Suspicious trade alerts (filterable by severity) |
| `GET /api/stats` | 24h dashboard statistics |
| `GET /api/wallet/{address}` | Detailed wallet analysis |
| `GET /api/clusters` | Detected coordinated wallet clusters |
| `GET /api/markets/suspicious` | Markets with most flagged activity |
| `GET /api/activity` | Raw activity log (all scanned trades) |
| `GET /api/activity/stats` | Signal distribution stats (for tuning) |
| `POST /api/scan` | Trigger a manual scan |

## Deployment

The app auto-deploys to Hetzner on every push to `main` via GitHub Actions (`.github/workflows/deploy.yml`). The workflow SSHs into the server, pulls the latest code, and rebuilds the Docker container.

For manual first-time setup, use `deploy.sh` which installs Docker and configures the app at `/opt/polymarket-insider`.

## Disclaimer

This tool is for research and educational purposes only. It does not provide financial advice, guarantee detection of actual insider trading, or replace proper due diligence. Not affiliated with Polymarket.
