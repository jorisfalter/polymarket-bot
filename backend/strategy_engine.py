"""
Strategy Engine — Orchestrates live trading strategies.

Two strategies:
1. Insider Signal Following — piggybacks on the detector pipeline
2. Resolution Arbitrage — buys near-certain outcomes before resolution

All trades go through RiskManager for hard safety limits,
and are logged to TradeJournal for full audit trail.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

from .config import settings
from .models import SuspiciousTrade, AlertSeverity
from .polymarket_client import PolymarketClient
from .auto_seller import auto_seller
from .risk_manager import risk_manager
from .trade_journal import journal
from .notifications import get_notifier, NotificationService


# Sports/crypto keywords — skip these markets
EXCLUDED_KEYWORDS = [
    "nfl", "nba", "mlb", "nhl", "ufc", "pga", "ncaa", "nascar",
    "football", "basketball", "baseball", "hockey", "soccer",
    "super bowl", "world series", "stanley cup", "champions league",
    "premier league", "playoffs", "finals", "f1", "formula 1",
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
    "crypto", "token price", "coin price", "above $", "below $",
    "reach $", "hit $", "price on", "price by", "price of",
]


def _is_excluded_market(question: str, slug: str) -> bool:
    text = f"{question} {slug}".lower()
    return any(kw in text for kw in EXCLUDED_KEYWORDS)


class StrategyEngine:
    """Orchestrates trading strategies with risk management."""

    def __init__(self):
        self._last_arb_scan: Optional[datetime] = None
        self._insider_queue: list[SuspiciousTrade] = []

    async def on_insider_alert(self, suspicious: SuspiciousTrade):
        """Called by main.py when a HIGH/CRITICAL alert is detected."""
        if not settings.strategy_enabled or not settings.strategy_insider_enabled:
            return
        self._insider_queue.append(suspicious)

    async def run_cycle(self):
        """Main cycle — called every 2 minutes by scheduler."""
        if not settings.strategy_enabled:
            return

        # Process insider signals
        if settings.strategy_insider_enabled:
            await self._run_insider_signals()

        # Resolution arbitrage (every 15 minutes)
        if settings.strategy_arbitrage_enabled:
            now = datetime.utcnow()
            if self._last_arb_scan is None or (now - self._last_arb_scan) > timedelta(minutes=15):
                await self._run_resolution_arbitrage()
                self._last_arb_scan = now

    async def _run_insider_signals(self):
        """Process queued insider alerts."""
        while self._insider_queue:
            suspicious = self._insider_queue.pop(0)
            try:
                await self._execute_insider_trade(suspicious)
            except Exception as e:
                logger.error(f"Insider signal error: {e}")

    async def _execute_insider_trade(self, suspicious: SuspiciousTrade):
        """Evaluate and execute a trade based on an insider signal."""
        trade = suspicious.trade
        score = suspicious.suspicion_score

        # Only HIGH+ severity
        if score < settings.insider_min_score:
            logger.debug(f"Insider signal skipped: score {score} < {settings.insider_min_score}")
            return

        # Skip excluded markets
        if _is_excluded_market(trade.market_question, trade.market_slug):
            logger.debug(f"Insider signal skipped: excluded market {trade.market_question[:40]}")
            return

        # We need a token_id to trade. Get market data.
        async with PolymarketClient() as client:
            market = await client.get_market(trade.market_id)
            if not market:
                logger.warning(f"Could not fetch market {trade.market_id}")
                return

            # Get token IDs from market
            tokens = market.get("tokens", []) or market.get("clobTokenIds", [])
            if not tokens:
                logger.warning(f"No tokens found for market {trade.market_id}")
                return

            # Determine which token to buy based on the suspicious trade's outcome
            # The insider bought a specific outcome — we follow
            token_id = None
            if isinstance(tokens, list) and len(tokens) >= 2:
                if isinstance(tokens[0], dict):
                    # tokens is list of dicts with token_id and outcome
                    for t in tokens:
                        outcome = t.get("outcome", "").lower()
                        if trade.outcome and trade.outcome.lower() == outcome:
                            token_id = t.get("token_id")
                            break
                    if not token_id:
                        token_id = tokens[0].get("token_id")  # default to first
                else:
                    # tokens is list of token_id strings [yes_token, no_token]
                    token_id = tokens[0] if trade.outcome in ("Yes", "YES", "yes") else tokens[1]
            elif isinstance(tokens, list) and len(tokens) == 1:
                token_id = tokens[0] if isinstance(tokens[0], str) else tokens[0].get("token_id")

            if not token_id:
                logger.warning(f"Could not determine token_id for {trade.market_question[:40]}")
                return

            # Check current price — skip if moved too much
            current_prices = market.get("outcomePrices", "")
            if current_prices and isinstance(current_prices, str):
                try:
                    import json
                    prices = json.loads(current_prices)
                    current_price_cents = float(prices[0]) * 100 if prices else None
                except (json.JSONDecodeError, IndexError):
                    current_price_cents = None
            else:
                current_price_cents = None

            if current_price_cents and trade.price > 0:
                drift_pct = abs(current_price_cents - trade.price) / trade.price * 100
                if drift_pct > settings.insider_max_price_drift_pct:
                    logger.info(f"Insider signal skipped: price drifted {drift_pct:.1f}% on {trade.market_question[:40]}")
                    return

            # Fixed position size of $25
            amount_usd = min(25.0, settings.strategy_max_per_trade)

            # Risk check
            approved, reason = await risk_manager.approve_trade(
                "INSIDER-SIGNAL", amount_usd, trade.market_slug, token_id
            )
            if not approved:
                logger.info(f"Insider trade rejected: {reason}")
                return

            # Execute the buy
            result = await auto_seller.execute_buy(
                token_id=token_id,
                amount_usd=amount_usd,
                max_price=None,  # Market order
            )

            if result.success:
                # Log to journal
                journal.log_entry(
                    strategy="INSIDER-SIGNAL",
                    action="ENTER",
                    market_question=trade.market_question,
                    market_slug=trade.market_slug,
                    token_id=token_id,
                    side="BUY",
                    price=result.price,
                    shares=result.shares,
                    amount_usd=amount_usd,
                    reason=f"Score {score} | Flags: {', '.join(suspicious.flags[:3])}",
                    order_id=result.order_id,
                )
                logger.info(f"🎯 INSIDER TRADE: ${amount_usd:.2f} on {trade.market_question[:50]}")
            else:
                logger.warning(f"Insider buy failed: {result.error}")

    async def _run_resolution_arbitrage(self):
        """Scan for near-resolution markets with near-certain outcomes."""
        logger.debug("Running resolution arbitrage scan...")

        async with PolymarketClient() as client:
            markets = await client.get_markets(limit=100, order="volume24hr")
            if not markets:
                return

            now = datetime.utcnow()
            candidates = 0

            for market in markets:
                try:
                    await self._evaluate_arb_candidate(client, market, now)
                    candidates += 1
                except Exception as e:
                    logger.debug(f"Arb eval error: {e}")
                    continue

            logger.debug(f"Arb scan complete: evaluated {candidates} markets")

    async def _evaluate_arb_candidate(self, client: PolymarketClient, market: dict, now: datetime):
        """Evaluate a single market for resolution arbitrage."""
        question = market.get("question", "")
        slug = market.get("slug", "") or market.get("market_slug", "")

        # Skip excluded markets
        if _is_excluded_market(question, slug):
            return

        # Must be active
        if not market.get("active", False):
            return

        # Check end date — must be within window
        end_date_str = market.get("endDate") or market.get("end_date_iso")
        if not end_date_str:
            return
        try:
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except (ValueError, AttributeError):
            return

        hours_to_end = (end_date - now).total_seconds() / 3600
        if hours_to_end <= 0 or hours_to_end > settings.arb_max_hours_to_end:
            return

        # Check outcome prices
        prices_str = market.get("outcomePrices", "")
        if not prices_str:
            return
        try:
            import json
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            if not prices or len(prices) < 2:
                return
            prices = [float(p) for p in prices]
        except (json.JSONDecodeError, ValueError):
            return

        # Find the dominant outcome
        max_price = max(prices)
        max_idx = prices.index(max_price)

        # Must be in the sweet spot: 95-99c
        if max_price < settings.arb_min_probability or max_price > settings.arb_max_probability:
            return

        # Calculate expected return
        expected_return_pct = ((1.0 - max_price) / max_price) * 100
        if expected_return_pct < 1.0:  # At least 1% return
            return

        # Check liquidity
        liquidity = float(market.get("liquidity", 0) or 0)
        if liquidity < settings.arb_min_liquidity:
            return

        # Get token ID for the dominant outcome
        tokens = market.get("tokens", []) or market.get("clobTokenIds", [])
        if not tokens or len(tokens) < 2:
            return

        if isinstance(tokens[0], dict):
            token_id = tokens[max_idx].get("token_id") if max_idx < len(tokens) else None
        else:
            token_id = tokens[max_idx] if max_idx < len(tokens) else None

        if not token_id:
            return

        # Verify order book depth
        book = await client.get_order_book(token_id)
        if not book:
            return
        asks = book.get("asks", []) if isinstance(book, dict) else getattr(book, "asks", [])
        if not asks:
            return

        # Check actual ask price
        if isinstance(asks[0], dict):
            best_ask = float(asks[0].get("price", 1.0))
        else:
            best_ask = float(getattr(asks[0], "price", 1.0))

        if best_ask > settings.arb_max_probability:
            return  # Too expensive

        # Position size: $25 fixed
        amount_usd = min(25.0, settings.strategy_max_per_trade)

        # Risk check
        approved, reason = await risk_manager.approve_trade(
            "RESOLUTION-ARB", amount_usd, slug, token_id
        )
        if not approved:
            logger.debug(f"Arb rejected: {reason}")
            return

        # Execute
        result = await auto_seller.execute_buy(
            token_id=token_id,
            amount_usd=amount_usd,
            max_price=settings.arb_max_probability,
        )

        if result.success:
            journal.log_entry(
                strategy="RESOLUTION-ARB",
                action="ENTER",
                market_question=question,
                market_slug=slug,
                token_id=token_id,
                side="BUY",
                price=result.price,
                shares=result.shares,
                amount_usd=amount_usd,
                reason=f"Outcome @ {max_price*100:.1f}c | {expected_return_pct:.1f}% return | Ends in {hours_to_end:.0f}h",
                order_id=result.order_id,
            )
            logger.info(f"📈 ARB TRADE: ${amount_usd:.2f} on {question[:50]} @ {result.price:.4f}")
        else:
            logger.debug(f"Arb buy failed: {result.error}")

    def get_status(self) -> dict:
        """Return current strategy engine status."""
        open_positions = journal.get_open_positions()
        performance = journal.get_performance()
        balance = auto_seller.get_usdc_balance()

        return {
            "enabled": settings.strategy_enabled,
            "strategies": {
                "insider_signal": settings.strategy_insider_enabled,
                "resolution_arb": settings.strategy_arbitrage_enabled,
            },
            "risk_limits": {
                "max_total_exposure": min(risk_manager.HARD_MAX_EXPOSURE, settings.strategy_max_total_exposure),
                "max_per_trade": min(risk_manager.HARD_MAX_PER_TRADE, settings.strategy_max_per_trade),
                "balance_floor": max(risk_manager.HARD_BALANCE_FLOOR, settings.strategy_balance_floor),
                "max_positions": min(risk_manager.HARD_MAX_POSITIONS, settings.strategy_max_open_positions),
            },
            "current_state": {
                "usdc_balance": balance,
                "open_positions": len(open_positions),
                "total_exposure": journal.get_total_exposure(),
                "positions": open_positions,
            },
            "performance": performance,
            "insider_queue_size": len(self._insider_queue),
            "last_arb_scan": self._last_arb_scan.isoformat() if self._last_arb_scan else None,
        }


# Singleton
strategy_engine = StrategyEngine()
