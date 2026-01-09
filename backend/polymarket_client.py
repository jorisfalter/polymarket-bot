"""
Polymarket API Client
Interfaces with Gamma, CLOB, and Data APIs
"""
import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from loguru import logger
import asyncio

from .config import settings


class PolymarketClient:
    """
    Async client for Polymarket APIs
    
    APIs:
    - Gamma API: Market discovery, events, metadata
    - CLOB API: Order book, real-time prices, trades
    - Data API: User positions, trade history
    """
    
    def __init__(self):
        self.gamma_url = settings.gamma_api_url
        self.clob_url = settings.clob_api_url
        self.data_url = settings.data_api_url
        self._client: Optional[httpx.AsyncClient] = None
        
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
        Get recent trades
        Can filter by market or maker address
        """
        try:
            params = {"limit": limit}
            if market_id:
                params["market"] = market_id
            if maker:
                params["maker"] = maker
                
            response = await self.client.get(
                f"{self.clob_url}/trades",
                params=params
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
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
        """
        all_trades = []
        
        # Get trades from multiple high-volume markets
        markets = await self.get_markets(limit=50, order="volume24hr")
        
        async def fetch_market_trades(market: Dict) -> List[Dict]:
            trades = await self.get_trades(market_id=market.get("id"), limit=200)
            # Enrich with market info
            for trade in trades:
                trade["market_question"] = market.get("question", "")
                trade["market_slug"] = market.get("slug", "")
            return trades
        
        # Fetch in parallel
        tasks = [fetch_market_trades(m) for m in markets[:20]]  # Top 20 markets
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_trades.extend(result)
        
        # Filter by notional
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        filtered = []
        
        for trade in all_trades:
            try:
                # Calculate notional (shares * price)
                shares = float(trade.get("size", 0))
                price = float(trade.get("price", 0))
                notional = shares * price / 100  # Price is in cents
                
                trade_time = trade.get("timestamp", "")
                if isinstance(trade_time, str):
                    trade_time = datetime.fromisoformat(trade_time.replace("Z", "+00:00"))
                
                if notional >= min_notional and trade_time >= cutoff:
                    trade["notional_usd"] = notional
                    filtered.append(trade)
            except (ValueError, TypeError) as e:
                continue
                
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

