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
    
    # Detection Thresholds - Based on the Polymarket Watch parameters
    min_notional_alert: float = 1000  # Minimum $ bet to track
    max_unique_markets_suspicious: int = 10  # Low market count = suspicious
    volume_spike_zscore: float = 2.5  # Standard deviations for anomaly
    whale_threshold_usd: float = 5000  # Large bet threshold
    fresh_wallet_max_trades: int = 5  # "Low activity wallet" threshold
    win_rate_suspicious_threshold: float = 0.85  # Unusually high win rate
    
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
    notification_min_severity: str = "medium"  # low, medium, high, critical
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./insider_detector.db"
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

