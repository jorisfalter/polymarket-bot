"""
Paper Trading System

Tracks hypothetical copy-trades without real money.
Records entries, monitors market prices, and calculates P&L when markets resolve.
"""
import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from loguru import logger

from .polymarket_client import PolymarketClient
from .leaderboard import tracker


PAPER_TRADES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "paper_trades.json"
)


class TradeStatus(Enum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"
    EXPIRED = "expired"


@dataclass
class PaperTrade:
    """A simulated trade."""
    id: str
    timestamp: str
    copied_from: str                    # Wallet address we copied
    copied_from_name: str               # Their display name
    market_id: str                      # conditionId
    market_title: str
    market_slug: str
    outcome: str                        # "Yes" or "No" / outcome name
    side: str                           # "BUY" or "SELL"
    entry_price: float                  # Price when we "entered"
    their_entry_price: float            # Price they entered at
    shares: float                       # Number of shares
    position_usd: float                 # USD value at entry
    current_price: float = 0.0          # Current market price
    exit_price: Optional[float] = None  # Price at resolution
    pnl_usd: float = 0.0                # Realized P&L
    pnl_pct: float = 0.0                # Percent return
    status: str = "open"
    resolved_at: Optional[str] = None
    notes: str = ""


class PaperTrader:
    """
    Paper trading system for simulating copy-trades.
    """

    def __init__(self, position_size_usd: float = 100.0):
        self.position_size = position_size_usd
        self.trades: List[PaperTrade] = []
        self._load_trades()

    def _load_trades(self):
        """Load trades from disk."""
        try:
            if os.path.exists(PAPER_TRADES_PATH):
                with open(PAPER_TRADES_PATH, "r") as f:
                    data = json.load(f)
                self.trades = [PaperTrade(**t) for t in data.get("trades", [])]
                logger.info(f"Loaded {len(self.trades)} paper trades")
        except Exception as e:
            logger.error(f"Error loading paper trades: {e}")

    def _save_trades(self):
        """Persist trades to disk."""
        try:
            os.makedirs(os.path.dirname(PAPER_TRADES_PATH), exist_ok=True)
            with open(PAPER_TRADES_PATH, "w") as f:
                json.dump(
                    {"trades": [asdict(t) for t in self.trades]},
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Error saving paper trades: {e}")

    async def record_copy_trade(
        self,
        copied_from: str,
        copied_from_name: str,
        market_id: str,
        market_title: str,
        market_slug: str,
        outcome: str,
        side: str,
        their_entry_price: float,
        our_entry_price: float,
    ) -> PaperTrade:
        """Record a new paper trade."""

        # Calculate shares based on our position size
        shares = self.position_size / our_entry_price if our_entry_price > 0 else 0

        trade = PaperTrade(
            id=f"PT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{len(self.trades)}",
            timestamp=datetime.utcnow().isoformat(),
            copied_from=copied_from,
            copied_from_name=copied_from_name,
            market_id=market_id,
            market_title=market_title,
            market_slug=market_slug,
            outcome=outcome,
            side=side,
            entry_price=our_entry_price,
            their_entry_price=their_entry_price,
            shares=shares,
            position_usd=self.position_size,
            current_price=our_entry_price,
        )

        self.trades.append(trade)
        self._save_trades()

        logger.info(
            f"📝 Paper trade recorded: {market_title[:40]}... "
            f"| {side} {shares:.1f} @ {our_entry_price:.4f}"
        )

        return trade

    async def update_prices(self):
        """Update current prices for all open trades."""
        open_trades = [t for t in self.trades if t.status == "open"]

        if not open_trades:
            return

        logger.info(f"Updating prices for {len(open_trades)} open paper trades...")

        async with PolymarketClient() as client:
            for trade in open_trades:
                try:
                    market = await client.get_market(trade.market_id)
                    if not market:
                        continue

                    # Check if market resolved
                    if market.get("closed") or market.get("resolved"):
                        # Market resolved - calculate final P&L
                        resolution = market.get("resolution") or market.get("outcome")

                        # Determine if we won
                        won = False
                        if resolution:
                            won = (resolution.lower() == trade.outcome.lower())

                        if won:
                            trade.exit_price = 1.0
                            trade.pnl_usd = trade.shares * 1.0 - trade.position_usd
                            trade.status = "won"
                        else:
                            trade.exit_price = 0.0
                            trade.pnl_usd = -trade.position_usd
                            trade.status = "lost"

                        trade.pnl_pct = (trade.pnl_usd / trade.position_usd) * 100
                        trade.resolved_at = datetime.utcnow().isoformat()

                        logger.info(
                            f"📊 Trade resolved: {trade.market_title[:30]}... "
                            f"| {trade.status.upper()} | P&L: ${trade.pnl_usd:+.2f}"
                        )
                    else:
                        # Update current price
                        tokens = market.get("tokens", [])
                        for token in tokens:
                            if token.get("outcome") == trade.outcome:
                                trade.current_price = float(token.get("price") or 0)
                                break

                except Exception as e:
                    logger.error(f"Error updating trade {trade.id}: {e}")

        self._save_trades()

    async def check_and_copy_new_trades(self) -> List[PaperTrade]:
        """
        Check watched traders for new trades and record paper copies.
        Returns list of new paper trades created.
        """
        if not tracker.watched_wallets:
            logger.debug("No watched wallets for paper trading")
            return []

        new_paper_trades = []

        # Track what we've already copied to avoid duplicates
        existing_keys = {
            f"{t.copied_from}:{t.market_id}:{t.outcome}"
            for t in self.trades
        }

        async with PolymarketClient() as client:
            for address in list(tracker.watched_wallets):
                try:
                    # Get trader's display name
                    profile = await client.get_wallet_profile(address)
                    trader_name = profile.get("username") or address[:12] + "..."

                    # Get their recent trades
                    trades = await client.get_user_trades(address, limit=20)

                    for trade in trades:
                        market_id = trade.get("conditionId")
                        outcome = trade.get("outcome") or ""

                        if not market_id:
                            continue

                        # Skip if already copied
                        key = f"{address}:{market_id}:{outcome}"
                        if key in existing_keys:
                            continue

                        title = trade.get("title") or trade.get("question") or ""

                        # Skip sports (optional - can be configured)
                        title_lower = title.lower()
                        is_sports = any(x in title_lower for x in [
                            "vs.", "spread:", "o/u ", "moneyline"
                        ])
                        if is_sports:
                            continue

                        # Skip small trades
                        usdc_size = float(trade.get("usdcSize") or 0)
                        if usdc_size < 50:
                            continue

                        their_price = float(trade.get("price") or 0)
                        if their_price <= 0:
                            continue

                        # Get current market price
                        market = await client.get_market(market_id)
                        current_price = their_price  # Default to their price

                        if market:
                            tokens = market.get("tokens", [])
                            for token in tokens:
                                if token.get("outcome") == outcome:
                                    current_price = float(token.get("price") or their_price)
                                    break

                        # Calculate slippage
                        slippage = abs(current_price - their_price) / their_price * 100 if their_price else 0

                        # Skip if slippage too high
                        if slippage > 10:
                            logger.info(f"Skipping due to slippage ({slippage:.1f}%): {title[:40]}")
                            continue

                        # Record the paper trade
                        paper_trade = await self.record_copy_trade(
                            copied_from=address,
                            copied_from_name=trader_name,
                            market_id=market_id,
                            market_title=title,
                            market_slug=trade.get("slug") or "",
                            outcome=outcome,
                            side=trade.get("side") or "BUY",
                            their_entry_price=their_price,
                            our_entry_price=current_price,
                        )

                        new_paper_trades.append(paper_trade)
                        existing_keys.add(key)

                except Exception as e:
                    logger.error(f"Error checking trader {address[:12]}...: {e}")

        return new_paper_trades

    def get_stats(self) -> Dict[str, Any]:
        """Get paper trading statistics."""
        open_trades = [t for t in self.trades if t.status == "open"]
        won_trades = [t for t in self.trades if t.status == "won"]
        lost_trades = [t for t in self.trades if t.status == "lost"]

        total_pnl = sum(t.pnl_usd for t in self.trades if t.status != "open")
        total_invested = sum(t.position_usd for t in self.trades if t.status != "open")

        # Unrealized P&L for open positions
        unrealized_pnl = sum(
            (t.current_price - t.entry_price) * t.shares
            for t in open_trades
        )

        return {
            "total_trades": len(self.trades),
            "open_trades": len(open_trades),
            "won_trades": len(won_trades),
            "lost_trades": len(lost_trades),
            "win_rate": len(won_trades) / (len(won_trades) + len(lost_trades)) * 100 if (won_trades or lost_trades) else 0,
            "realized_pnl": total_pnl,
            "unrealized_pnl": unrealized_pnl,
            "total_pnl": total_pnl + unrealized_pnl,
            "total_invested": total_invested,
            "roi_pct": (total_pnl / total_invested * 100) if total_invested else 0,
            "position_size": self.position_size,
            "recent_trades": [
                {
                    "id": t.id,
                    "market": t.market_title[:50],
                    "outcome": t.outcome,
                    "copied_from": t.copied_from_name,
                    "entry": t.entry_price,
                    "current": t.current_price,
                    "their_entry": t.their_entry_price,
                    "position_usd": t.position_usd,
                    "pnl_usd": t.pnl_usd,
                    "status": t.status,
                    "timestamp": t.timestamp,
                }
                for t in sorted(self.trades, key=lambda x: x.timestamp, reverse=True)[:20]
            ],
        }

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions with current values."""
        return [
            {
                "id": t.id,
                "market": t.market_title,
                "market_slug": t.market_slug,
                "outcome": t.outcome,
                "copied_from": t.copied_from_name,
                "entry_price": t.entry_price,
                "their_entry": t.their_entry_price,
                "current_price": t.current_price,
                "shares": t.shares,
                "position_usd": t.position_usd,
                "unrealized_pnl": (t.current_price - t.entry_price) * t.shares,
                "timestamp": t.timestamp,
            }
            for t in self.trades
            if t.status == "open"
        ]


# Singleton
paper_trader = PaperTrader(position_size_usd=100.0)
