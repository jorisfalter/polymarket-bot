"""
Trade Tracker Module

Tracks positions with entry/target prices and monitors for auto-sell triggers.
Supports price fetching from Polymarket CLOB API.
"""
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import httpx
from loguru import logger

# Import auto_seller lazily to avoid circular imports
_auto_seller = None

def get_auto_seller():
    """Lazy load auto_seller to avoid circular imports."""
    global _auto_seller
    if _auto_seller is None:
        from .auto_seller import auto_seller
        _auto_seller = auto_seller
    return _auto_seller


@dataclass
class TrackedTrade:
    """A trade position being tracked for auto-sell."""
    id: str
    market_slug: str
    market_question: str
    token_id: str
    condition_id: str
    side: str  # "YES" or "NO"
    entry_price: float  # cents (e.g., 4.0 for 4 cents)
    target_price: float  # cents (e.g., 4.5 for 4.5 cents)
    shares: float
    current_price: float = 0.0
    status: str = "monitoring"  # monitoring, target_hit, sold, stopped
    created_at: str = ""
    updated_at: str = ""
    auto_sell: bool = True
    notes: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    @property
    def pnl_cents(self) -> float:
        """Unrealized P&L in cents per share."""
        return self.current_price - self.entry_price

    @property
    def pnl_pct(self) -> float:
        """Unrealized P&L as percentage."""
        if self.entry_price <= 0:
            return 0.0
        return ((self.current_price - self.entry_price) / self.entry_price) * 100

    @property
    def pnl_usd(self) -> float:
        """Unrealized P&L in USD."""
        return (self.pnl_cents / 100) * self.shares

    @property
    def position_value_usd(self) -> float:
        """Current position value in USD."""
        return (self.current_price / 100) * self.shares

    @property
    def entry_value_usd(self) -> float:
        """Entry position value in USD."""
        return (self.entry_price / 100) * self.shares

    @property
    def progress_pct(self) -> float:
        """Progress from entry to target as percentage (0-100+)."""
        if self.target_price <= self.entry_price:
            return 100.0 if self.current_price >= self.target_price else 0.0

        total_distance = self.target_price - self.entry_price
        current_progress = self.current_price - self.entry_price
        return (current_progress / total_distance) * 100

    @property
    def target_hit(self) -> bool:
        """Check if current price has hit or exceeded target."""
        return self.current_price >= self.target_price

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with computed properties."""
        data = asdict(self)
        data.update({
            "pnl_cents": self.pnl_cents,
            "pnl_pct": round(self.pnl_pct, 2),
            "pnl_usd": round(self.pnl_usd, 2),
            "position_value_usd": round(self.position_value_usd, 2),
            "entry_value_usd": round(self.entry_value_usd, 2),
            "progress_pct": round(self.progress_pct, 2),
            "target_hit": self.target_hit,
        })
        return data


class TradeTracker:
    """
    Manages tracked trades with persistence and price updates.
    """

    CLOB_URL = "https://clob.polymarket.com"
    GAMMA_URL = "https://gamma-api.polymarket.com"

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.trades_file = self.data_dir / "tracked_trades.json"
        self.trades: Dict[str, TrackedTrade] = {}
        self._load()

    def _load(self):
        """Load trades from JSON file."""
        if self.trades_file.exists():
            try:
                with open(self.trades_file, "r") as f:
                    data = json.load(f)
                    for trade_data in data:
                        trade = TrackedTrade(**trade_data)
                        self.trades[trade.id] = trade
                logger.info(f"Loaded {len(self.trades)} tracked trades")
            except Exception as e:
                logger.error(f"Error loading trades: {e}")

    def _save(self):
        """Save trades to JSON file."""
        try:
            with open(self.trades_file, "w") as f:
                data = [asdict(t) for t in self.trades.values()]
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving trades: {e}")

    def add_trade(
        self,
        market_slug: str,
        token_id: str,
        condition_id: str,
        side: str,
        entry_price: float,
        target_price: float,
        shares: float,
        market_question: str = "",
        auto_sell: bool = True,
        notes: str = "",
    ) -> TrackedTrade:
        """Add a new trade to track."""
        trade = TrackedTrade(
            id=str(uuid.uuid4())[:8],
            market_slug=market_slug,
            market_question=market_question,
            token_id=token_id,
            condition_id=condition_id,
            side=side.upper(),
            entry_price=entry_price,
            target_price=target_price,
            shares=shares,
            current_price=entry_price,
            auto_sell=auto_sell,
            notes=notes,
        )
        self.trades[trade.id] = trade
        self._save()
        logger.info(f"Added trade {trade.id}: {market_question[:50]}...")
        return trade

    def get_trade(self, trade_id: str) -> Optional[TrackedTrade]:
        """Get a trade by ID."""
        return self.trades.get(trade_id)

    def get_all_trades(self) -> List[TrackedTrade]:
        """Get all tracked trades."""
        return list(self.trades.values())

    def get_active_trades(self) -> List[TrackedTrade]:
        """Get trades that are still being monitored."""
        return [t for t in self.trades.values() if t.status == "monitoring"]

    def update_trade(self, trade_id: str, **kwargs) -> Optional[TrackedTrade]:
        """Update trade fields."""
        trade = self.trades.get(trade_id)
        if not trade:
            return None

        for key, value in kwargs.items():
            if hasattr(trade, key):
                setattr(trade, key, value)

        trade.updated_at = datetime.utcnow().isoformat()
        self._save()
        return trade

    def delete_trade(self, trade_id: str) -> bool:
        """Remove a trade from tracking."""
        if trade_id in self.trades:
            del self.trades[trade_id]
            self._save()
            logger.info(f"Deleted trade {trade_id}")
            return True
        return False

    async def fetch_price(self, token_id: str, side: str = "sell") -> Optional[float]:
        """
        Fetch current price for a token from CLOB API.
        Returns price in cents (0-100).
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try the price endpoint
                response = await client.get(
                    f"{self.CLOB_URL}/price",
                    params={"token_id": token_id, "side": side}
                )
                if response.status_code == 200:
                    data = response.json()
                    price = float(data.get("price", 0))
                    # Price is 0-1, convert to cents
                    return price * 100

                # Fallback: try midpoint from order book
                response = await client.get(
                    f"{self.CLOB_URL}/book",
                    params={"token_id": token_id}
                )
                if response.status_code == 200:
                    book = response.json()
                    bids = book.get("bids", [])
                    asks = book.get("asks", [])

                    best_bid = float(bids[0]["price"]) if bids else 0
                    best_ask = float(asks[0]["price"]) if asks else 0

                    if best_bid > 0 and best_ask > 0:
                        midpoint = (best_bid + best_ask) / 2
                        return midpoint * 100
                    elif best_bid > 0:
                        return best_bid * 100
                    elif best_ask > 0:
                        return best_ask * 100

        except Exception as e:
            logger.error(f"Error fetching price for {token_id}: {e}")

        return None

    async def update_prices(self):
        """Update current prices for all active trades."""
        active_trades = self.get_active_trades()
        if not active_trades:
            return

        logger.info(f"Updating prices for {len(active_trades)} active trades")

        for trade in active_trades:
            price = await self.fetch_price(trade.token_id)
            if price is not None:
                old_price = trade.current_price
                trade.current_price = price
                trade.updated_at = datetime.utcnow().isoformat()

                # Check for target hit
                if trade.target_hit and trade.status == "monitoring":
                    trade.status = "target_hit"
                    logger.info(
                        f"TARGET HIT for trade {trade.id}: "
                        f"{trade.current_price:.2f}c >= {trade.target_price:.2f}c"
                    )

                if abs(old_price - price) > 0.01:
                    logger.debug(
                        f"Trade {trade.id}: {old_price:.2f}c -> {price:.2f}c "
                        f"(target: {trade.target_price:.2f}c)"
                    )

        self._save()

    async def check_targets(self) -> List[TrackedTrade]:
        """
        Check all trades for target hits.
        If auto_sell is enabled, automatically execute the sell.
        Returns list of trades that hit their target this check.
        """
        await self.update_prices()

        newly_hit = []
        for trade in self.trades.values():
            if trade.status == "target_hit" and trade.auto_sell:
                newly_hit.append(trade)
                # Try to auto-sell
                await self.execute_auto_sell(trade)

        return newly_hit

    async def execute_auto_sell(self, trade: TrackedTrade) -> bool:
        """
        Execute auto-sell for a trade that hit its target.
        Returns True if successful.
        """
        seller = get_auto_seller()
        if not seller.is_ready():
            logger.warning(f"Auto-seller not ready for trade {trade.id}")
            return False

        logger.info(f"🎯 Auto-selling trade {trade.id}: {trade.shares} shares at ~{trade.current_price:.2f}¢")

        # Execute the sell with a minimum price slightly below target
        # to ensure execution (allow 5% slippage)
        min_price = (trade.target_price * 0.95) / 100  # Convert cents to 0-1 scale

        result = await seller.execute_sell(
            trade_id=trade.id,
            token_id=trade.token_id,
            shares=trade.shares,
            min_price=min_price,
        )

        if result.success:
            trade.status = "sold"
            trade.updated_at = datetime.utcnow().isoformat()
            trade.notes = f"{trade.notes} | Auto-sold at {result.price*100:.2f}¢ (Order: {result.order_id})"
            self._save()
            logger.info(f"✅ Auto-sell successful for trade {trade.id}")
            return True
        else:
            logger.error(f"❌ Auto-sell failed for trade {trade.id}: {result.error}")
            # Don't change status - will retry on next check
            return False

    async def lookup_market(self, slug: str) -> Optional[Dict[str, Any]]:
        """
        Look up market details by slug to get token IDs.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.GAMMA_URL}/markets",
                    params={"slug": slug}
                )
                if response.status_code == 200:
                    markets = response.json()
                    if markets:
                        return markets[0]
        except Exception as e:
            logger.error(f"Error looking up market {slug}: {e}")
        return None

    async def search_markets(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for markets by query string."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.GAMMA_URL}/markets",
                    params={"_q": query, "_limit": limit, "active": "true"}
                )
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.error(f"Error searching markets: {e}")
        return []

    def get_stats(self) -> Dict[str, Any]:
        """Get summary statistics for all trades."""
        all_trades = list(self.trades.values())
        active = [t for t in all_trades if t.status == "monitoring"]
        hit = [t for t in all_trades if t.status == "target_hit"]
        sold = [t for t in all_trades if t.status == "sold"]

        total_invested = sum(t.entry_value_usd for t in all_trades)
        total_current = sum(t.position_value_usd for t in all_trades)
        total_pnl = sum(t.pnl_usd for t in all_trades)

        return {
            "total_trades": len(all_trades),
            "active_trades": len(active),
            "targets_hit": len(hit),
            "sold_trades": len(sold),
            "total_invested_usd": round(total_invested, 2),
            "total_current_usd": round(total_current, 2),
            "total_pnl_usd": round(total_pnl, 2),
            "total_pnl_pct": round((total_pnl / total_invested * 100) if total_invested > 0 else 0, 2),
        }


# Singleton instance
trade_tracker = TradeTracker()
