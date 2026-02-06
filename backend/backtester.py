"""
Backtesting module for the Insider Detector.

Replays historical trades on resolved markets through the detection engine
to validate it catches known insider cases.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
from loguru import logger

from .polymarket_client import PolymarketClient
from .detectors import detector


# Known insider trading cases for validation
# Each case has a hardcoded conditionId, slug, and the actual insider wallet address
KNOWN_CASES = {
    "maduro_capture": {
        "id": "maduro_capture",
        "name": "Maduro Capture (Jan 2026)",
        "description": 'User "Burdensome-Mix" wagered ~$32k at ~7% odds on Maduro capture hours before the raid was announced, netting $436k profit.',
        "condition_id": "0x580adc1327de9bf7c179ef5aaffa3377bb5cb252b7d6390b027172d43fd6f993",
        "slug": "maduro-out-by-january-31-2026",
        "question": "Maduro out by January 31, 2026?",
        "insider_wallet": "0x31a56e9E690c621eD21De08Cb559e9524Cdb8eD9",
        "insider_name": "Burdensome-Mix",
        "expected_min_score": 60,
        "expected_signals": ["Fresh Wallet", "Extreme Odds", "Position Size"],
    },
    "nobel_peace_prize": {
        "id": "nobel_peace_prize",
        "name": "Nobel Peace Prize (2025)",
        "description": 'User "dirtycup" placed ~$70k on Machado at ~3.6% odds, hours before the announcement. Norway investigated as a possible leak.',
        "condition_id": "0x14a3dfeba8b22a32feb0f10763db68bc4d2abeb5bff90e9ae20de53793b35a1d",
        "slug": "will-mara-corina-machado-win-the-nobel-peace-prize-in-2025",
        "question": "Will Maria Corina Machado win the Nobel Peace Prize in 2025?",
        "insider_wallet": "0x234cc49e43dff8b3207bbd3a8a2579f339cb9867",
        "insider_name": "dirtycup",
        "expected_min_score": 60,
        "expected_signals": ["Extreme Odds", "Position Size", "Timing"],
    },
    "taylor_swift_engagement": {
        "id": "taylor_swift_engagement",
        "name": "Taylor Swift Engagement (Aug 2025)",
        "description": 'User "romanticpaul" bought shares within 15 hours of the public announcement, redeemed 5,180 shares for $5,180.',
        "condition_id": "0x89ac32e18929185f5bd0dc00e70337571f546e64ae5cd16dceb6026ac2679c1e",
        "slug": "taylor-swift-and-travis-kelce-engaged-in-2025",
        "question": "Taylor Swift and Travis Kelce engaged in 2025?",
        "insider_wallet": "0xf5cfe6f998d597085e366f915b140e82e0869fc6",
        "insider_name": "romanticpaul",
        "expected_min_score": 60,
        "expected_signals": ["Fresh Wallet", "Timing"],
    },
    "google_year_in_search": {
        "id": "google_year_in_search",
        "name": "Google Year in Search (2025)",
        "description": 'Wallet "AlphaRaccoon" deposited $3M and went 22-for-23 on Google search markets, netting ~$1M. Suspected Google insider.',
        "condition_id": "0xea17b1284d10617a57f910b2ea63bdef481b1724a4b899d454ff104bea67b657",
        "slug": "will-d4vd-be-the-1-searched-person-on-google-this-year",
        "question": "Will d4vd be the #1 searched person on Google this year?",
        "insider_wallet": "0xee50a31c3f5a7c77824b12a941a54388a2827ed6",
        "insider_name": "AlphaRaccoon",
        "expected_min_score": 60,
        "expected_signals": ["Position Size", "Extreme Odds"],
    },
}


@dataclass
class BacktestResult:
    """Result from backtesting a single market"""
    case_id: Optional[str] = None
    case_name: Optional[str] = None
    market_question: str = ""
    market_id: str = ""
    market_slug: str = ""
    total_trades: int = 0
    trades_analyzed: int = 0
    suspicious_trades: List[Dict[str, Any]] = field(default_factory=list)
    top_score: float = 0
    expected_min_score: float = 0
    passed: Optional[bool] = None
    error: Optional[str] = None
    duration_seconds: float = 0
    # Known insider tracking
    insider_wallet: Optional[str] = None
    insider_name: Optional[str] = None
    insider_found: bool = False
    insider_score: Optional[float] = None
    insider_rank: Optional[int] = None  # Where the insider ranked in suspicious trades


class Backtester:
    """
    Replay historical trades through the detection engine.
    """

    async def search_resolved_markets(
        self, query: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Search for resolved/closed markets by keyword using Gamma API text search."""
        results = []
        async with PolymarketClient() as client:
            try:
                # Gamma API supports text search via the slug-like endpoint
                # and also via direct query on the markets list
                response = await client.client.get(
                    f"{client.gamma_url}/markets",
                    params={
                        "limit": limit,
                        "closed": "true",
                        "order": "volume24hr",
                        "ascending": "false",
                    },
                )
                response.raise_for_status()
                markets = response.json()

                query_lower = query.lower()
                for m in markets:
                    question = (m.get("question") or "").lower()
                    description = (m.get("description") or "").lower()
                    if query_lower in question or query_lower in description:
                        results.append({
                            "id": m.get("id"),
                            "conditionId": m.get("conditionId"),
                            "question": m.get("question"),
                            "slug": m.get("slug"),
                            "volume": m.get("volume"),
                            "closed": m.get("closed"),
                        })
            except Exception as e:
                logger.debug(f"Gamma search failed: {e}")

            # Also try searching by slug (handles exact slug matches)
            if not results:
                try:
                    slug_query = query.lower().replace(" ", "-")
                    response = await client.client.get(
                        f"{client.gamma_url}/markets",
                        params={"slug": slug_query},
                    )
                    if response.status_code == 200:
                        data = response.json()
                        markets_list = data if isinstance(data, list) else [data] if data else []
                        for m in markets_list:
                            if m.get("conditionId"):
                                results.append({
                                    "id": m.get("id"),
                                    "conditionId": m.get("conditionId"),
                                    "question": m.get("question"),
                                    "slug": m.get("slug"),
                                    "volume": m.get("volume"),
                                    "closed": m.get("closed"),
                                })
                except Exception as e:
                    logger.debug(f"Slug search failed: {e}")

        return results[:limit]

    async def backtest_market(
        self, condition_id: str, market_question: str = "", market_slug: str = ""
    ) -> BacktestResult:
        """
        Backtest a single market: fetch all trades and run them through detection.
        """
        start = datetime.utcnow()
        result = BacktestResult(
            market_id=condition_id,
            market_question=market_question,
            market_slug=market_slug,
        )

        try:
            async with PolymarketClient() as client:
                # Fetch trades for this market
                trades = await client.get_market_trades(condition_id, limit=500)
                result.total_trades = len(trades)

                if not trades:
                    result.error = "No trades found for this market"
                    return result

                # Build market_data dict for the detector
                market_data = {
                    "id": condition_id,
                    "slug": market_slug,
                    "question": market_question,
                    "yes_price": 50,
                    "no_price": 50,
                    "volume_24h": 0,
                    "volume_total": 0,
                    "liquidity": 0,
                    "is_active": False,
                }

                # Try to enrich from API
                market_info = await client.get_market(condition_id)
                if market_info:
                    market_data["question"] = market_info.get("question", market_question)
                    market_data["slug"] = market_info.get("slug", market_slug)
                    result.market_question = market_data["question"]
                    result.market_slug = market_data["slug"]

                # Cache wallet profiles to avoid redundant lookups
                wallet_cache: Dict[str, Dict] = {}

                for trade in trades:
                    wallet_addr = trade.get("user") or trade.get("proxyWallet") or trade.get("maker")
                    if not wallet_addr or len(wallet_addr) < 10:
                        continue

                    # Normalize trade fields
                    trade["maker"] = wallet_addr
                    trade["market"] = condition_id
                    trade["side"] = trade.get("side") or trade.get("type") or "BUY"
                    trade["market_question"] = market_data["question"]
                    trade["market_slug"] = market_data["slug"]

                    # Calculate notional
                    shares = float(trade.get("size", 0) or trade.get("amount", 0) or 0)
                    price = float(trade.get("price", 50) or 50)
                    if price <= 1:
                        price = price * 100
                    trade["notional_usd"] = trade.get("usdcSize") or (shares * price / 100)
                    if isinstance(trade["notional_usd"], str):
                        trade["notional_usd"] = float(trade["notional_usd"])

                    # Get or fetch wallet profile
                    if wallet_addr not in wallet_cache:
                        wallet_cache[wallet_addr] = await client.get_wallet_profile(wallet_addr)
                    wallet_profile = wallet_cache[wallet_addr]

                    # Run through detector
                    suspicious, signals = detector.analyze_trade_detailed(
                        trade_data=trade,
                        wallet_profile=wallet_profile,
                        market_data=market_data,
                    )

                    total_score = sum(s["score"] for s in signals)
                    result.trades_analyzed += 1

                    if total_score > 0:
                        entry = {
                            "trader": wallet_addr,
                            "side": trade.get("side", "BUY"),
                            "notional_usd": trade.get("notional_usd", 0),
                            "price": price,
                            "shares": shares,
                            "score": total_score,
                            "signals": signals,
                            "is_alert": suspicious is not None,
                            "severity": suspicious.severity.value if suspicious else None,
                            "wallet_trades": wallet_profile.get("total_trades", 0),
                            "wallet_markets": wallet_profile.get("unique_markets", 0),
                        }
                        result.suspicious_trades.append(entry)
                        if total_score > result.top_score:
                            result.top_score = total_score

                # Sort by score descending
                result.suspicious_trades.sort(key=lambda x: x["score"], reverse=True)
                # Keep top 50
                result.suspicious_trades = result.suspicious_trades[:50]

        except Exception as e:
            logger.error(f"Backtest error for {condition_id}: {e}")
            result.error = str(e)

        result.duration_seconds = (datetime.utcnow() - start).total_seconds()
        return result

    async def run_known_case(self, case_id: str) -> BacktestResult:
        """
        Run backtest for a known insider trading case.
        Uses the hardcoded conditionId directly — no search needed.
        Checks if the known insider wallet was detected and at what score.
        """
        case = KNOWN_CASES.get(case_id)
        if not case:
            return BacktestResult(
                case_id=case_id, error=f"Unknown case: {case_id}"
            )

        try:
            condition_id = case["condition_id"]
            result = await self.backtest_market(
                condition_id=condition_id,
                market_question=case.get("question", ""),
                market_slug=case.get("slug", ""),
            )
            result.case_id = case_id
            result.case_name = case["name"]
            result.expected_min_score = case["expected_min_score"]

            # Track the known insider
            insider_wallet = case.get("insider_wallet", "").lower()
            result.insider_wallet = case.get("insider_wallet")
            result.insider_name = case.get("insider_name")

            # Check if the insider was found in suspicious trades
            if insider_wallet:
                for i, trade in enumerate(result.suspicious_trades):
                    trader_addr = (trade.get("trader") or "").lower()
                    if trader_addr == insider_wallet:
                        result.insider_found = True
                        result.insider_score = trade.get("score", 0)
                        result.insider_rank = i + 1  # 1-indexed rank
                        # Mark this trade as the known insider in the results
                        trade["is_known_insider"] = True
                        trade["insider_name"] = case.get("insider_name")
                        break

            # Pass if we found the insider with a good score, or if top score is high
            result.passed = (
                (result.insider_found and result.insider_score and result.insider_score >= case["expected_min_score"])
                or result.top_score >= case["expected_min_score"]
            )

        except Exception as e:
            logger.error(f"Known case backtest error for {case_id}: {e}")
            result = BacktestResult(
                case_id=case_id,
                case_name=case["name"],
                expected_min_score=case["expected_min_score"],
                error=str(e),
            )

        return result


# Singleton
backtester = Backtester()
