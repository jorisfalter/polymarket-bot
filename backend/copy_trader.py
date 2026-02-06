"""
Automated Copy-Trading Module

Monitors watched traders and automatically mirrors their trades
with configurable slippage protection and position sizing.
"""
import asyncio
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger

from .polymarket_client import PolymarketClient
from .leaderboard import tracker


class CopyMode(Enum):
    """Copy trading modes."""
    MIRROR = "mirror"      # Copy exact position size
    FIXED = "fixed"        # Fixed USD amount per trade
    SCALED = "scaled"      # Scale based on their position as % of portfolio


@dataclass
class CopyTradeConfig:
    """Configuration for copy trading."""
    enabled: bool = False
    mode: CopyMode = CopyMode.FIXED
    fixed_amount_usd: float = 100.0          # For FIXED mode
    scale_factor: float = 0.1                # For SCALED mode (10% of their size)
    max_position_usd: float = 500.0          # Max single position
    max_slippage_pct: float = 5.0            # Max price difference from their entry
    min_trade_size_usd: float = 10.0         # Minimum trade to copy
    excluded_categories: List[str] = field(default_factory=lambda: ["sports"])
    poll_interval_seconds: int = 30          # How often to check for new trades
    dry_run: bool = True                     # Log trades but don't execute


@dataclass
class CopyTradeResult:
    """Result of a copy trade attempt."""
    success: bool
    original_trader: str
    market: str
    side: str
    original_price: float
    our_price: Optional[float] = None
    original_size_usd: float = 0
    our_size_usd: float = 0
    slippage_pct: float = 0
    error: Optional[str] = None
    dry_run: bool = True
    timestamp: str = ""


class CopyTrader:
    """
    Automated copy-trading system.

    Monitors watched traders from the leaderboard and automatically
    mirrors their trades with configurable parameters.
    """

    def __init__(self, config: Optional[CopyTradeConfig] = None):
        self.config = config or CopyTradeConfig()
        self._last_seen_trades: Dict[str, str] = {}  # trader -> last trade timestamp
        self._pending_copies: List[Dict] = []
        self._executed_copies: List[CopyTradeResult] = []
        self._running = False

    async def check_for_new_trades(self) -> List[Dict[str, Any]]:
        """
        Check watched traders for new trades.
        Returns list of trades that should be copied.
        """
        if not tracker.watched_wallets:
            return []

        new_trades = []

        async with PolymarketClient() as client:
            for address in list(tracker.watched_wallets):
                try:
                    trades = await client.get_user_trades(address, limit=10)
                    if not trades:
                        continue

                    last_seen = self._last_seen_trades.get(address)
                    latest_ts = None

                    for trade in trades:
                        ts = trade.get("timestamp") or trade.get("createdAt") or ""
                        if isinstance(ts, int):
                            ts = str(ts)

                        if last_seen and ts <= last_seen:
                            break

                        if not latest_ts or ts > latest_ts:
                            latest_ts = ts

                        # Extract trade details
                        title = trade.get("title") or trade.get("question") or ""
                        usdc_size = float(trade.get("usdcSize") or 0)
                        if not usdc_size:
                            size = float(trade.get("size") or 0)
                            price = float(trade.get("price") or 0)
                            usdc_size = size * price

                        # Check if trade meets our criteria
                        if usdc_size < self.config.min_trade_size_usd:
                            logger.debug(f"Skipping small trade: ${usdc_size:.2f}")
                            continue

                        # Check for excluded categories
                        title_lower = title.lower()
                        is_excluded = any(
                            cat in title_lower
                            for cat in ["vs.", "spread:", "o/u ", "moneyline"]  # Sports indicators
                        )
                        if is_excluded and "sports" in self.config.excluded_categories:
                            logger.debug(f"Skipping sports trade: {title[:50]}")
                            continue

                        new_trade = {
                            "trader": address,
                            "market": trade.get("conditionId") or trade.get("market"),
                            "market_title": title,
                            "slug": trade.get("slug") or "",
                            "side": trade.get("side") or "BUY",
                            "outcome": trade.get("outcome") or "",
                            "price": float(trade.get("price") or 0),
                            "size": float(trade.get("size") or 0),
                            "usdc_size": usdc_size,
                            "timestamp": ts,
                            "asset": trade.get("asset"),
                        }
                        new_trades.append(new_trade)
                        logger.info(f"📡 Detected trade from {address[:12]}...: {title[:40]}...")

                    if latest_ts:
                        self._last_seen_trades[address] = latest_ts

                except Exception as e:
                    logger.error(f"Error checking trader {address[:12]}...: {e}")

        return new_trades

    async def evaluate_copy(self, trade: Dict[str, Any]) -> Optional[CopyTradeResult]:
        """
        Evaluate whether to copy a trade and at what parameters.
        Returns CopyTradeResult if we should copy, None otherwise.
        """
        result = CopyTradeResult(
            success=False,
            original_trader=trade["trader"],
            market=trade["market_title"],
            side=trade["side"],
            original_price=trade["price"],
            original_size_usd=trade["usdc_size"],
            timestamp=datetime.utcnow().isoformat(),
            dry_run=self.config.dry_run,
        )

        try:
            async with PolymarketClient() as client:
                # Get current market price
                market_info = await client.get_market(trade["market"])
                if not market_info:
                    result.error = "Could not fetch market info"
                    return result

                # Determine current price for our side
                # This is simplified - real implementation would check order book
                tokens = market_info.get("tokens", [])
                current_price = None
                for token in tokens:
                    if token.get("outcome") == trade["outcome"]:
                        current_price = float(token.get("price") or 0)
                        break

                if not current_price:
                    # Fallback to their price
                    current_price = trade["price"]

                result.our_price = current_price

                # Calculate slippage
                if trade["price"] > 0:
                    slippage = abs(current_price - trade["price"]) / trade["price"] * 100
                    result.slippage_pct = slippage

                    if slippage > self.config.max_slippage_pct:
                        result.error = f"Slippage too high: {slippage:.1f}% > {self.config.max_slippage_pct}%"
                        return result

                # Calculate our position size
                if self.config.mode == CopyMode.FIXED:
                    our_size = self.config.fixed_amount_usd
                elif self.config.mode == CopyMode.SCALED:
                    our_size = trade["usdc_size"] * self.config.scale_factor
                else:  # MIRROR
                    our_size = trade["usdc_size"]

                # Apply max position limit
                our_size = min(our_size, self.config.max_position_usd)
                result.our_size_usd = our_size

                result.success = True

        except Exception as e:
            result.error = str(e)

        return result

    async def execute_copy(self, trade: Dict[str, Any], evaluation: CopyTradeResult) -> CopyTradeResult:
        """
        Execute the copy trade.
        """
        if self.config.dry_run:
            logger.info(
                f"🧪 DRY RUN - Would copy trade:\n"
                f"   Market: {evaluation.market[:50]}...\n"
                f"   Side: {evaluation.side}\n"
                f"   Their price: {evaluation.original_price:.4f} -> Our price: {evaluation.our_price:.4f}\n"
                f"   Their size: ${evaluation.original_size_usd:.2f} -> Our size: ${evaluation.our_size_usd:.2f}\n"
                f"   Slippage: {evaluation.slippage_pct:.2f}%"
            )
            evaluation.dry_run = True
            self._executed_copies.append(evaluation)
            return evaluation

        # Real execution would go here
        # This requires proper CLOB API integration with order signing
        try:
            async with PolymarketClient() as client:
                # Calculate shares to buy
                shares = evaluation.our_size_usd / evaluation.our_price if evaluation.our_price else 0

                # Place order via CLOB API
                # Note: This is a simplified version - real implementation needs:
                # - Order signing with private key
                # - Proper order book interaction
                # - Limit vs market order logic

                order_result = await client.place_order(
                    market_id=trade["market"],
                    side=trade["side"],
                    price=evaluation.our_price,
                    size=shares,
                    asset_id=trade.get("asset"),
                )

                if order_result and order_result.get("success"):
                    logger.info(f"✅ Executed copy trade: {evaluation.market[:40]}...")
                    evaluation.success = True
                else:
                    evaluation.error = order_result.get("error", "Unknown error")
                    evaluation.success = False

        except Exception as e:
            evaluation.error = str(e)
            evaluation.success = False

        self._executed_copies.append(evaluation)
        return evaluation

    async def run_copy_cycle(self) -> List[CopyTradeResult]:
        """
        Run one cycle of copy trading:
        1. Check for new trades from watched traders
        2. Evaluate each trade
        3. Execute copies that pass evaluation
        """
        results = []

        new_trades = await self.check_for_new_trades()

        for trade in new_trades:
            evaluation = await self.evaluate_copy(trade)
            if evaluation and evaluation.success:
                result = await self.execute_copy(trade, evaluation)
                results.append(result)
            elif evaluation:
                logger.info(f"⏭️ Skipping trade: {evaluation.error}")
                results.append(evaluation)

        return results

    async def start(self):
        """Start the copy trading loop."""
        if not self.config.enabled:
            logger.warning("Copy trading is disabled in config")
            return

        self._running = True
        logger.info(f"🚀 Starting copy trader (dry_run={self.config.dry_run})")
        logger.info(f"   Mode: {self.config.mode.value}")
        logger.info(f"   Poll interval: {self.config.poll_interval_seconds}s")
        logger.info(f"   Max slippage: {self.config.max_slippage_pct}%")
        logger.info(f"   Watching {len(tracker.watched_wallets)} traders")

        while self._running:
            try:
                await self.run_copy_cycle()
            except Exception as e:
                logger.error(f"Copy cycle error: {e}")

            await asyncio.sleep(self.config.poll_interval_seconds)

    def stop(self):
        """Stop the copy trading loop."""
        self._running = False
        logger.info("🛑 Stopping copy trader")

    def get_stats(self) -> Dict[str, Any]:
        """Get copy trading statistics."""
        successful = [c for c in self._executed_copies if c.success]
        failed = [c for c in self._executed_copies if not c.success]

        return {
            "enabled": self.config.enabled,
            "dry_run": self.config.dry_run,
            "mode": self.config.mode.value,
            "watching": len(tracker.watched_wallets),
            "total_copies": len(self._executed_copies),
            "successful": len(successful),
            "failed": len(failed),
            "total_volume_usd": sum(c.our_size_usd for c in successful),
            "avg_slippage_pct": (
                sum(c.slippage_pct for c in successful) / len(successful)
                if successful else 0
            ),
            "recent_copies": [
                {
                    "market": c.market[:50],
                    "side": c.side,
                    "size_usd": c.our_size_usd,
                    "slippage_pct": c.slippage_pct,
                    "success": c.success,
                    "error": c.error,
                    "timestamp": c.timestamp,
                }
                for c in self._executed_copies[-10:]
            ],
        }


# Singleton with default config (disabled, dry run)
copy_trader = CopyTrader()
