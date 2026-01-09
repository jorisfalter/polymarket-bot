"""
Data models for insider detection
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class AlertSeverity(str, Enum):
    """Severity levels for suspicious activity"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WalletProfile(BaseModel):
    """Profile of a trader's wallet"""
    address: str
    display_name: Optional[str] = None
    total_trades: int = 0
    unique_markets: int = 0
    total_volume_usd: float = 0
    win_rate: Optional[float] = None
    first_seen: Optional[datetime] = None
    last_active: Optional[datetime] = None
    
    # Computed suspicion indicators
    is_fresh_wallet: bool = False
    is_whale: bool = False
    has_unusual_win_rate: bool = False
    
    @property
    def suspicion_score(self) -> float:
        """Calculate overall suspicion score 0-100"""
        score = 0
        
        # Fresh wallet with big bets = very suspicious
        if self.is_fresh_wallet:
            score += 30
        
        # Low market diversity
        if self.unique_markets <= 5:
            score += 25
        elif self.unique_markets <= 10:
            score += 15
            
        # Whale activity
        if self.is_whale:
            score += 20
            
        # Unusually high win rate
        if self.has_unusual_win_rate:
            score += 25
            
        return min(score, 100)


class Trade(BaseModel):
    """Individual trade data"""
    id: str
    market_id: str
    market_slug: str
    market_question: str
    trader_address: str
    side: str  # BUY or SELL
    outcome: str  # YES or NO
    shares: float
    price: float  # in cents (e.g., 7.3)
    notional_usd: float
    timestamp: datetime
    
    # Context
    market_volume_24h: Optional[float] = None
    market_liquidity: Optional[float] = None
    
    
class SuspiciousTrade(BaseModel):
    """A trade flagged as potentially suspicious"""
    trade: Trade
    wallet: WalletProfile
    
    # Alert details
    severity: AlertSeverity
    suspicion_score: float = Field(ge=0, le=100)
    flags: List[str] = []  # Human-readable reasons
    
    # Contextual analysis
    volume_zscore: Optional[float] = None
    time_to_resolution: Optional[float] = None  # hours until market resolved
    price_at_resolution: Optional[float] = None
    potential_profit: Optional[float] = None
    
    @property
    def potential_return_pct(self) -> Optional[float]:
        """Calculate potential return if bet wins"""
        if self.trade.price > 0:
            return ((100 - self.trade.price) / self.trade.price) * 100
        return None


class MarketSnapshot(BaseModel):
    """Current state of a prediction market"""
    id: str
    slug: str
    question: str
    description: Optional[str] = None
    category: Optional[str] = None
    
    # Pricing
    yes_price: float
    no_price: float
    
    # Volume metrics
    volume_24h: float
    volume_total: float
    liquidity: float
    
    # Status
    is_active: bool
    end_date: Optional[datetime] = None
    resolution_date: Optional[datetime] = None
    resolved_outcome: Optional[str] = None
    
    # Computed
    volume_zscore: Optional[float] = None  # vs historical average
    is_volume_anomaly: bool = False


class InsiderAlert(BaseModel):
    """Complete alert package for UI"""
    id: str
    created_at: datetime
    
    # The suspicious activity
    suspicious_trade: SuspiciousTrade
    market: MarketSnapshot
    
    # Additional context
    related_trades: List[Trade] = []  # Other trades in same market/timeframe
    similar_wallets: List[str] = []  # Wallets with correlated activity
    
    # Analysis
    insider_probability: float = Field(ge=0, le=1)  # ML model output
    narrative: str  # Human-readable explanation


class DashboardStats(BaseModel):
    """Aggregate statistics for dashboard"""
    total_alerts_24h: int = 0
    critical_alerts_24h: int = 0
    total_suspicious_volume_24h: float = 0
    top_suspicious_markets: List[str] = []
    most_active_suspicious_wallets: List[str] = []
    avg_suspicion_score: float = 0
    
    # Trends
    alerts_change_pct: float = 0  # vs previous 24h
    volume_change_pct: float = 0


class WalletCluster(BaseModel):
    """Group of wallets with coordinated activity"""
    cluster_id: str
    wallets: List[str]
    correlation_score: float  # How synchronized their trades are
    shared_markets: List[str]
    total_volume: float
    first_coordinated_trade: datetime
    
    @property
    def is_suspicious(self) -> bool:
        return self.correlation_score > 0.8 and len(self.wallets) > 2

