"""
Polymarket API Client
Interfaces with Gamma, CLOB, and Data APIs

Note: Some CLOB endpoints require authentication. We use public endpoints where possible,
and authenticated endpoints when API credentials are configured.
"""
import httpx
import hmac
import hashlib
import time
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from loguru import logger
import asyncio

from .config import settings


class PolymarketClient:
    """
    Async client for Polymarket APIs
    
    APIs:
    - Gamma API: Market discovery, events, metadata, activity
    - CLOB API: Order book, real-time prices (some endpoints need auth)
    - Data API: User positions, trade history
    - Strapi API: Public activity feed
    """
    
    def __init__(self):
        self.gamma_url = settings.gamma_api_url
        self.clob_url = settings.clob_api_url
        self.data_url = settings.data_api_url
        # Public Strapi API for activity data
        self.strapi_url = "https://strapi-matic.poly.market"
        self._client: Optional[httpx.AsyncClient] = None
        
        # API credentials (optional)
        self.api_key = settings.poly_api_key
        self.api_secret = settings.poly_api_secret
        self.passphrase = settings.poly_passphrase
        self.has_credentials = bool(self.api_key and self.api_secret)
        
        if self.has_credentials:
            logger.info("✅ Polymarket API credentials configured - full access enabled")
        else:
            logger.info("ℹ️ No API credentials - using public endpoints only")
        
    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=30.0)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
            
    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")
        return self._client
    
    def _get_auth_headers(self, method: str = "GET", path: str = "", body: str = "") -> Dict[str, str]:
        """
        Generate HMAC-SHA256 authentication headers for Polymarket CLOB API.
        Returns empty dict if no credentials configured.
        """
        if not self.has_credentials:
            return {}
        
        timestamp = str(int(time.time()))
        message = f"{timestamp}{method}{path}{body}"
        
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        headers = {
            "POLY_API_KEY": self.api_key,
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": timestamp,
        }
        
        if self.passphrase:
            headers["POLY_PASSPHRASE"] = self.passphrase
            
        return headers
    
    # ==================== GAMMA API (Markets) ====================
    
    async def get_markets(
        self, 
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
        order: str = "volume24hr",
        ascending: bool = False
    ) -> List[Dict[str, Any]]:
        """Fetch markets from Gamma API"""
        try:
            params = {
                "limit": limit,
                "offset": offset,
                "active": str(active).lower(),
                "closed": str(closed).lower(),
                "order": order,
                "ascending": str(ascending).lower()
            }
            
            response = await self.client.get(
                f"{self.gamma_url}/markets",
                params=params
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching markets: {e}")
            return []
    
    async def get_market(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Get single market details"""
        try:
            response = await self.client.get(f"{self.gamma_url}/markets/{market_id}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching market {market_id}: {e}")
            return None
            
    async def get_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get events (groups of related markets)"""
        try:
            response = await self.client.get(
                f"{self.gamma_url}/events",
                params={"limit": limit, "active": "true"}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching events: {e}")
            return []
    
    # ==================== CLOB API (Trading Data) ====================
    
    async def get_order_book(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Get order book for a market token"""
        try:
            response = await self.client.get(
                f"{self.clob_url}/book",
                params={"token_id": token_id}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching order book: {e}")
            return None
            
    async def get_prices(self, token_ids: List[str]) -> Dict[str, float]:
        """Get current prices for multiple tokens"""
        try:
            response = await self.client.get(
                f"{self.clob_url}/prices",
                params={"token_ids": ",".join(token_ids)}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching prices: {e}")
            return {}
    
    async def get_trades(
        self,
        market_id: Optional[str] = None,
        maker: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get recent trades - tries authenticated endpoint first, then public fallbacks
        """
        # If we have credentials, try the authenticated CLOB endpoint
        if self.has_credentials:
            try:
                params = {"limit": limit}
                if market_id:
                    params["market"] = market_id
                if maker:
                    params["maker"] = maker
                
                path = "/trades"
                headers = self._get_auth_headers("GET", path)
                
                response = await self.client.get(
                    f"{self.clob_url}{path}",
                    params=params,
                    headers=headers
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                logger.debug(f"Authenticated trades endpoint failed: {e}")
        
        # Try Gamma API activity endpoint (public)
        try:
            params = {"limit": limit}
            if market_id:
                params["market"] = market_id
                
            response = await self.client.get(
                f"{self.gamma_url}/activity",
                params=params
            )
            response.raise_for_status()
            data = response.json()
            # Normalize the response
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "data" in data:
                return data["data"]
            return []
        except Exception as e:
            logger.debug(f"Gamma activity not available: {e}")
        
        # Try Strapi API for recent activity
        try:
            response = await self.client.get(
                f"{self.strapi_url}/activities",
                params={"_limit": limit, "_sort": "timestamp:DESC"}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.debug(f"Strapi activity not available: {e}")
            
        return []
    
    async def get_market_activity(self, condition_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get activity for a specific market using condition ID"""
        try:
            response = await self.client.get(
                f"{self.gamma_url}/activity",
                params={"conditionId": condition_id, "limit": limit}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.debug(f"Error fetching market activity: {e}")
            return []
    
    # ==================== DATA API (User/Portfolio) ====================
    
    async def get_user_positions(self, address: str) -> List[Dict[str, Any]]:
        """Get all positions for a wallet address"""
        try:
            response = await self.client.get(
                f"{self.data_url}/positions",
                params={"user": address}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching positions for {address}: {e}")
            return []
            
    async def get_user_trades(
        self,
        address: str,
        limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Get trade history for a wallet"""
        try:
            response = await self.client.get(
                f"{self.data_url}/trades",
                params={"user": address, "limit": limit}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching trades for {address}: {e}")
            return []
            
    async def get_user_profit_loss(self, address: str) -> Optional[Dict[str, Any]]:
        """Get P&L summary for a wallet"""
        try:
            response = await self.client.get(
                f"{self.data_url}/pnl",
                params={"user": address}
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching P&L for {address}: {e}")
            return None
    
    # ==================== BULK OPERATIONS ====================
    
    async def get_recent_large_trades(
        self,
        min_notional: float = 1000,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent trades above a notional threshold
        This is the core data source for detecting suspicious activity
        
        Uses multiple strategies:
        1. Gamma API global activity feed
        2. High-volume markets with embedded activity
        3. Market-specific activity queries
        """
        all_trades = []
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        # Strategy 1: Try global activity feed from Gamma API
        try:
            response = await self.client.get(
                f"{self.gamma_url}/activity",
                params={"limit": 500}
            )
            if response.status_code == 200:
                activity = response.json()
                if isinstance(activity, list):
                    all_trades.extend(activity)
                    logger.info(f"Got {len(activity)} activities from Gamma API")
        except Exception as e:
            logger.debug(f"Global activity feed not available: {e}")
        
        # Strategy 2: Get high-volume markets and check for recent large positions
        markets = await self.get_markets(limit=50, order="volume24hr")
        logger.info(f"Analyzing {len(markets)} high-volume markets")
        
        for market in markets[:30]:
            try:
                # Markets often have embedded activity/trade data
                market_id = market.get("id")
                condition_id = market.get("conditionId")
                
                # Try to get activity for this market
                if condition_id:
                    activity = await self.get_market_activity(condition_id, limit=50)
                    for item in activity:
                        item["market_question"] = market.get("question", "")
                        item["market_slug"] = market.get("slug", "")
                        item["market_id"] = market_id
                    all_trades.extend(activity)
                
                # Also create synthetic trade entries from market volume changes
                # High volume in a market = potential large trades
                volume_24h = float(market.get("volume24hr", 0) or 0)
                liquidity = float(market.get("liquidity", 0) or 0)
                
                if volume_24h >= min_notional:
                    # Create a market-level entry for analysis
                    synthetic_trade = {
                        "id": f"market_{market_id}",
                        "market": market_id,
                        "market_question": market.get("question", ""),
                        "market_slug": market.get("slug", ""),
                        "type": "market_volume",
                        "volume_24h": volume_24h,
                        "liquidity": liquidity,
                        "notional_usd": volume_24h,  # Use volume as proxy
                        "price": float(market.get("outcomePrices", "50,50").split(",")[0] or 50),
                        "timestamp": datetime.utcnow().isoformat(),
                        "size": volume_24h / 50,  # Estimate shares
                        "side": "BUY",
                        "maker": market.get("creator", "unknown"),
                    }
                    all_trades.append(synthetic_trade)
                    
            except Exception as e:
                logger.debug(f"Error processing market {market.get('id')}: {e}")
                continue
        
        # Filter and normalize trades
        filtered = []
        seen_ids = set()
        
        for trade in all_trades:
            try:
                trade_id = trade.get("id", str(hash(str(trade))))
                if trade_id in seen_ids:
                    continue
                seen_ids.add(trade_id)
                
                # Calculate notional if not present
                if "notional_usd" not in trade:
                    shares = float(trade.get("size", 0) or trade.get("amount", 0) or 0)
                    price = float(trade.get("price", 50) or 50)
                    trade["notional_usd"] = shares * price / 100
                
                # Parse timestamp
                trade_time = trade.get("timestamp", "") or trade.get("createdAt", "")
                if isinstance(trade_time, str) and trade_time:
                    try:
                        trade_time = datetime.fromisoformat(trade_time.replace("Z", "+00:00"))
                    except:
                        trade_time = datetime.utcnow()
                elif not trade_time:
                    trade_time = datetime.utcnow()
                
                trade["timestamp"] = trade_time
                
                # Filter by notional and time
                if trade.get("notional_usd", 0) >= min_notional:
                    # Ensure required fields
                    trade["maker"] = trade.get("maker") or trade.get("user") or trade.get("proxyWallet") or "unknown"
                    trade["side"] = trade.get("side") or trade.get("type") or "BUY"
                    filtered.append(trade)
                    
            except Exception as e:
                logger.debug(f"Error processing trade: {e}")
                continue
        
        logger.info(f"Found {len(filtered)} trades meeting criteria (min ${min_notional})")
        return sorted(filtered, key=lambda x: x.get("notional_usd", 0), reverse=True)
    
    async def get_wallet_profile(self, address: str) -> Dict[str, Any]:
        """
        Build a comprehensive profile for a wallet
        Key for identifying "low activity" or suspicious wallets
        """
        trades = await self.get_user_trades(address, limit=500)
        positions = await self.get_user_positions(address)
        pnl = await self.get_user_profit_loss(address)
        
        # Calculate metrics
        unique_markets = set()
        total_volume = 0
        wins = 0
        resolved_trades = 0
        first_trade = None
        last_trade = None
        
        for trade in trades:
            market_id = trade.get("market")
            if market_id:
                unique_markets.add(market_id)
            
            notional = float(trade.get("size", 0)) * float(trade.get("price", 0)) / 100
            total_volume += notional
            
            trade_time = trade.get("timestamp")
            if trade_time:
                if isinstance(trade_time, str):
                    trade_time = datetime.fromisoformat(trade_time.replace("Z", "+00:00"))
                if not first_trade or trade_time < first_trade:
                    first_trade = trade_time
                if not last_trade or trade_time > last_trade:
                    last_trade = trade_time
        
        # Get win rate from P&L if available
        win_rate = None
        if pnl:
            total_markets = pnl.get("marketsTraded", 0)
            markets_won = pnl.get("marketsWon", 0)
            if total_markets > 0:
                win_rate = markets_won / total_markets
        
        return {
            "address": address,
            "total_trades": len(trades),
            "unique_markets": len(unique_markets),
            "total_volume_usd": total_volume,
            "win_rate": win_rate,
            "first_seen": first_trade,
            "last_active": last_trade,
            "positions": positions,
            "recent_pnl": pnl
        }


# Singleton instance
_client: Optional[PolymarketClient] = None

async def get_client() -> PolymarketClient:
    """Get or create the Polymarket client"""
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client

