# 🔍 Polymarket Insider Detector

A real-time surveillance system that monitors Polymarket for unusual trading patterns that may indicate insider information.

![Dashboard Preview](https://img.shields.io/badge/status-active-brightgreen) ![Python](https://img.shields.io/badge/python-3.10+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## 🎯 What It Does

This tool implements the philosophy: **"You don't need to predict the future, you need to track suspicious behavior."**

It monitors Polymarket 24/7 and flags trades that exhibit patterns consistent with insider knowledge:

### Detection Signals

| Signal                     | Description                                   | Weight   |
| -------------------------- | --------------------------------------------- | -------- |
| 🐣 **Fresh Wallet**        | Low activity wallets making significant bets  | High     |
| 💰 **Whale Bets**          | Large position sizes ($5K+)                   | Medium   |
| 🎯 **Low Diversity**       | Trading in very few unique markets            | High     |
| 📈 **Volume Spike**        | Market experiencing abnormal volume (Z-score) | Medium   |
| 🏆 **Win Rate Anomaly**    | Unusually high historical win rate (>85%)     | Medium   |
| ⏰ **Timing**              | Trades close to expected resolution           | Medium   |
| 🎲 **Extreme Odds**        | Betting on low-probability outcomes (<20¢)    | High     |
| 🕸️ **Coordinated Trading** | Multiple wallets trading in sync              | Critical |

### Advanced Features

- **Wallet Clustering**: Detects coordinated trading networks using forensic network analysis
- **Information Cascade Detection**: Identifies "spark" trades that trigger follow-on activity
- **Real-time Alerts**: Severity-based alert system (Critical → High → Medium → Low)
- **Suspicion Scoring**: 0-100 score combining multiple signals

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- pip

### Installation

```bash
# Clone the repository
cd polymarket

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running the App

```bash
# Start the server
python -m uvicorn backend.main:app --reload --port 8000
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

## 📊 Dashboard

The dashboard provides:

- **Real-time Alert Feed**: Live stream of suspicious trades
- **Severity Filtering**: Filter by Critical/High/Medium/Low
- **Suspicious Markets**: Markets with the most flagged activity
- **Wallet Clusters**: Detected coordinated trading networks
- **Statistics**: 24h overview of suspicious activity

## 🔧 Configuration

Edit `backend/config.py` to adjust detection thresholds:

```python
# Detection Thresholds
min_notional_alert: float = 1000       # Minimum $ to track
max_unique_markets_suspicious: int = 10 # Low diversity threshold
volume_spike_zscore: float = 2.5       # Volume anomaly sensitivity
whale_threshold_usd: float = 5000      # Large bet threshold
fresh_wallet_max_trades: int = 5       # "New wallet" definition
win_rate_suspicious_threshold: float = 0.85  # Win rate flag
```

## 🔑 Polymarket API Credentials (Optional)

The app works with **public endpoints by default**, analyzing market volumes and activity. For **full trade-level data**, you can add API credentials:

### Getting API Keys

1. Go to [Polymarket](https://polymarket.com) → **Settings** → **API**
2. Enable API trading
3. Generate an API key + secret
4. Add to your `.env`:

```bash
POLY_API_KEY=your-api-key
POLY_API_SECRET=your-api-secret
POLY_PASSPHRASE=your-passphrase  # optional
```

### What Credentials Unlock

| Feature                  | Without API Key | With API Key |
| ------------------------ | --------------- | ------------ |
| Market data & volumes    | ✅              | ✅           |
| Global activity feed     | ✅              | ✅           |
| Individual trade history | ❌              | ✅           |
| Order book depth         | ❌              | ✅           |
| Wallet trade details     | ⚠️ Limited      | ✅ Full      |

The app will automatically use credentials if provided, falling back to public endpoints otherwise.

## 📬 Notifications

Get alerted via **email (Postmark)** or **webhook (n8n/Zapier)** when suspicious trades are detected.

### Option 1: Postmark (Email)

Set these environment variables or edit `backend/config.py`:

```bash
export POSTMARK_API_TOKEN="your-postmark-server-token"
export POSTMARK_FROM_EMAIL="alerts@yourdomain.com"  # Must be verified in Postmark
export ALERT_EMAIL="you@example.com"
export NOTIFICATION_MIN_SEVERITY="medium"  # low, medium, high, critical
```

### Option 2: Webhook (n8n, Zapier, Make)

```bash
export WEBHOOK_URL="https://your-n8n-instance.com/webhook/xxxxx"
```

The webhook receives a JSON payload with full alert details:

```json
{
  "event": "insider_alert",
  "severity": "high",
  "suspicion_score": 75,
  "flags": ["🐣 Low activity wallet", "💰 Large position: $6,000"],
  "trade": {
    "market_question": "Will X happen?",
    "side": "BUY",
    "notional_usd": 6000,
    "price_cents": 7.3,
    "potential_return_pct": 1269
  },
  "wallet": {
    "address": "0x...",
    "total_trades": 4,
    "unique_markets": 3
  }
}
```

### Both Together

You can use both Postmark AND webhook simultaneously—just set both environment variables.

## 🛠️ API Endpoints

| Endpoint                      | Description                 |
| ----------------------------- | --------------------------- |
| `GET /api/alerts`             | Get suspicious trade alerts |
| `GET /api/stats`              | Dashboard statistics        |
| `GET /api/wallet/{address}`   | Analyze specific wallet     |
| `GET /api/clusters`           | Coordinated wallet clusters |
| `GET /api/markets/suspicious` | Most suspicious markets     |
| `POST /api/scan`              | Trigger manual scan         |

## 🧠 How Detection Works

### 1. Data Collection

The system polls Polymarket's APIs:

- **Gamma API**: Market metadata, events
- **CLOB API**: Real-time trades, order books
- **Data API**: User positions, trade history

### 2. Trade Analysis

Each large trade is analyzed against multiple signals:

```
Suspicion Score = Σ(Signal Weights)

Example:
- Fresh wallet (+35)
- Large bet (+25)
- Low market diversity (+30)
- Extreme odds (+20)
= 110 → Capped at 100 (CRITICAL)
```

### 3. Pattern Recognition

Advanced patterns detected:

- **Wallet Clusters**: Graph analysis of coordinated trades
- **Information Cascades**: First-mover detection
- **Volume Anomalies**: Statistical deviation from baseline

## 📁 Project Structure

```
polymarket/
├── backend/
│   ├── __init__.py
│   ├── config.py            # Configuration
│   ├── models.py            # Data models
│   ├── polymarket_client.py # API client
│   ├── detectors.py         # Detection algorithms
│   ├── notifications.py     # Email/webhook alerts
│   └── main.py              # FastAPI app
├── frontend/
│   ├── index.html           # Dashboard UI
│   ├── styles.css           # Styling
│   └── app.js               # Frontend logic
├── requirements.txt
└── README.md
```

## ⚠️ Disclaimer

This tool is for **research and educational purposes only**. It does not:

- Provide financial advice
- Guarantee detection of actual insider trading
- Replace proper due diligence

Use at your own risk. Not affiliated with Polymarket.

## 🤝 Contributing

Contributions welcome! Ideas for improvement:

- [ ] Machine learning classifier for insider probability
- [x] Email/webhook alert integration (Postmark, n8n)
- [ ] Historical backtesting module
- [ ] Cross-platform analysis (Kalshi, Metaculus)
- [ ] Wallet reputation database
- [ ] Telegram/Discord bot

## 📜 License

MIT License - see LICENSE file for details.

---

Built with 🔍 for the prediction market community
