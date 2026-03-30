"""
Configuration for Polymarket Insider Detector
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings with sensible defaults"""
    
    # Polymarket API URLs
    gamma_api_url: str = "https://gamma-api.polymarket.com"
    clob_api_url: str = "https://clob.polymarket.com"
    data_api_url: str = "https://data-api.polymarket.com"
    
    # Polymarket API Credentials (optional - for full trade data access)
    poly_api_key: Optional[str] = None
    poly_api_secret: Optional[str] = None
    poly_passphrase: Optional[str] = None

    # Polymarket Trading Credentials (for auto-sell execution)
    # Export private key from: https://reveal.magic.link/polymarket
    poly_private_key: Optional[str] = None
    poly_wallet_address: Optional[str] = None
    
    # Detection Thresholds - Based on the Polymarket Watch parameters
    min_notional_alert: float = 1000  # Minimum $ bet to track
    max_unique_markets_suspicious: int = 10  # Low market count = suspicious
    volume_spike_zscore: float = 2.5  # Standard deviations for anomaly
    whale_threshold_usd: float = 5000  # Large bet threshold
    fresh_wallet_max_trades: int = 5  # "Low activity wallet" threshold
    win_rate_suspicious_threshold: float = 0.85  # Unusually high win rate

    # Minimum notional for each severity level (small bets can't be high severity)
    min_notional_critical: float = 5000  # Must be $5k+ for CRITICAL
    min_notional_high: float = 2000      # Must be $2k+ for HIGH
    min_notional_medium: float = 500     # Must be $500+ for MEDIUM
    min_notional_low: float = 100        # Minimum to generate any alert
    
    # Scan pipeline settings
    scan_analysis_cap: int = 200  # Max trades to analyze per scan (was 50)
    deep_scan_enabled: bool = True  # Deep-fetch hot markets after initial scan
    deep_scan_max_markets: int = 5  # Max markets to deep scan
    fresh_wallet_priority_boost: bool = True  # Prioritize fresh wallets in sorting

    # Time windows for analysis
    volume_lookback_hours: int = 168  # 7 days for baseline
    alert_window_hours: int = 24  # Recent activity window
    
    # Notifications - Postmark (email)
    postmark_api_token: Optional[str] = None  # Your Postmark server token
    postmark_from_email: str = "alerts@yourdomain.com"  # Must be verified in Postmark
    alert_email: Optional[str] = None  # Where to send alerts
    
    # Notifications - Webhook (n8n, Zapier, Make, etc.)
    webhook_url: Optional[str] = None  # Your n8n/Zapier webhook URL
    
    # Notification settings
    notification_min_severity: str = "high"  # low, medium, high, critical
    dashboard_url: str = "http://localhost:8000"  # Public URL for email links
    exclude_sports_alerts: bool = True  # Skip alerts for sports events
    exclude_crypto_price_alerts: bool = True  # Skip alerts for BTC/ETH price markets
    
    # Strategy Engine (DISABLED — replaced by AI agent)
    strategy_enabled: bool = False
    strategy_insider_enabled: bool = False
    strategy_smartmoney_enabled: bool = False
    strategy_arbitrage_enabled: bool = False

    # Hard limits — DO NOT raise without explicit user approval
    strategy_max_total_exposure: float = 100.0   # Max USD across ALL open positions
    strategy_max_per_trade: float = 25.0         # Max USD per single trade
    strategy_balance_floor: float = 840.0        # Refuse trades if balance would drop below
    strategy_max_open_positions: int = 5          # Max concurrent positions

    # Insider signal strategy
    insider_max_price_drift_pct: float = 10.0    # Skip if price moved more than this %
    insider_min_score: int = 60                   # Minimum suspicion score (HIGH+)

    # Smart money copy trading
    smartmoney_min_win_rate: float = 0.6         # Minimum win rate for auto-curation
    smartmoney_min_markets: int = 20              # Must have traded 20+ markets
    smartmoney_max_wallets: int = 10              # Max wallets to auto-watch

    # Resolution arbitrage strategy
    arb_min_probability: float = 0.95            # Minimum outcome probability
    arb_max_probability: float = 0.99            # Above this, spread too thin
    arb_max_hours_to_end: float = 48.0           # Market must end within this window
    arb_min_liquidity: float = 5000.0            # Minimum market liquidity USD

    # AI Trading Agent
    agent_enabled: bool = True
    anthropic_api_key: Optional[str] = None
    agent_model: str = "claude-haiku-4-5-20251001"
    agent_max_positions: int = 5
    agent_max_per_trade: float = 1.0        # Penny trades: max $1 per trade
    agent_max_total_exposure: float = 5.0    # Max $5 total at risk

    # Twitter/X integration (disabled — account suspended)
    twitter_api_key: Optional[str] = None
    twitter_api_secret: Optional[str] = None
    twitter_access_token: Optional[str] = None
    twitter_access_secret: Optional[str] = None
    twitter_enabled: bool = False

    # Telegram bot
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    telegram_enabled: bool = True

    # Google Sheets integration
    google_sheets_id: Optional[str] = None               # Spreadsheet ID from URL
    google_service_account_file: Optional[str] = None     # Path to service account JSON
    google_oauth_creds_file: Optional[str] = None         # Path to OAuth user creds JSON

    # Database
    database_url: str = "sqlite+aiosqlite:///./insider_detector.db"
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

