"""
Smart Money Tracker - Leaderboard & Watchlist

Track top Polymarket performers and get notified when they place new bets.
"""
import json
import os
from typing import List, Dict, Any, Set, Optional
from datetime import datetime, timedelta
from loguru import logger

from .polymarket_client import PolymarketClient
from .notifications import get_notifier


WATCHLIST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "watched_wallets.json"
)

# Keywords for classifying market questions by category
CATEGORY_KEYWORDS = {
    "sports": [
        "nfl", "nba", "mlb", "nhl", "fifa", "soccer", "football", "basketball",
        "baseball", "tennis", "golf", "boxing", "ufc", "mma", "superbowl", "super bowl",
        "championship", "world cup", "league", "playoff", "match", "game", "season",
        "team", "player", "score", "win", "tournament", "series",
    ],
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto", "token",
        "coin", "blockchain", "defi", "nft", "altcoin", "binance", "coinbase",
        "stablecoin", "usdc", "usdt", "doge", "xrp", "ripple", "cardano",
        "price above", "price below", "reach $", "hit $",
    ],
    "politics": [
        "election", "president", "congress", "senate", "house", "democrat",
        "republican", "vote", "ballot", "legislation", "bill", "supreme court",
        "governor", "mayor", "parliament", "prime minister", "cabinet", "impeach",
        "approval rating", "poll", "campaign", "candidate", "party",
    ],
    "geopolitics": [
        "war", "military", "attack", "ceasefire", "missile", "bomb", "troops",
        "sanctions", "nato", "israel", "iran", "ukraine", "russia", "china",
        "taiwan", "north korea", "middle east", "conflict", "invasion", "coup",
        "nuclear", "diplomatic", "treaty", "alliance", "occupation",
    ],
    "finance": [
        "stock", "earnings", "revenue", "fed rate", "interest rate", "cpi",
        "inflation", "gdp", "recession", "bank", "s&p", "nasdaq", "dow",
        "market cap", "ipo", "merger", "acquisition", "bankruptcy", "bonds",
        "yield", "hedge fund", "treasury", "federal reserve",
    ],
    "tech": [
        "apple", "google", "microsoft", "amazon", "meta", "tesla", "openai",
        "nvidia", "ai model", "artificial intelligence", "launch", "release",
        "product", "spacex", "starship", "gpt", "claude", "gemini", "llm",
        "chip", "semiconductor", "app", "software", "hardware",
    ],
    "science": [
        "asteroid", "climate", "temperature", "vaccine", "drug", "disease",
        "cancer", "fda", "trial", "study", "nasa", "space", "planet", "moon",
        "earthquake", "hurricane", "storm", "wildfire",
    ],
    "entertainment": [
        "oscar", "grammy", "emmy", "golden globe", "celebrity", "movie",
        "film", "show", "actor", "actress", "music", "album", "award",
        "box office", "spotify", "netflix", "disney",
    ],
}


def classify_market_category(question: str) -> str:
    """Classify a market question into a category based on keywords."""
    text = question.lower()
    scores: Dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[category] = score
    if not scores:
        return "other"
    return max(scores, key=lambda c: scores[c])


class LeaderboardTracker:
    """
    Tracks top Polymarket traders and monitors watched wallets for new trades.
    """

    def __init__(self):
        self.watched_wallets: Set[str] = set()
        self._last_seen_trades: Dict[str, str] = {}  # wallet -> last trade timestamp
        self._wallet_specializations: Dict[str, Dict] = {}  # wallet -> category breakdown
        self._load_watchlist()

    def _load_watchlist(self):
        """Load watched wallets from disk."""
        try:
            if os.path.exists(WATCHLIST_PATH):
                with open(WATCHLIST_PATH, "r") as f:
                    data = json.load(f)
                self.watched_wallets = set(data.get("wallets", []))
                self._last_seen_trades = data.get("last_seen", {})
                self._wallet_specializations = data.get("specializations", {})
                logger.info(f"Loaded {len(self.watched_wallets)} watched wallets")
        except Exception as e:
            logger.error(f"Error loading watchlist: {e}")

    def _save_watchlist(self):
        """Persist watched wallets to disk."""
        try:
            os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
            with open(WATCHLIST_PATH, "w") as f:
                json.dump(
                    {
                        "wallets": list(self.watched_wallets),
                        "last_seen": self._last_seen_trades,
                        "specializations": self._wallet_specializations,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Error saving watchlist: {e}")

    async def analyze_wallet_specialization(self, address: str, trades: list) -> Dict:
        """
        Build a category profile from a wallet's recent trades.
        Returns dict: {category: count, ...} plus top_category.
        """
        counts: Dict[str, int] = {}
        for t in trades:
            question = t.get("title") or t.get("question") or t.get("market") or ""
            if question:
                cat = classify_market_category(question)
                counts[cat] = counts.get(cat, 0) + 1

        if not counts:
            return {"top_category": "unknown", "distribution": {}}

        total = sum(counts.values())
        distribution = {k: round(v / total * 100) for k, v in sorted(counts.items(), key=lambda x: -x[1])}
        top = max(counts, key=lambda c: counts[c])
        top_pct = distribution[top]

        return {
            "top_category": top,
            "top_pct": top_pct,
            "distribution": distribution,
            "total_classified": total,
            "updated": datetime.utcnow().isoformat(),
        }

    def get_wallet_specialization(self, address: str) -> Optional[Dict]:
        """Return cached specialization data for a wallet."""
        return self._wallet_specializations.get(address.lower())

    def watch(self, address: str):
        """Add a wallet to the watchlist."""
        self.watched_wallets.add(address.lower())
        self._save_watchlist()

    def unwatch(self, address: str):
        """Remove a wallet from the watchlist."""
        self.watched_wallets.discard(address.lower())
        self._last_seen_trades.pop(address.lower(), None)
        self._save_watchlist()

    def get_watching(self) -> List[str]:
        """Return list of watched wallet addresses."""
        return list(self.watched_wallets)

    async def fetch_leaderboard(
        self,
        category: Optional[str] = None,
        time_period: str = "all",
        order_by: str = "pnl",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch leaderboard rankings from the API."""
        async with PolymarketClient() as client:
            data = await client.get_leaderboard(
                category=category,
                time_period=time_period,
                order_by=order_by,
                limit=limit,
            )

            results = []
            if isinstance(data, list):
                for entry in data:
                    # API returns: proxyWallet, userName, vol, pnl, rank
                    address = entry.get("proxyWallet") or entry.get("address") or entry.get("user") or ""
                    results.append({
                        "address": address,
                        "display_name": entry.get("userName") or entry.get("displayName") or entry.get("username") or "",
                        "pnl": float(entry.get("pnl") or entry.get("profit") or 0),
                        "volume": float(entry.get("vol") or entry.get("volume") or 0),
                        "markets_traded": int(entry.get("marketsTraded") or entry.get("markets_traded") or 0),
                        "win_rate": float(entry.get("winRate") or entry.get("win_rate") or 0),
                        "rank": int(entry.get("rank") or (len(results) + 1)),
                        "is_watched": address.lower() in self.watched_wallets,
                    })
            return results

    async def get_trader_profile(self, address: str) -> Dict[str, Any]:
        """Get detailed profile for a single trader."""
        async with PolymarketClient() as client:
            wallet = await client.get_wallet_profile(address)
            trades = await client.get_user_trades(address, limit=50)

            recent_trades = []
            for t in trades[:20]:
                recent_trades.append({
                    "market": t.get("title") or t.get("question") or t.get("market") or "",
                    "side": t.get("side") or t.get("type") or "BUY",
                    "size": float(t.get("size") or t.get("amount") or 0),
                    "price": float(t.get("price") or 0),
                    "timestamp": t.get("timestamp") or t.get("createdAt") or "",
                })

            # Compute and cache specialization
            spec = await self.analyze_wallet_specialization(address, trades)
            self._wallet_specializations[address.lower()] = spec
            self._save_watchlist()

            return {
                "address": address,
                "total_trades": wallet.get("total_trades", 0),
                "unique_markets": wallet.get("unique_markets", 0),
                "total_volume_usd": wallet.get("total_volume_usd", 0),
                "win_rate": wallet.get("win_rate"),
                "recent_trades": recent_trades,
                "is_watched": address.lower() in self.watched_wallets,
                "specialization": spec,
            }

    async def check_watched_traders(self) -> List[Dict[str, Any]]:
        """
        Check watched traders for new trades. Returns list of new trades found.
        Called periodically by the scheduler.
        """
        if not self.watched_wallets:
            return []

        new_trades = []
        logger.info(f"Checking {len(self.watched_wallets)} watched traders...")

        async with PolymarketClient() as client:
            for address in list(self.watched_wallets):
                try:
                    trades = await client.get_user_trades(address, limit=20)
                    if not trades:
                        continue

                    # Build specialization lazily if we don't have it yet
                    addr_lower = address.lower()
                    if addr_lower not in self._wallet_specializations:
                        spec = await self.analyze_wallet_specialization(address, trades)
                        self._wallet_specializations[addr_lower] = spec
                        logger.debug(f"Built specialization for {address[:12]}...: {spec.get('top_category')} ({spec.get('top_pct')}%)")

                    spec = self._wallet_specializations.get(addr_lower, {})

                    last_seen = self._last_seen_trades.get(address)
                    latest_ts = None

                    for trade in trades:
                        ts = trade.get("timestamp") or trade.get("createdAt") or ""
                        if isinstance(ts, str) and ts:
                            if last_seen and ts <= last_seen:
                                break
                            if not latest_ts or ts > latest_ts:
                                latest_ts = ts

                            # Classify this trade's category
                            market_question = trade.get("title") or trade.get("question") or trade.get("market") or "Unknown"
                            trade_category = classify_market_category(market_question)

                            # Is it in the wallet's specialty?
                            top_cat = spec.get("top_category", "unknown")
                            top_pct = spec.get("top_pct", 0)
                            in_specialty = trade_category == top_cat and top_pct >= 40

                            # This is a new trade
                            new_trade = {
                                "trader": address,
                                "market": market_question,
                                "side": trade.get("side") or "BUY",
                                "size": float(trade.get("size") or trade.get("amount") or 0),
                                "price": float(trade.get("price") or 0),
                                "usdcSize": float(trade.get("usdcSize") or 0),
                                "timestamp": ts,
                                "category": trade_category,
                                "in_specialty": in_specialty,
                                "wallet_specialty": top_cat,
                                "wallet_specialty_pct": top_pct,
                            }
                            new_trades.append(new_trade)

                            # Send notification
                            try:
                                notifier = get_notifier()
                                await notifier.notify_smart_money(
                                    trader=address,
                                    trade=new_trade,
                                )
                            except Exception as e:
                                logger.debug(f"Smart money notification failed: {e}")

                    if latest_ts:
                        self._last_seen_trades[address] = latest_ts

                except Exception as e:
                    logger.error(f"Error checking watched trader {address[:12]}...: {e}")
                    continue

        if new_trades:
            self._save_watchlist()
            logger.info(f"Found {len(new_trades)} new trades from watched traders")

        return new_trades


# Singleton
tracker = LeaderboardTracker()
