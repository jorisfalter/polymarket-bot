"""
Insider Trading Detection Algorithms

This module implements various detection strategies:
1. Fresh Wallet Detection - New wallets making large bets
2. Volume Anomaly Detection - Z-score based spike detection  
3. Whale Tracking - Large position monitoring
4. Wallet Clustering - Coordinated trading detection
5. Timing Analysis - Trades close to resolution
6. Win Rate Anomaly - Unusually successful traders
7. Information Cascade - Pattern of informed trading spreading
"""
import numpy as np
from scipy import stats
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
from collections import defaultdict
from loguru import logger

from .config import settings
from .models import (
    WalletProfile, Trade, SuspiciousTrade, MarketSnapshot,
    InsiderAlert, AlertSeverity, WalletCluster
)


class InsiderDetector:
    """
    Main detection engine combining multiple signals
    """
    
    def __init__(self):
        # Historical data for baseline calculations
        self.volume_history: Dict[str, List[float]] = defaultdict(list)
        self.wallet_cache: Dict[str, WalletProfile] = {}
        self.trade_history: List[Trade] = []
        
    def analyze_trade(
        self,
        trade_data: Dict,
        wallet_profile: Dict,
        market_data: Dict
    ) -> Optional[SuspiciousTrade]:
        """
        Analyze a single trade for suspicious patterns
        Returns SuspiciousTrade if suspicious, None otherwise
        """
        suspicious, _ = self.analyze_trade_detailed(trade_data, wallet_profile, market_data)
        return suspicious
    
    def analyze_trade_detailed(
        self,
        trade_data: Dict,
        wallet_profile: Dict,
        market_data: Dict
    ) -> Tuple[Optional[SuspiciousTrade], List[Dict]]:
        """
        Analyze a single trade and return BOTH the result AND detailed signal breakdown.
        This is useful for debugging and understanding why trades are/aren't flagged.
        
        Returns: (SuspiciousTrade or None, list of signal details)
        """
        flags = []
        severity_score = 0
        signals = []  # Detailed breakdown of each signal
        
        # Build models from raw data
        wallet = self._build_wallet_profile(wallet_profile)
        trade = self._build_trade(trade_data, market_data)
        
        # ========== DETECTION CHECKS ==========
        
        # 1. Fresh Wallet Check (🐣 Low Activity Wallet)
        fresh_wallet_score = self._check_fresh_wallet(wallet)
        signals.append({
            "signal": "🐣 Fresh Wallet",
            "score": fresh_wallet_score,
            "details": f"{wallet.total_trades} trades, {wallet.unique_markets} markets",
            "threshold": f"<{settings.fresh_wallet_max_trades} trades"
        })
        if fresh_wallet_score > 0:
            flags.append(f"🐣 Low activity wallet ({wallet.total_trades} trades, {wallet.unique_markets} markets)")
            severity_score += fresh_wallet_score
            
        # 2. Unusual Position Size
        size_score = self._check_unusual_size(trade, wallet)
        signals.append({
            "signal": "💰 Position Size",
            "score": size_score,
            "details": f"${trade.notional_usd:,.0f}",
            "threshold": f">${settings.whale_threshold_usd:,} whale"
        })
        if size_score > 0:
            flags.append(f"💰 Large position: ${trade.notional_usd:,.0f} ({self._get_size_context(trade, wallet)})")
            severity_score += size_score
            
        # 3. Low Market Diversity  
        diversity_score = self._check_low_diversity(wallet)
        signals.append({
            "signal": "🎯 Market Diversity",
            "score": diversity_score,
            "details": f"{wallet.unique_markets} unique markets",
            "threshold": f"<{settings.max_unique_markets_suspicious} suspicious"
        })
        if diversity_score > 0:
            flags.append(f"🎯 Only {wallet.unique_markets} unique markets traded")
            severity_score += diversity_score
            
        # 4. Volume Anomaly (market-wide)
        volume_score, zscore = self._check_volume_anomaly(trade, market_data)
        signals.append({
            "signal": "📈 Volume Spike",
            "score": volume_score,
            "details": f"Z-score: {zscore:.2f}",
            "threshold": f">{settings.volume_spike_zscore}σ"
        })
        if volume_score > 0:
            flags.append(f"📈 Volume spike: {zscore:.1f}σ above normal")
            severity_score += volume_score
            
        # 5. Win Rate Anomaly
        winrate_score = self._check_win_rate_anomaly(wallet)
        signals.append({
            "signal": "🏆 Win Rate",
            "score": winrate_score,
            "details": f"{wallet.win_rate*100:.0f}%" if wallet.win_rate else "N/A",
            "threshold": f">{settings.win_rate_suspicious_threshold*100:.0f}%"
        })
        if winrate_score > 0:
            flags.append(f"🏆 Suspicious win rate: {wallet.win_rate*100:.0f}%")
            severity_score += winrate_score
            
        # 6. Timing Analysis (close to likely resolution)
        timing_score = self._check_timing(trade, market_data)
        signals.append({
            "signal": "⏰ Timing",
            "score": timing_score,
            "details": "Near resolution" if timing_score > 0 else "Normal",
            "threshold": "<24h to resolution"
        })
        if timing_score > 0:
            flags.append("⏰ Trade placed close to expected resolution")
            severity_score += timing_score
            
        # 7. Extreme Odds Bet
        odds_score = self._check_extreme_odds(trade)
        potential_return = ((100 - trade.price) / trade.price) * 100 if trade.price > 0 else 0
        signals.append({
            "signal": "🎲 Extreme Odds",
            "score": odds_score,
            "details": f"{trade.price:.1f}¢ ({potential_return:.0f}% potential)",
            "threshold": "<20¢ price"
        })
        if odds_score > 0:
            flags.append(f"🎲 Betting on {trade.price:.1f}¢ outcome ({potential_return:.0f}% potential return)")
            severity_score += odds_score
            
        # ========== DETERMINE IF SUSPICIOUS ==========
        
        if severity_score < 20:
            return None, signals  # Not suspicious enough, but return signals for logging
            
        # Determine severity level
        if severity_score >= 80:
            severity = AlertSeverity.CRITICAL
        elif severity_score >= 60:
            severity = AlertSeverity.HIGH
        elif severity_score >= 40:
            severity = AlertSeverity.MEDIUM
        else:
            severity = AlertSeverity.LOW
            
        suspicious_trade = SuspiciousTrade(
            trade=trade,
            wallet=wallet,
            severity=severity,
            suspicion_score=min(severity_score, 100),
            flags=flags,
            volume_zscore=zscore if volume_score > 0 else None,
            potential_profit=self._calculate_potential_profit(trade)
        )
        
        return suspicious_trade, signals
    
    # ==================== INDIVIDUAL DETECTORS ====================
    
    def _check_fresh_wallet(self, wallet: WalletProfile) -> float:
        """
        Detect low activity wallets making significant bets
        Fresh wallets are highly suspicious when making large trades
        """
        score = 0
        
        # Very few trades overall
        if wallet.total_trades <= settings.fresh_wallet_max_trades:
            score += 35
            wallet.is_fresh_wallet = True
        elif wallet.total_trades <= 20:
            score += 15
            
        # Recent account (less than 30 days old)
        if wallet.first_seen:
            try:
                # Handle both timezone-aware and naive datetimes
                now = datetime.utcnow()
                first_seen = wallet.first_seen
                # Make both naive for comparison
                if hasattr(first_seen, 'tzinfo') and first_seen.tzinfo is not None:
                    first_seen = first_seen.replace(tzinfo=None)
                account_age = (now - first_seen).days
                if account_age < 7:
                    score += 20
                elif account_age < 30:
                    score += 10
            except Exception:
                pass  # Skip age check if datetime parsing fails
                
        return score
    
    def _check_unusual_size(self, trade: Trade, wallet: WalletProfile) -> float:
        """
        Check if trade size is unusual relative to:
        - Absolute thresholds
        - Wallet's typical behavior
        """
        score = 0
        
        # Absolute whale threshold
        if trade.notional_usd >= settings.whale_threshold_usd:
            score += 25
            wallet.is_whale = True
            
        # Relative to wallet's average (if we have history)
        if wallet.total_volume_usd > 0 and wallet.total_trades > 0:
            avg_trade = wallet.total_volume_usd / wallet.total_trades
            if trade.notional_usd > avg_trade * 5:
                score += 20  # 5x their normal size
            elif trade.notional_usd > avg_trade * 3:
                score += 10
                
        return score
    
    def _check_low_diversity(self, wallet: WalletProfile) -> float:
        """
        Low market diversity = focused betting = potentially informed
        """
        if wallet.unique_markets <= 3:
            return 30
        elif wallet.unique_markets <= settings.max_unique_markets_suspicious:
            return 15
        return 0
    
    def _check_volume_anomaly(
        self, 
        trade: Trade, 
        market_data: Dict
    ) -> Tuple[float, float]:
        """
        Detect if market is experiencing unusual volume
        Uses Z-score against historical baseline
        """
        market_id = trade.market_id
        current_volume = market_data.get("volume24hr", 0)
        
        # Get or initialize history
        history = self.volume_history.get(market_id, [])
        
        if len(history) < 3:
            # Not enough history, add current and return
            self.volume_history[market_id].append(current_volume)
            return 0, 0
            
        # Calculate Z-score
        mean_vol = np.mean(history)
        std_vol = np.std(history) if np.std(history) > 0 else 1
        zscore = (current_volume - mean_vol) / std_vol
        
        # Update history
        self.volume_history[market_id].append(current_volume)
        if len(self.volume_history[market_id]) > 30:  # Keep 30 days
            self.volume_history[market_id].pop(0)
        
        if zscore >= settings.volume_spike_zscore * 2:
            return 30, zscore
        elif zscore >= settings.volume_spike_zscore:
            return 15, zscore
            
        return 0, zscore
    
    def _check_win_rate_anomaly(self, wallet: WalletProfile) -> float:
        """
        Unusually high win rates may indicate informed trading
        """
        if wallet.win_rate is None:
            return 0
            
        # Need enough resolved markets to be meaningful
        if wallet.total_trades < 10:
            return 0
            
        if wallet.win_rate >= settings.win_rate_suspicious_threshold:
            wallet.has_unusual_win_rate = True
            return 25
        elif wallet.win_rate >= 0.75:
            return 10
            
        return 0
    
    def _check_timing(self, trade: Trade, market_data: Dict) -> float:
        """
        Trades placed very close to resolution are suspicious
        Especially at extreme odds
        """
        end_date = market_data.get("endDate")
        if not end_date:
            return 0
            
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            
        hours_to_end = (end_date - trade.timestamp).total_seconds() / 3600
        
        # Trade within 24h of resolution at extreme odds
        if hours_to_end < 24 and trade.price < 20:
            return 25
        elif hours_to_end < 48:
            return 10
            
        return 0
    
    def _check_extreme_odds(self, trade: Trade) -> float:
        """
        Betting on low probability outcomes is high risk/reward
        Insiders often bet on "unlikely" outcomes they know will happen
        """
        if trade.price <= 10:  # 10% or less implied probability
            return 30
        elif trade.price <= 20:
            return 20
        elif trade.price <= 30:
            return 10
        return 0
    
    # ==================== ADVANCED DETECTION ====================
    
    def detect_wallet_clusters(
        self,
        trades: List[Dict],
        time_window_minutes: int = 30
    ) -> List[WalletCluster]:
        """
        Detect coordinated trading by finding wallets that trade
        the same markets within tight time windows
        
        This is forensic network analysis for insider rings
        """
        clusters = []
        
        # Group trades by market
        market_trades: Dict[str, List[Dict]] = defaultdict(list)
        for trade in trades:
            market_id = trade.get("market")
            if market_id:
                market_trades[market_id].append(trade)
        
        # For each market, find time-clustered wallets
        for market_id, market_trade_list in market_trades.items():
            # Sort by time
            sorted_trades = sorted(
                market_trade_list,
                key=lambda x: x.get("timestamp", "")
            )
            
            # Find clusters within time window
            current_cluster = []
            cluster_start = None
            
            for trade in sorted_trades:
                trade_time = trade.get("timestamp")
                if isinstance(trade_time, str):
                    trade_time = datetime.fromisoformat(trade_time.replace("Z", "+00:00"))
                
                if not cluster_start:
                    cluster_start = trade_time
                    current_cluster = [trade]
                elif (trade_time - cluster_start).total_seconds() / 60 <= time_window_minutes:
                    current_cluster.append(trade)
                else:
                    # Check if current cluster is suspicious
                    if len(current_cluster) >= 3:
                        wallets = list(set(t.get("maker") for t in current_cluster if t.get("maker")))
                        if len(wallets) >= 3:
                            total_vol = sum(
                                float(t.get("size", 0)) * float(t.get("price", 0)) / 100 
                                for t in current_cluster
                            )
                            clusters.append(WalletCluster(
                                cluster_id=f"{market_id}_{cluster_start.isoformat()}",
                                wallets=wallets,
                                correlation_score=self._calculate_correlation(current_cluster),
                                shared_markets=[market_id],
                                total_volume=total_vol,
                                first_coordinated_trade=cluster_start
                            ))
                    
                    # Start new cluster
                    cluster_start = trade_time
                    current_cluster = [trade]
        
        return [c for c in clusters if c.is_suspicious]
    
    def detect_information_cascade(
        self,
        market_id: str,
        trades: List[Dict]
    ) -> Optional[Dict]:
        """
        Detect "information cascade" pattern:
        1. First mover (potential insider) places bet
        2. Price moves
        3. Other informed traders pile in
        4. Eventually resolves in favor of early bettors
        
        Returns analysis if pattern detected
        """
        if len(trades) < 5:
            return None
            
        # Sort by time
        sorted_trades = sorted(trades, key=lambda x: x.get("timestamp", ""))
        
        # Identify the "spark" - first significant trade
        spark_trade = None
        for trade in sorted_trades[:5]:
            notional = float(trade.get("size", 0)) * float(trade.get("price", 0)) / 100
            if notional >= settings.min_notional_alert:
                spark_trade = trade
                break
        
        if not spark_trade:
            return None
            
        spark_side = spark_trade.get("side")
        spark_time = spark_trade.get("timestamp")
        
        # Count how many followed in same direction
        followers = 0
        follower_volume = 0
        
        for trade in sorted_trades:
            if trade == spark_trade:
                continue
            if trade.get("side") == spark_side:
                followers += 1
                follower_volume += float(trade.get("size", 0)) * float(trade.get("price", 0)) / 100
        
        follow_ratio = followers / len(sorted_trades) if sorted_trades else 0
        
        if follow_ratio >= 0.7 and followers >= 5:
            return {
                "type": "information_cascade",
                "spark_trade": spark_trade,
                "spark_wallet": spark_trade.get("maker"),
                "followers": followers,
                "follow_ratio": follow_ratio,
                "follower_volume": follower_volume,
                "direction": spark_side
            }
            
        return None
    
    # ==================== HELPERS ====================
    
    def _build_wallet_profile(self, data: Dict) -> WalletProfile:
        """Convert raw wallet data to WalletProfile model"""
        return WalletProfile(
            address=data.get("address", ""),
            display_name=data.get("display_name"),
            total_trades=data.get("total_trades", 0),
            unique_markets=data.get("unique_markets", 0),
            total_volume_usd=data.get("total_volume_usd", 0),
            win_rate=data.get("win_rate"),
            first_seen=data.get("first_seen"),
            last_active=data.get("last_active")
        )
    
    def _build_trade(self, trade_data: Dict, market_data: Dict) -> Trade:
        """Convert raw trade data to Trade model"""
        timestamp = trade_data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        elif not timestamp:
            timestamp = datetime.utcnow()
            
        shares = float(trade_data.get("size", 0))
        price = float(trade_data.get("price", 0))
        
        return Trade(
            id=trade_data.get("id", ""),
            market_id=trade_data.get("market", ""),
            market_slug=market_data.get("slug", ""),
            market_question=market_data.get("question", ""),
            trader_address=trade_data.get("maker", ""),
            side=trade_data.get("side", "BUY"),
            outcome=trade_data.get("outcome", ""),
            shares=shares,
            price=price,
            notional_usd=shares * price / 100,
            timestamp=timestamp,
            market_volume_24h=market_data.get("volume24hr"),
            market_liquidity=market_data.get("liquidity")
        )
    
    def _get_size_context(self, trade: Trade, wallet: WalletProfile) -> str:
        """Get human readable context for trade size"""
        if wallet.total_trades > 0 and wallet.total_volume_usd > 0:
            avg = wallet.total_volume_usd / wallet.total_trades
            multiple = trade.notional_usd / avg if avg > 0 else 0
            if multiple > 1:
                return f"{multiple:.1f}x their average"
        return "whale-sized bet"
    
    def _calculate_potential_profit(self, trade: Trade) -> float:
        """Calculate potential profit if the bet wins"""
        if trade.price <= 0:
            return 0
        # If price is 10¢, buying YES means 90¢ profit per share if it resolves YES
        return trade.shares * (100 - trade.price) / 100
    
    def _calculate_correlation(self, trades: List[Dict]) -> float:
        """
        Calculate how correlated a set of trades are
        Higher = more synchronized (suspicious)
        """
        if len(trades) < 2:
            return 0
            
        # Factors: same direction, similar timing, similar size
        sides = [t.get("side") for t in trades]
        same_side_ratio = max(sides.count("BUY"), sides.count("SELL")) / len(sides)
        
        # Time spread (lower = more correlated)
        times = []
        for t in trades:
            ts = t.get("timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts:
                times.append(ts.timestamp())
        
        time_spread = (max(times) - min(times)) / 60 if times else 999  # in minutes
        time_score = 1 - min(time_spread / 60, 1)  # 0-1, higher if within 1 hour
        
        return (same_side_ratio + time_score) / 2


# Singleton instance
detector = InsiderDetector()

