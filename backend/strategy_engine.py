"""
Strategy Engine — Orchestrates paper trading strategies.

Three strategies:
1. Insider Signal Following — piggybacks on the detector pipeline
2. Smart Money Copy Trading — follows top leaderboard traders
3. Resolution Arbitrage — buys near-certain outcomes before resolution

All trades are PAPER ONLY — logged to trade journal and paper_trader.
No real money is spent.
"""
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from loguru import logger

from .config import settings
from .models import SuspiciousTrade, AlertSeverity
from .polymarket_client import PolymarketClient
from .auto_seller import auto_seller
from .trade_journal import journal
from .paper_trader import paper_trader
from .leaderboard import tracker


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
    """Orchestrates paper trading strategies."""

    def __init__(self):
        self._last_arb_scan: Optional[datetime] = None
        self._last_watchlist_curate: Optional[datetime] = None
        self._insider_queue: list[SuspiciousTrade] = []
        self._smart_money_last_seen: Dict[str, str] = {}  # address -> last trade timestamp

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

        # Smart money copy trading (check every cycle)
        if settings.strategy_smartmoney_enabled:
            await self._run_smart_money()

        # Auto-curate watchlist every 6 hours
        if settings.strategy_smartmoney_enabled:
            now = datetime.utcnow()
            if self._last_watchlist_curate is None or (now - self._last_watchlist_curate) > timedelta(hours=6):
                await self._curate_smart_money_watchlist()
                self._last_watchlist_curate = now

        # Resolution arbitrage (every 15 minutes)
        if settings.strategy_arbitrage_enabled:
            now = datetime.utcnow()
            if self._last_arb_scan is None or (now - self._last_arb_scan) > timedelta(minutes=15):
                await self._run_resolution_arbitrage()
                self._last_arb_scan = now

    # ==================== STRATEGY 1: INSIDER SIGNAL ====================

    async def _run_insider_signals(self):
        """Process queued insider alerts."""
        while self._insider_queue:
            suspicious = self._insider_queue.pop(0)
            try:
                await self._execute_insider_trade(suspicious)
            except Exception as e:
                logger.error(f"Insider signal error: {e}")

    async def _execute_insider_trade(self, suspicious: SuspiciousTrade):
        """Evaluate and paper-trade based on an insider signal."""
        trade = suspicious.trade
        score = suspicious.suspicion_score

        if score < settings.insider_min_score:
            return

        if _is_excluded_market(trade.market_question, trade.market_slug):
            return

        # Check if we already have a position in this market
        if journal.has_open_position(trade.market_id):
            return

        async with PolymarketClient() as client:
            market = await client.get_market(trade.market_id)
            if not market:
                return

            # Get current price
            current_price = self._get_market_price(market, trade.outcome)
            if current_price is None:
                current_price = trade.price / 100  # fallback to trade price in 0-1 scale

            # Check price drift
            if trade.price > 0:
                detected_price = trade.price / 100  # cents to 0-1
                drift_pct = abs(current_price - detected_price) / detected_price * 100
                if drift_pct > settings.insider_max_price_drift_pct:
                    logger.info(f"Insider skipped: price drifted {drift_pct:.1f}% on {trade.market_question[:40]}")
                    return

            amount_usd = min(25.0, settings.strategy_max_per_trade)

            # Paper trade via paper_trader
            paper_trade = await paper_trader.record_copy_trade(
                copied_from=suspicious.wallet.address,
                copied_from_name="INSIDER-SIGNAL",
                market_id=trade.market_id,
                market_title=trade.market_question,
                market_slug=trade.market_slug,
                outcome=trade.outcome or "Yes",
                side=trade.side or "BUY",
                their_entry_price=trade.price / 100 if trade.price > 1 else trade.price,
                our_entry_price=current_price if current_price > 0 else 0.5,
            )

            # Also log to trade journal for the strategy dashboard
            journal.log_entry(
                strategy="INSIDER-SIGNAL",
                action="ENTER",
                market_question=trade.market_question,
                market_slug=trade.market_slug,
                token_id=trade.market_id,
                side=trade.side or "BUY",
                price=current_price,
                shares=paper_trade.shares,
                amount_usd=amount_usd,
                reason=f"Score {score} | {', '.join(suspicious.flags[:2])}",
            )
            logger.info(f"📝 INSIDER PAPER: {trade.market_question[:50]} @ {current_price:.4f}")

    # ==================== STRATEGY 2: SMART MONEY COPY ====================

    async def _curate_smart_money_watchlist(self):
        """Auto-curate the watchlist from leaderboard top performers."""
        logger.info("Curating smart money watchlist...")
        try:
            leaders = await tracker.fetch_leaderboard(order_by="pnl", limit=50)
            if not leaders:
                return

            candidates = []
            for t in leaders:
                win_rate = float(t.get("win_rate", 0) or 0)
                pnl = float(t.get("pnl", 0) or 0)
                markets = int(t.get("markets_traded", 0) or 0)
                address = t.get("address", "")

                if win_rate >= settings.smartmoney_min_win_rate and pnl > 0 and markets >= settings.smartmoney_min_markets:
                    candidates.append(address)

                if len(candidates) >= settings.smartmoney_max_wallets:
                    break

            # Add new candidates to watchlist
            added = 0
            for addr in candidates:
                if addr not in tracker.watched_wallets:
                    tracker.watch(addr)
                    added += 1

            if added:
                logger.info(f"Added {added} smart money wallets to watchlist (total: {len(tracker.watched_wallets)})")

        except Exception as e:
            logger.error(f"Watchlist curation error: {e}")

    async def _run_smart_money(self):
        """Check watched traders for new trades and paper-copy them."""
        if not tracker.watched_wallets:
            return

        async with PolymarketClient() as client:
            for address in list(tracker.watched_wallets):
                try:
                    trades = await client.get_user_trades(address, limit=10)
                    if not trades:
                        continue

                    last_seen = self._smart_money_last_seen.get(address)
                    latest_ts = None

                    for t in trades:
                        ts = t.get("timestamp") or t.get("createdAt") or ""
                        if not ts:
                            continue
                        if last_seen and ts <= last_seen:
                            break
                        if not latest_ts or ts > latest_ts:
                            latest_ts = ts

                        # New trade from watched trader
                        market_title = t.get("title") or t.get("question") or t.get("market") or "Unknown"
                        market_slug = t.get("market_slug") or t.get("slug") or ""
                        market_id = t.get("conditionId") or t.get("market_id") or t.get("condition_id") or ""
                        side = t.get("side") or "BUY"
                        price = float(t.get("price") or 0)
                        usdc_size = float(t.get("usdcSize") or t.get("size") or 0)
                        outcome = t.get("outcome") or "Yes"

                        # Skip excluded markets
                        if _is_excluded_market(market_title, market_slug):
                            continue

                        # Skip tiny trades
                        if usdc_size < 10:
                            continue

                        # Check slippage — get current price
                        if market_id:
                            market_data = await client.get_market(market_id)
                            current_price = self._get_market_price(market_data, outcome) if market_data else price
                        else:
                            current_price = price

                        if current_price and price > 0:
                            slippage = abs(current_price - price) / price * 100
                            if slippage > 5.0:
                                logger.debug(f"Smart money skip: {slippage:.1f}% slippage on {market_title[:30]}")
                                continue

                        entry_price = current_price if current_price and current_price > 0 else price

                        # Paper trade
                        await paper_trader.record_copy_trade(
                            copied_from=address,
                            copied_from_name="SMART-MONEY",
                            market_id=market_id,
                            market_title=market_title,
                            market_slug=market_slug,
                            outcome=outcome,
                            side=side,
                            their_entry_price=price,
                            our_entry_price=entry_price if entry_price > 0 else 0.5,
                        )

                        journal.log_entry(
                            strategy="SMART-MONEY",
                            action="ENTER",
                            market_question=market_title,
                            market_slug=market_slug,
                            token_id=market_id,
                            side=side,
                            price=entry_price,
                            shares=25.0 / entry_price if entry_price > 0 else 0,
                            amount_usd=25.0,
                            reason=f"Copied {address[:10]}... | ${usdc_size:.0f} trade",
                        )
                        logger.info(f"📝 SMART MONEY PAPER: {market_title[:40]} copied from {address[:10]}...")

                    if latest_ts:
                        self._smart_money_last_seen[address] = latest_ts

                except Exception as e:
                    logger.debug(f"Smart money check error for {address[:12]}: {e}")

    # ==================== STRATEGY 3: RESOLUTION ARBITRAGE ====================

    async def _run_resolution_arbitrage(self):
        """Scan for near-resolution markets with near-certain outcomes."""
        logger.debug("Running resolution arbitrage scan...")

        async with PolymarketClient() as client:
            markets = await client.get_markets(limit=100, order="volume24hr")
            if not markets:
                return

            now = datetime.utcnow()
            for market in markets:
                try:
                    await self._evaluate_arb_candidate(client, market, now)
                except Exception as e:
                    logger.debug(f"Arb eval error: {e}")

    async def _evaluate_arb_candidate(self, client: PolymarketClient, market: dict, now: datetime):
        """Evaluate a single market for resolution arbitrage."""
        question = market.get("question", "")
        slug = market.get("slug", "") or market.get("market_slug", "")

        if _is_excluded_market(question, slug):
            return
        if not market.get("active", False):
            return

        # Check end date
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
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            if not prices or len(prices) < 2:
                return
            prices = [float(p) for p in prices]
        except (json.JSONDecodeError, ValueError):
            return

        max_price = max(prices)
        max_idx = prices.index(max_price)

        if max_price < settings.arb_min_probability or max_price > settings.arb_max_probability:
            return

        expected_return_pct = ((1.0 - max_price) / max_price) * 100
        if expected_return_pct < 1.0:
            return

        liquidity = float(market.get("liquidity", 0) or 0)
        if liquidity < settings.arb_min_liquidity:
            return

        market_id = market.get("conditionId") or market.get("id") or ""
        if journal.has_open_position(market_id):
            return

        outcome = "Yes" if max_idx == 0 else "No"
        amount_usd = min(25.0, settings.strategy_max_per_trade)

        # Paper trade
        await paper_trader.record_copy_trade(
            copied_from="SYSTEM",
            copied_from_name="RESOLUTION-ARB",
            market_id=market_id,
            market_title=question,
            market_slug=slug,
            outcome=outcome,
            side="BUY",
            their_entry_price=max_price,
            our_entry_price=max_price,
        )

        journal.log_entry(
            strategy="RESOLUTION-ARB",
            action="ENTER",
            market_question=question,
            market_slug=slug,
            token_id=market_id,
            side="BUY",
            price=max_price,
            shares=amount_usd / max_price if max_price > 0 else 0,
            amount_usd=amount_usd,
            reason=f"Outcome @ {max_price*100:.1f}c | {expected_return_pct:.1f}% return | Ends in {hours_to_end:.0f}h",
        )
        logger.info(f"📝 ARB PAPER: {question[:50]} @ {max_price:.4f}")

    # ==================== HELPERS ====================

    def _get_market_price(self, market: dict, outcome: str = "Yes") -> Optional[float]:
        """Extract current price for an outcome from market data."""
        if not market:
            return None
        prices_str = market.get("outcomePrices", "")
        if not prices_str:
            return None
        try:
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            if not prices:
                return None
            idx = 0 if outcome in ("Yes", "YES", "yes") else 1
            if idx < len(prices):
                return float(prices[idx])
            return float(prices[0])
        except (json.JSONDecodeError, ValueError, IndexError):
            return None

    def get_status(self) -> dict:
        """Return current strategy engine status."""
        open_positions = journal.get_open_positions()
        performance = journal.get_performance()
        balance = auto_seller.get_usdc_balance()

        return {
            "enabled": settings.strategy_enabled,
            "mode": "PAPER",
            "strategies": {
                "insider_signal": settings.strategy_insider_enabled,
                "smart_money": settings.strategy_smartmoney_enabled,
                "resolution_arb": settings.strategy_arbitrage_enabled,
            },
            "risk_limits": {
                "max_total_exposure": settings.strategy_max_total_exposure,
                "max_per_trade": settings.strategy_max_per_trade,
                "balance_floor": settings.strategy_balance_floor,
                "max_positions": settings.strategy_max_open_positions,
            },
            "current_state": {
                "usdc_balance": balance,
                "open_positions": len(open_positions),
                "total_exposure": journal.get_total_exposure(),
                "positions": open_positions,
                "watched_wallets": len(tracker.watched_wallets),
            },
            "performance": performance,
            "insider_queue_size": len(self._insider_queue),
            "last_arb_scan": self._last_arb_scan.isoformat() if self._last_arb_scan else None,
            "last_watchlist_curate": self._last_watchlist_curate.isoformat() if self._last_watchlist_curate else None,
        }


# Singleton
strategy_engine = StrategyEngine()
