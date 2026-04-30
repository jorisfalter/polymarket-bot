"""
Polymarket Insider Detector - API Server

A FastAPI application that monitors Polymarket for suspicious trading patterns
that may indicate insider information.

Run with: uvicorn backend.main:app --reload
"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from contextlib import asynccontextmanager
import uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings
from .models import (
    SuspiciousTrade, InsiderAlert, DashboardStats,
    AlertSeverity, WalletProfile, WalletCluster
)
from .polymarket_client import PolymarketClient
from .detectors import detector
from .notifications import get_notifier
from .backtester import backtester, KNOWN_CASES
from .leaderboard import tracker
from .copy_trader import copy_trader, CopyTradeConfig, CopyMode
from .paper_trader import paper_trader
from .trade_tracker import trade_tracker
from .auto_seller import auto_seller
from .strategy_engine import strategy_engine
from .trade_journal import journal as trade_journal
from .ai_agent import ai_agent
from .daily_summary import run_daily_summary


def _get_trade_key(trade) -> str:
    """
    Generate a composite key for trade deduplication.
    Uses wallet + market + price + shares + timestamp instead of unreliable trade IDs.
    """
    return f"{trade.trader_address}:{trade.market_id}:{trade.price:.2f}:{trade.shares:.2f}:{trade.timestamp.isoformat()}"


# Set to track seen trade keys (more reliable than trade IDs)
seen_trade_keys: set = set()

# In-memory storage (replace with DB in production)
alerts_store: List[InsiderAlert] = []
suspicious_trades_store: List[SuspiciousTrade] = []
wallet_clusters_store: List[WalletCluster] = []

# Activity log - stores ALL analyzed trades with their signal breakdown
activity_log: List[dict] = []


async def _prioritize_trades(client: PolymarketClient, trades: List[dict]) -> List[dict]:
    """
    Score and sort trades by priority for analysis.
    Fresh wallets and extreme odds get boosted to the top so they aren't
    drowned out by whale activity.
    """
    if not settings.fresh_wallet_priority_boost:
        return trades

    # Collect unique wallets and batch-check trade counts
    unique_wallets = list(set(
        t.get("maker", "") for t in trades if t.get("maker") and t.get("maker") != "unknown"
    ))
    logger.info(f"Checking trade counts for {len(unique_wallets)} unique wallets")

    wallet_trade_counts: dict = {}
    batch_size = 20
    for i in range(0, len(unique_wallets), batch_size):
        batch = unique_wallets[i:i + batch_size]
        results = await asyncio.gather(
            *[client.get_wallet_trade_count(addr) for addr in batch],
            return_exceptions=True
        )
        for addr, count in zip(batch, results):
            wallet_trade_counts[addr] = count if isinstance(count, int) else -1

    # Score each trade
    for trade in trades:
        priority = 0
        wallet = trade.get("maker", "")
        trade_count = wallet_trade_counts.get(wallet, -1)

        # Fresh wallet boost
        if 0 <= trade_count < 5:
            priority += 500
        elif 0 <= trade_count < 10:
            priority += 200

        # Extreme odds boost
        price = float(trade.get("price", 50) or 50)
        if price <= 1:
            price = price * 100
        if price < 10:
            priority += 300
        elif price < 20:
            priority += 150

        # Notional as tiebreaker (scaled down)
        notional = float(trade.get("notional_usd", 0) or 0)
        priority += min(notional / 100, 100)  # Cap at 100

        trade["_priority"] = priority
        trade["_wallet_trade_count"] = trade_count

    trades.sort(key=lambda t: t.get("_priority", 0), reverse=True)
    fresh_count = sum(1 for t in trades if t.get("_priority", 0) >= 200)
    logger.info(f"Priority scoring done: {fresh_count} high-priority trades (fresh/extreme odds)")
    return trades


async def _batch_fetch_profiles(
    client: PolymarketClient, addresses: List[str]
) -> Dict[str, dict]:
    """Pre-fetch wallet profiles in parallel batches."""
    cache: Dict[str, dict] = {}
    batch_size = 10
    for i in range(0, len(addresses), batch_size):
        batch = addresses[i:i + batch_size]
        results = await asyncio.gather(
            *[client.get_wallet_profile(addr) for addr in batch],
            return_exceptions=True
        )
        for addr, result in zip(batch, results):
            if isinstance(result, dict):
                cache[addr] = result
            else:
                cache[addr] = {"address": addr, "total_trades": 0, "unique_markets": 0, "total_volume_usd": 0}
    return cache


def _build_market_data(trade_data: dict, fetched_market: Optional[dict] = None) -> dict:
    """Build normalized market_data dict from trade info and/or fetched market."""
    market_id = trade_data.get("market") or trade_data.get("conditionId") or trade_data.get("marketId")

    if trade_data.get("market_question"):
        return {
            "id": market_id or "unknown",
            "slug": trade_data.get("market_slug", ""),
            "question": trade_data.get("market_question", "Unknown"),
            "yes_price": float(trade_data.get("price", 50)),
            "no_price": 100 - float(trade_data.get("price", 50)),
            "volume_24h": 0, "volume_total": 0, "liquidity": 0, "is_active": True,
        }

    if fetched_market:
        return {
            "id": fetched_market.get("id", market_id),
            "slug": fetched_market.get("slug", ""),
            "question": fetched_market.get("question", "Unknown"),
            "yes_price": float(fetched_market.get("outcomePrices", [50, 50])[0] if fetched_market.get("outcomePrices") else 50),
            "no_price": float(fetched_market.get("outcomePrices", [50, 50])[1] if fetched_market.get("outcomePrices") else 50),
            "volume_24h": float(fetched_market.get("volume24hr", 0) or 0),
            "volume_total": float(fetched_market.get("volume", 0) or 0),
            "liquidity": float(fetched_market.get("liquidity", 0) or 0),
            "is_active": fetched_market.get("active", True),
        }

    return {
        "id": market_id or "unknown",
        "slug": "",
        "question": trade_data.get("title", trade_data.get("description", "Unknown Market")),
        "yes_price": float(trade_data.get("price", 50)),
        "no_price": 100 - float(trade_data.get("price", 50)),
        "volume_24h": 0, "volume_total": 0, "liquidity": 0, "is_active": True,
    }


async def _analyze_and_record(
    trade_data: dict,
    wallet_profile: dict,
    market_data: dict,
) -> tuple:
    """Run detection on a single trade, record to activity log. Returns (suspicious, new_alert_bool)."""
    trader_address = trade_data.get("maker", "")
    suspicious, signals = detector.analyze_trade_detailed(
        trade_data=trade_data,
        wallet_profile=wallet_profile,
        market_data=market_data,
    )

    activity_entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.utcnow().isoformat(),
        "market": market_data.get("question", "Unknown")[:80],
        "market_slug": market_data.get("slug", ""),
        "trader": trader_address[:12] + "...",
        "trader_full": trader_address,
        "side": trade_data.get("side", "BUY"),
        "notional_usd": trade_data.get("notional_usd", 0),
        "price": float(trade_data.get("price", 0)),
        "shares": float(trade_data.get("size", 0)),
        "signals": signals,
        "total_score": sum(s["score"] for s in signals),
        "is_alert": suspicious is not None,
        "wallet_trades": wallet_profile.get("total_trades", 0),
        "wallet_markets": wallet_profile.get("unique_markets", 0),
    }

    existing_traders = [(a["trader_full"], a["market"]) for a in activity_log[-100:]]
    if (trader_address, activity_entry["market"]) not in existing_traders:
        activity_log.insert(0, activity_entry)
        while len(activity_log) > 500:
            activity_log.pop()

    new_alert = False
    if suspicious:
        alert = InsiderAlert(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            suspicious_trade=suspicious,
            market=market_data,
            insider_probability=suspicious.suspicion_score / 100,
            narrative=_generate_narrative(suspicious),
        )
        trade_key = _get_trade_key(suspicious.trade)
        if trade_key not in seen_trade_keys:
            seen_trade_keys.add(trade_key)
            alerts_store.insert(0, alert)
            suspicious_trades_store.insert(0, suspicious)
            new_alert = True
            logger.info(f"🚨 New alert: {suspicious.severity.value.upper()} - {suspicious.flags[0] if suspicious.flags else 'Suspicious'}")
            try:
                notifier = get_notifier()
                await notifier.notify(suspicious)
            except Exception as e:
                logger.error(f"Notification failed: {e}")

            # Feed HIGH/CRITICAL alerts to strategy engine
            if suspicious.severity in (AlertSeverity.HIGH, AlertSeverity.CRITICAL):
                asyncio.create_task(strategy_engine.on_insider_alert(suspicious))

        while len(alerts_store) > 500:
            alerts_store.pop()
        if len(seen_trade_keys) > 10000:
            seen_trade_keys.clear()
            for a in alerts_store:
                seen_trade_keys.add(_get_trade_key(a.suspicious_trade.trade))

    return suspicious, new_alert


async def scan_for_suspicious_activity():
    """
    Background task that periodically scans for suspicious trades.

    Pipeline:
    1. Fetch large trades (now 500 from each source)
    2. Priority-score trades (fresh wallets + extreme odds first)
    3. Batch-fetch wallet profiles
    4. Analyze top N trades (configurable, default 200)
    5. Deep scan hot markets with multiple alerts or many fresh wallets
    """
    logger.info("🔍 Scanning for suspicious activity...")

    try:
        async with PolymarketClient() as client:
            # Step 1: Fetch trades
            large_trades = await client.get_recent_large_trades(
                min_notional=settings.min_notional_alert,
                hours=settings.alert_window_hours,
            )
            logger.info(f"Found {len(large_trades)} large trades to analyze")

            # Step 2: Priority scoring
            large_trades = await _prioritize_trades(client, large_trades)

            # Step 3: Select top N and batch-fetch profiles
            analysis_cap = settings.scan_analysis_cap
            trades_to_analyze = large_trades[:analysis_cap]
            unique_wallets = list(set(
                t.get("maker", "") for t in trades_to_analyze
                if t.get("maker") and t.get("maker") != "unknown"
            ))
            logger.info(f"Batch-fetching profiles for {len(unique_wallets)} wallets")
            profile_cache = await _batch_fetch_profiles(client, unique_wallets)

            # Step 4: Analyze
            new_alerts_count = 0
            duplicate_count = 0
            market_alert_counts: Dict[str, int] = {}
            market_wallet_sets: Dict[str, set] = {}

            for trade_data in trades_to_analyze:
                try:
                    trader_address = trade_data.get("maker")
                    if not trader_address or trader_address == "unknown":
                        continue

                    wallet_profile = profile_cache.get(trader_address)
                    if not wallet_profile:
                        wallet_profile = await client.get_wallet_profile(trader_address)
                        profile_cache[trader_address] = wallet_profile

                    market_id = trade_data.get("market") or trade_data.get("conditionId") or trade_data.get("marketId")

                    market_data = _build_market_data(trade_data)
                    if not trade_data.get("market_question") and market_id:
                        fetched_market = await client.get_market(market_id)
                        if fetched_market:
                            market_data = _build_market_data(trade_data, fetched_market)

                    suspicious, new_alert = await _analyze_and_record(trade_data, wallet_profile, market_data)

                    if new_alert:
                        new_alerts_count += 1
                    elif suspicious:
                        duplicate_count += 1

                    # Track market activity for deep scan
                    if market_id:
                        if suspicious:
                            market_alert_counts[market_id] = market_alert_counts.get(market_id, 0) + 1
                        market_wallet_sets.setdefault(market_id, set()).add(trader_address)

                except Exception as e:
                    logger.error(f"Error analyzing trade: {e}")
                    continue

            # Step 5: Deep scan hot markets
            if settings.deep_scan_enabled:
                hot_markets = []
                for mid in set(list(market_alert_counts.keys()) + list(market_wallet_sets.keys())):
                    alerts = market_alert_counts.get(mid, 0)
                    wallets = len(market_wallet_sets.get(mid, set()))
                    if alerts >= 1 or wallets >= 3:
                        hot_markets.append((mid, alerts + wallets))

                hot_markets.sort(key=lambda x: x[1], reverse=True)
                hot_markets = hot_markets[:settings.deep_scan_max_markets]

                if hot_markets:
                    logger.info(f"🔥 Deep scanning {len(hot_markets)} hot markets")

                for mid, _ in hot_markets:
                    try:
                        deep_trades = await client.get_market_trades_deep(mid, limit=500)
                        analyzed_wallets = set(profile_cache.keys())
                        fresh_trades = [
                            t for t in deep_trades
                            if t.get("maker") not in analyzed_wallets
                        ]
                        logger.info(f"Deep scan {mid[:16]}...: {len(deep_trades)} trades, {len(fresh_trades)} new wallets")

                        # Batch-check which are fresh
                        new_wallets = list(set(t["maker"] for t in fresh_trades))[:50]
                        new_counts: Dict[str, int] = {}
                        for i in range(0, len(new_wallets), 20):
                            batch = new_wallets[i:i+20]
                            results = await asyncio.gather(
                                *[client.get_wallet_trade_count(addr) for addr in batch],
                                return_exceptions=True,
                            )
                            for addr, count in zip(batch, results):
                                new_counts[addr] = count if isinstance(count, int) else -1

                        for trade_data in fresh_trades:
                            wallet = trade_data["maker"]
                            count = new_counts.get(wallet, -1)
                            if count < 0 or count >= 10:
                                continue

                            if wallet not in profile_cache:
                                profile_cache[wallet] = await client.get_wallet_profile(wallet)
                            wallet_profile = profile_cache[wallet]

                            market_data = _build_market_data(trade_data)
                            suspicious, new_alert = await _analyze_and_record(trade_data, wallet_profile, market_data)
                            if new_alert:
                                new_alerts_count += 1

                    except Exception as e:
                        logger.error(f"Deep scan error for {mid}: {e}")

            # Detect wallet clusters (coordinated trading)
            clusters = detector.detect_wallet_clusters(large_trades)
            for cluster in clusters:
                if cluster.cluster_id not in [c.cluster_id for c in wallet_clusters_store]:
                    wallet_clusters_store.insert(0, cluster)
                    logger.info(f"🕸️ Detected wallet cluster: {len(cluster.wallets)} wallets, ${cluster.total_volume:,.0f}")

            if duplicate_count > 0:
                logger.info(f"Skipped {duplicate_count} duplicate trades")

    except Exception as e:
        logger.error(f"Scan error: {e}")

    logger.info(f"✅ Scan complete. Total alerts: {len(alerts_store)}, New this scan: {new_alerts_count}")

    # Feed new alerts to AI agent for next cycle
    if new_alerts_count > 0:
        recent = [a for a in alerts_store[:new_alerts_count]]
        ai_agent.feed_alerts(recent)


def _generate_narrative(suspicious: SuspiciousTrade) -> str:
    """Generate a human-readable explanation of why this trade is suspicious"""
    wallet = suspicious.wallet
    trade = suspicious.trade

    parts = []

    # Wallet context
    if wallet.is_fresh_wallet:
        parts.append(f"A low-activity wallet ({wallet.total_trades} total trades)")
    else:
        parts.append(f"Wallet {trade.trader_address[:10]}...")

    # Trade action
    parts.append(f"placed a ${trade.notional_usd:,.0f} {trade.side} bet")
    parts.append(f"on '{trade.market_question[:50]}...'")

    # Price context
    if trade.price < 20:
        potential_return = ((100 - trade.price) / trade.price) * 100
        parts.append(f"at just {trade.price:.1f}¢ ({potential_return:.0f}% potential return)")
    else:
        parts.append(f"at {trade.price:.1f}¢")

    # Why suspicious
    if len(suspicious.flags) > 1:
        parts.append(f". Flagged for: {', '.join(suspicious.flags[1:])}")

    return " ".join(parts)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for the app"""
    # Startup
    logger.info("🚀 Starting Polymarket Insider Detector")

    # Start scheduler for periodic scans
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scan_for_suspicious_activity,
        'interval',
        minutes=5,  # Scan every 5 minutes
        id='scan_job'
    )
    scheduler.add_job(
        tracker.check_watched_traders,
        'interval',
        minutes=5,  # Check watched traders every 5 minutes
        id='watch_job'
    )
    scheduler.add_job(
        paper_trader.check_and_copy_new_trades,
        'interval',
        minutes=2,  # Check for copy trades every 2 minutes
        id='paper_copy_job'
    )
    scheduler.add_job(
        paper_trader.update_prices,
        'interval',
        minutes=10,  # Update prices every 10 minutes
        id='paper_price_job'
    )
    scheduler.add_job(
        trade_tracker.check_targets,
        'interval',
        seconds=10,  # Check trade targets every 10 seconds
        id='trade_monitor_job'
    )
    scheduler.add_job(
        strategy_engine.run_cycle,
        'interval',
        minutes=2,  # Run strategy engine every 2 minutes
        id='strategy_cycle_job'
    )
    scheduler.add_job(
        ai_agent.run_cycle,
        'interval',
        minutes=15,  # AI agent thinks every 15 minutes
        id='ai_agent_job'
    )
    scheduler.add_job(
        run_daily_summary,
        'cron',
        hour=9, minute=0,  # Daily at 09:00 UTC — social-media-ready recap
        id='daily_summary_job'
    )
    scheduler.start()

    # Initial scan
    asyncio.create_task(scan_for_suspicious_activity())

    yield

    # Shutdown
    scheduler.shutdown()
    logger.info("👋 Shutting down")


# Create FastAPI app
app = FastAPI(
    title="Polymarket Insider Detector",
    description="Track unusual bets that hint at insider information",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== API ENDPOINTS ====================

@app.get("/api/alerts", response_model=List[dict])
async def get_alerts(
    severity: Optional[AlertSeverity] = None,
    limit: int = Query(50, le=200),
    offset: int = 0
):
    """Get recent suspicious activity alerts"""
    filtered = alerts_store

    if severity:
        filtered = [a for a in filtered if a.suspicious_trade.severity == severity]

    # Convert to dict for response
    result = []
    for alert in filtered[offset:offset + limit]:
        result.append({
            "id": alert.id,
            "created_at": alert.created_at.isoformat(),
            "severity": alert.suspicious_trade.severity.value,
            "suspicion_score": alert.suspicious_trade.suspicion_score,
            "flags": alert.suspicious_trade.flags,
            "narrative": alert.narrative,
            "trade": {
                "market_question": alert.suspicious_trade.trade.market_question,
                "market_slug": alert.suspicious_trade.trade.market_slug,
                "trader": alert.suspicious_trade.trade.trader_address,
                "side": alert.suspicious_trade.trade.side,
                "outcome": alert.suspicious_trade.trade.outcome,
                "shares": alert.suspicious_trade.trade.shares,
                "price": alert.suspicious_trade.trade.price,
                "notional_usd": alert.suspicious_trade.trade.notional_usd,
                "timestamp": alert.suspicious_trade.trade.timestamp.isoformat(),
                "potential_return_pct": alert.suspicious_trade.potential_return_pct
            },
            "wallet": {
                "address": alert.suspicious_trade.wallet.address,
                "total_trades": alert.suspicious_trade.wallet.total_trades,
                "unique_markets": alert.suspicious_trade.wallet.unique_markets,
                "total_volume_usd": alert.suspicious_trade.wallet.total_volume_usd,
                "win_rate": alert.suspicious_trade.wallet.win_rate,
                "is_fresh_wallet": alert.suspicious_trade.wallet.is_fresh_wallet,
                "is_whale": alert.suspicious_trade.wallet.is_whale,
                "suspicion_score": alert.suspicious_trade.wallet.suspicion_score
            },
            "insider_probability": alert.insider_probability
        })

    return result


@app.get("/api/stats")
async def get_stats():
    """Get dashboard statistics"""
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=24)

    recent_alerts = [a for a in alerts_store if a.created_at >= cutoff]
    critical_alerts = [a for a in recent_alerts if a.suspicious_trade.severity == AlertSeverity.CRITICAL]

    total_volume = sum(a.suspicious_trade.trade.notional_usd for a in recent_alerts)

    # Get unique suspicious markets
    markets = list(set(a.suspicious_trade.trade.market_question[:50] for a in recent_alerts))[:5]

    # Get most suspicious wallets
    wallet_scores = {}
    for alert in recent_alerts:
        addr = alert.suspicious_trade.wallet.address
        wallet_scores[addr] = wallet_scores.get(addr, 0) + alert.suspicious_trade.suspicion_score

    top_wallets = sorted(wallet_scores.items(), key=lambda x: x[1], reverse=True)[:5]

    avg_score = (
        sum(a.suspicious_trade.suspicion_score for a in recent_alerts) / len(recent_alerts)
        if recent_alerts else 0
    )

    return {
        "total_alerts_24h": len(recent_alerts),
        "critical_alerts_24h": len(critical_alerts),
        "total_suspicious_volume_24h": total_volume,
        "top_suspicious_markets": markets,
        "most_active_suspicious_wallets": [w[0][:12] + "..." for w in top_wallets],
        "avg_suspicion_score": round(avg_score, 1),
        "wallet_clusters_detected": len(wallet_clusters_store),
        "last_scan": now.isoformat()
    }


@app.get("/api/wallet/{address}")
async def get_wallet_analysis(address: str):
    """Get detailed analysis for a specific wallet"""
    async with PolymarketClient() as client:
        profile = await client.get_wallet_profile(address)

        # Get alerts for this wallet
        wallet_alerts = [
            a for a in alerts_store
            if a.suspicious_trade.wallet.address.lower() == address.lower()
        ]

        return {
            "profile": profile,
            "alert_count": len(wallet_alerts),
            "recent_alerts": [
                {
                    "created_at": a.created_at.isoformat(),
                    "severity": a.suspicious_trade.severity.value,
                    "market": a.suspicious_trade.trade.market_question,
                    "flags": a.suspicious_trade.flags
                }
                for a in wallet_alerts[:10]
            ]
        }


@app.get("/api/clusters")
async def get_wallet_clusters():
    """Get detected wallet clusters (coordinated trading)"""
    return [
        {
            "cluster_id": c.cluster_id,
            "wallets": c.wallets,
            "wallet_count": len(c.wallets),
            "correlation_score": c.correlation_score,
            "shared_markets": c.shared_markets,
            "total_volume": c.total_volume,
            "first_detected": c.first_coordinated_trade.isoformat()
        }
        for c in wallet_clusters_store[:20]
    ]


@app.post("/api/scan")
async def trigger_scan():
    """Manually trigger a scan for suspicious activity"""
    asyncio.create_task(scan_for_suspicious_activity())
    return {"status": "Scan started"}


@app.get("/api/activity")
async def get_activity_log(limit: int = Query(100, le=500)):
    """
    Get ALL analyzed trades with their individual signal breakdown.
    This helps understand what the detector is seeing even when
    trades don't meet the alert threshold.
    """
    return activity_log[:limit]


@app.get("/api/activity/stats")
async def get_activity_stats():
    """Get statistics about recent activity for parameter tuning"""
    if not activity_log:
        return {"message": "No activity yet", "total_scanned": 0}

    # Analyze signal distribution
    signal_counts = {}
    signal_totals = {}

    for entry in activity_log:
        for signal in entry.get("signals", []):
            name = signal["signal"]
            score = signal["score"]
            if name not in signal_counts:
                signal_counts[name] = 0
                signal_totals[name] = 0
            if score > 0:
                signal_counts[name] += 1
                signal_totals[name] += score

    # Calculate which signals fire most often
    signal_stats = []
    for name in signal_counts:
        signal_stats.append({
            "signal": name,
            "times_triggered": signal_counts[name],
            "avg_score_when_triggered": round(signal_totals[name] / signal_counts[name], 1) if signal_counts[name] > 0 else 0,
            "trigger_rate": f"{(signal_counts[name] / len(activity_log) * 100):.1f}%"
        })

    signal_stats.sort(key=lambda x: x["times_triggered"], reverse=True)

    # Score distribution
    scores = [e["total_score"] for e in activity_log]
    alerts = [e for e in activity_log if e["is_alert"]]

    return {
        "total_scanned": len(activity_log),
        "alerts_generated": len(alerts),
        "alert_rate": f"{(len(alerts) / len(activity_log) * 100):.1f}%" if activity_log else "0%",
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "max_score": max(scores) if scores else 0,
        "min_score": min(scores) if scores else 0,
        "signal_breakdown": signal_stats,
        "recent_markets": list(set(e["market"][:50] for e in activity_log[:20]))
    }


@app.get("/api/markets/suspicious")
async def get_suspicious_markets(limit: int = 10):
    """Get markets with the most suspicious activity"""
    market_scores = {}

    for alert in alerts_store:
        market = alert.suspicious_trade.trade.market_question
        if market not in market_scores:
            market_scores[market] = {
                "question": market,
                "slug": alert.suspicious_trade.trade.market_slug,
                "alert_count": 0,
                "total_suspicious_volume": 0,
                "max_severity": "low",
                "latest_alert": None
            }

        market_scores[market]["alert_count"] += 1
        market_scores[market]["total_suspicious_volume"] += alert.suspicious_trade.trade.notional_usd

        # Track highest severity
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        current = severity_order.get(market_scores[market]["max_severity"], 0)
        new = severity_order.get(alert.suspicious_trade.severity.value, 0)
        if new > current:
            market_scores[market]["max_severity"] = alert.suspicious_trade.severity.value

        market_scores[market]["latest_alert"] = alert.created_at.isoformat()

    sorted_markets = sorted(
        market_scores.values(),
        key=lambda x: (x["alert_count"], x["total_suspicious_volume"]),
        reverse=True
    )

    return sorted_markets[:limit]


# ==================== BACKTEST ENDPOINTS ====================

@app.get("/api/backtest/cases")
async def get_backtest_cases():
    """Get all known insider trading cases for backtesting"""
    return [
        {
            "id": case["id"],
            "name": case["name"],
            "description": case["description"],
            "expected_min_score": case["expected_min_score"],
            "expected_signals": case["expected_signals"],
        }
        for case in KNOWN_CASES.values()
    ]


@app.post("/api/backtest/case/{case_id}")
async def run_backtest_case(case_id: str):
    """Run backtest for a known insider case"""
    if case_id not in KNOWN_CASES:
        raise HTTPException(status_code=404, detail=f"Unknown case: {case_id}")

    result = await backtester.run_known_case(case_id)
    return {
        "case_id": result.case_id,
        "case_name": result.case_name,
        "market_question": result.market_question,
        "market_id": result.market_id,
        "market_slug": result.market_slug,
        "total_trades": result.total_trades,
        "trades_analyzed": result.trades_analyzed,
        "suspicious_trades": result.suspicious_trades,
        "top_score": result.top_score,
        "expected_min_score": result.expected_min_score,
        "passed": result.passed,
        "error": result.error,
        "duration_seconds": result.duration_seconds,
        # Known insider tracking
        "insider_wallet": result.insider_wallet,
        "insider_name": result.insider_name,
        "insider_found": result.insider_found,
        "insider_score": result.insider_score,
        "insider_rank": result.insider_rank,
    }


@app.post("/api/backtest/market")
async def run_market_backtest(
    condition_id: str = Query(..., description="Market conditionId"),
    question: str = Query("", description="Market question for display"),
    slug: str = Query("", description="Market slug"),
):
    """Backtest a specific market by conditionId"""
    result = await backtester.backtest_market(condition_id, question, slug)
    return {
        "market_question": result.market_question,
        "market_id": result.market_id,
        "market_slug": result.market_slug,
        "total_trades": result.total_trades,
        "trades_analyzed": result.trades_analyzed,
        "suspicious_trades": result.suspicious_trades,
        "top_score": result.top_score,
        "error": result.error,
        "duration_seconds": result.duration_seconds,
    }


@app.get("/api/backtest/search")
async def search_backtest_markets(
    q: str = Query(..., description="Search term"),
    limit: int = Query(20, le=50),
):
    """Search for resolved markets to backtest"""
    results = await backtester.search_resolved_markets(q, limit=limit)
    return results


# ==================== EARNINGS ENDPOINT ====================

EARNINGS_TERMS = [
    "earnings", "revenue", "Q1", "Q2", "Q3", "Q4",
    "EPS", "beat", "miss", "quarterly", "profit",
]

@app.get("/api/markets/earnings")
async def search_earnings_markets(
    limit: int = Query(20, le=50),
):
    """Search for earnings-related markets (resolved, for backtesting)"""
    all_markets = []
    seen_ids = set()

    for term in EARNINGS_TERMS:
        results = await backtester.search_resolved_markets(term, limit=10)
        for m in results:
            mid = m.get("id") or m.get("conditionId")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                all_markets.append(m)

    return all_markets[:limit]


# ==================== LEADERBOARD ENDPOINTS ====================

@app.get("/api/leaderboard")
async def get_leaderboard(
    category: Optional[str] = None,
    time_period: str = Query("all"),
    order_by: str = Query("pnl"),
    limit: int = Query(50, le=100),
):
    """Fetch leaderboard rankings"""
    return await tracker.fetch_leaderboard(
        category=category,
        time_period=time_period,
        order_by=order_by,
        limit=limit,
    )


@app.get("/api/leaderboard/trader/{address}")
async def get_trader_detail(address: str):
    """Get detailed profile for a leaderboard trader"""
    return await tracker.get_trader_profile(address)


@app.post("/api/leaderboard/watch/{address}")
async def watch_trader(address: str):
    """Add a trader to the watchlist"""
    tracker.watch(address)
    return {"status": "watching", "address": address}


@app.delete("/api/leaderboard/watch/{address}")
async def unwatch_trader(address: str):
    """Remove a trader from the watchlist"""
    tracker.unwatch(address)
    return {"status": "unwatched", "address": address}


@app.get("/api/leaderboard/watching")
async def get_watching():
    """Get list of watched wallet addresses"""
    return {"wallets": tracker.get_watching()}


# ==================== COPY TRADING ====================

@app.get("/api/copy-trader/status")
async def get_copy_trader_status():
    """Get copy trader status and recent activity"""
    return copy_trader.get_stats()


@app.post("/api/copy-trader/config")
async def update_copy_trader_config(
    enabled: Optional[bool] = None,
    dry_run: Optional[bool] = None,
    mode: Optional[str] = None,
    fixed_amount: Optional[float] = None,
    max_slippage: Optional[float] = None,
    max_position: Optional[float] = None,
):
    """Update copy trader configuration"""
    if enabled is not None:
        copy_trader.config.enabled = enabled
    if dry_run is not None:
        copy_trader.config.dry_run = dry_run
    if mode is not None:
        copy_trader.config.mode = CopyMode(mode)
    if fixed_amount is not None:
        copy_trader.config.fixed_amount_usd = fixed_amount
    if max_slippage is not None:
        copy_trader.config.max_slippage_pct = max_slippage
    if max_position is not None:
        copy_trader.config.max_position_usd = max_position

    return {
        "enabled": copy_trader.config.enabled,
        "dry_run": copy_trader.config.dry_run,
        "mode": copy_trader.config.mode.value,
        "fixed_amount_usd": copy_trader.config.fixed_amount_usd,
        "max_slippage_pct": copy_trader.config.max_slippage_pct,
        "max_position_usd": copy_trader.config.max_position_usd,
    }


@app.post("/api/copy-trader/simulate")
async def simulate_copy_trading():
    """Run one cycle of copy trading (always in dry-run mode for safety)"""
    # Force dry run for simulation
    original_dry_run = copy_trader.config.dry_run
    copy_trader.config.dry_run = True

    results = await copy_trader.run_copy_cycle()

    copy_trader.config.dry_run = original_dry_run

    return {
        "trades_found": len(results),
        "results": [
            {
                "market": r.market[:60] if r.market else "",
                "side": r.side,
                "original_trader": r.original_trader[:16] + "...",
                "original_price": r.original_price,
                "our_price": r.our_price,
                "original_size_usd": r.original_size_usd,
                "our_size_usd": r.our_size_usd,
                "slippage_pct": r.slippage_pct,
                "would_copy": r.success,
                "skip_reason": r.error,
            }
            for r in results
        ],
    }


# ==================== PAPER TRADING ====================

@app.get("/api/paper-trader/stats")
async def get_paper_trading_stats():
    """Get paper trading statistics and recent trades"""
    return paper_trader.get_stats()


@app.get("/api/paper-trader/positions")
async def get_paper_trading_positions():
    """Get all open paper trading positions"""
    return {"positions": paper_trader.get_open_positions()}


@app.post("/api/paper-trader/scan")
async def scan_for_paper_trades():
    """Manually trigger a scan for new copy trades"""
    new_trades = await paper_trader.check_and_copy_new_trades()
    return {
        "new_trades": len(new_trades),
        "trades": [
            {
                "id": t.id,
                "market": t.market_title[:50],
                "outcome": t.outcome,
                "copied_from": t.copied_from_name,
                "entry_price": t.entry_price,
                "their_entry": t.their_entry_price,
                "position_usd": t.position_usd,
            }
            for t in new_trades
        ],
    }


@app.post("/api/paper-trader/update-prices")
async def update_paper_trade_prices():
    """Update current prices and check for resolved markets"""
    await paper_trader.update_prices()
    return paper_trader.get_stats()


# ==================== TRADE TRACKER ====================

@app.get("/api/trades")
async def get_tracked_trades():
    """Get all tracked trades with current prices"""
    await trade_tracker.update_prices()
    trades = trade_tracker.get_all_trades()
    return {
        "trades": [t.to_dict() for t in trades],
        "stats": trade_tracker.get_stats(),
    }


@app.post("/api/trades")
async def add_tracked_trade(
    market_slug: str = Query(..., description="Market slug from Polymarket URL"),
    token_id: str = Query(..., description="CLOB token ID for the outcome"),
    condition_id: str = Query("", description="Market condition ID"),
    side: str = Query("YES", description="YES or NO"),
    entry_price: float = Query(..., description="Entry price in cents (e.g., 4.0)"),
    target_price: float = Query(..., description="Target sell price in cents"),
    shares: float = Query(..., description="Number of shares"),
    market_question: str = Query("", description="Market question text"),
    auto_sell: bool = Query(True, description="Enable auto-sell at target"),
    notes: str = Query("", description="Optional notes"),
):
    """Add a new trade to track"""
    trade = trade_tracker.add_trade(
        market_slug=market_slug,
        token_id=token_id,
        condition_id=condition_id,
        side=side,
        entry_price=entry_price,
        target_price=target_price,
        shares=shares,
        market_question=market_question,
        auto_sell=auto_sell,
        notes=notes,
    )
    return trade.to_dict()


@app.get("/api/trades/{trade_id}")
async def get_tracked_trade(trade_id: str):
    """Get a specific tracked trade"""
    trade = trade_tracker.get_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade.to_dict()


@app.get("/api/trades/{trade_id}/price")
async def get_trade_price(trade_id: str):
    """Get current price for a tracked trade"""
    trade = trade_tracker.get_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    price = await trade_tracker.fetch_price(trade.token_id)
    if price is not None:
        trade.current_price = price
        trade.updated_at = datetime.utcnow().isoformat()
        trade_tracker._save()

    return {
        "trade_id": trade_id,
        "current_price": trade.current_price,
        "entry_price": trade.entry_price,
        "target_price": trade.target_price,
        "pnl_pct": trade.pnl_pct,
        "progress_pct": trade.progress_pct,
        "target_hit": trade.target_hit,
        "status": trade.status,
        "updated_at": trade.updated_at,
    }


@app.patch("/api/trades/{trade_id}")
async def update_tracked_trade(
    trade_id: str,
    target_price: Optional[float] = None,
    auto_sell: Optional[bool] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None,
):
    """Update a tracked trade"""
    updates = {}
    if target_price is not None:
        updates["target_price"] = target_price
    if auto_sell is not None:
        updates["auto_sell"] = auto_sell
    if status is not None:
        updates["status"] = status
    if notes is not None:
        updates["notes"] = notes

    trade = trade_tracker.update_trade(trade_id, **updates)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade.to_dict()


@app.delete("/api/trades/{trade_id}")
async def delete_tracked_trade(trade_id: str):
    """Remove a trade from tracking"""
    if trade_tracker.delete_trade(trade_id):
        return {"status": "deleted", "trade_id": trade_id}
    raise HTTPException(status_code=404, detail="Trade not found")


@app.post("/api/trades/{trade_id}/sell")
async def execute_trade_sell(trade_id: str, manual: bool = Query(False, description="Mark sold without executing")):
    """
    Execute a sell order for a tracked trade.
    If auto_seller is ready, executes actual sell on Polymarket.
    If manual=True or auto_seller not ready, just marks as sold for tracking.
    """
    trade = trade_tracker.get_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    # If manual mode or auto-seller not ready, just mark as sold
    if manual or not auto_seller.is_ready():
        trade = trade_tracker.update_trade(trade_id, status="sold")
        return {
            "status": "sold",
            "trade_id": trade_id,
            "execution": "manual",
            "final_price": trade.current_price,
            "pnl_usd": trade.pnl_usd,
            "pnl_pct": trade.pnl_pct,
        }

    # Execute actual sell
    result = await auto_seller.execute_sell(
        trade_id=trade_id,
        token_id=trade.token_id,
        shares=trade.shares,
        min_price=None,  # Market order
    )

    if result.success:
        trade = trade_tracker.update_trade(
            trade_id,
            status="sold",
            notes=f"{trade.notes} | Sold at {result.price*100:.2f}¢ (Order: {result.order_id})"
        )
        return {
            "status": "sold",
            "trade_id": trade_id,
            "execution": "auto",
            "order_id": result.order_id,
            "shares_sold": result.shares_sold,
            "price": result.price * 100,  # Convert to cents
            "pnl_usd": trade.pnl_usd,
            "pnl_pct": trade.pnl_pct,
        }
    else:
        raise HTTPException(status_code=500, detail=f"Sell failed: {result.error}")


@app.get("/api/trades/auto-seller/status")
async def get_auto_seller_status():
    """Get auto-seller status and configuration."""
    return auto_seller.get_status()


@app.get("/api/trades/search/markets")
async def search_markets_for_tracking(
    q: str = Query(..., description="Search query"),
    limit: int = Query(10, le=20),
):
    """Search for markets to add for tracking"""
    markets = await trade_tracker.search_markets(q, limit)
    return [
        {
            "slug": m.get("slug", ""),
            "question": m.get("question", ""),
            "condition_id": m.get("conditionId", ""),
            "clob_token_ids": m.get("clobTokenIds", []),
            "outcomes": m.get("outcomes", ["Yes", "No"]),
            "outcome_prices": m.get("outcomePrices", []),
        }
        for m in markets
    ]


@app.get("/api/trades/lookup/{slug}")
async def lookup_market_by_slug(slug: str):
    """Look up market details by slug"""
    market = await trade_tracker.lookup_market(slug)
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    return {
        "slug": market.get("slug", ""),
        "question": market.get("question", ""),
        "condition_id": market.get("conditionId", ""),
        "clob_token_ids": market.get("clobTokenIds", []),
        "outcomes": market.get("outcomes", ["Yes", "No"]),
        "outcome_prices": market.get("outcomePrices", []),
        "volume_24h": market.get("volume24hr", 0),
        "liquidity": market.get("liquidity", 0),
    }


# Serve frontend
# ==================== STRATEGY ENGINE ====================

@app.get("/api/strategy/status")
async def get_strategy_status():
    """Get strategy engine status, risk limits, and current positions."""
    return strategy_engine.get_status()


@app.get("/api/strategy/journal")
async def get_strategy_journal(limit: int = Query(100, le=500)):
    """Get full trade journal history."""
    return trade_journal.get_history(limit)


@app.get("/api/strategy/performance")
async def get_strategy_performance():
    """Get P&L summary by strategy."""
    return trade_journal.get_performance()


# ==================== AI AGENT ====================

@app.get("/api/agent/status")
async def get_agent_status():
    """Get AI agent status, portfolio, and last thinking."""
    return ai_agent.get_status()


@app.get("/api/agent/thinking")
async def get_agent_thinking(limit: int = Query(50, le=200)):
    """Get the agent's thinking journal."""
    return ai_agent.get_thinking_history(limit)


@app.get("/api/agent/theses")
async def get_agent_theses():
    """Get the agent's thesis board."""
    return ai_agent.theses


@app.post("/api/agent/run")
async def trigger_agent_cycle():
    """Manually trigger one agent cycle."""
    await ai_agent.run_cycle()
    return {"ok": True, "thinking": ai_agent._thinking_history[-1] if ai_agent._thinking_history else None}


@app.post("/api/agent/daily-summary")
async def trigger_daily_summary():
    """Manually trigger the daily summary (Telegram + archive)."""
    from .daily_summary import generate_daily_summary
    await run_daily_summary()
    return {"ok": True, "summary": generate_daily_summary()}


@app.get("/api/agent/journal")
async def get_agent_journal(limit: int = Query(50, le=500)):
    """Recent ENTER/EXIT entries from the trade journal (most recent first)."""
    from .trade_journal import journal
    history = journal.get_history(limit=limit)
    enters = [e for e in history if e.get("action") == "ENTER"][:limit]
    exits = [e for e in history if e.get("action") == "EXIT"][:limit]
    return {
        "enters": enters,
        "exits": exits,
        "performance": journal.get_performance(),
    }


@app.get("/api/agent/strategy-summary")
async def get_agent_strategy_summary():
    """Per-strategy P&L breakdown from the journal."""
    from .trade_journal import journal
    perf = journal.get_performance()
    by_strategy = perf.get("by_strategy", {})
    # Add open position counts per strategy
    open_by_strategy: Dict[str, int] = {}
    for p in journal.get_open_positions():
        s = p.get("strategy", "unknown")
        open_by_strategy[s] = open_by_strategy.get(s, 0) + 1
    return {
        "totals": {k: v for k, v in perf.items() if k != "by_strategy"},
        "by_strategy": [
            {
                "name": name,
                "pnl": stats["pnl"],
                "trades": stats["trades"],
                "wins": stats["wins"],
                "win_rate": (stats["wins"] / stats["trades"]) if stats["trades"] else 0,
                "open_positions": open_by_strategy.get(name, 0),
            }
            for name, stats in by_strategy.items()
        ],
    }


@app.get("/api/agent/daily-summary")
async def get_daily_summary_data():
    """Read-only: return the same data the daily summary cron job would format."""
    from .daily_summary import generate_daily_summary
    return generate_daily_summary()


@app.get("/api/intel/newsletters")
async def get_newsletters():
    """Recent newsletter emails (Matt Levine, EventWaves, etc.) pulled from Gmail."""
    from .intel_feeds import fetch_gmail_newsletters
    items = await fetch_gmail_newsletters()
    return items


# Manual research ideas inbox — paste a Matt Levine excerpt or your own thesis,
# the agent picks it up next cycle. File-backed so it survives restarts.
import json as _json
RESEARCH_IDEAS_PATH = Path(__file__).parent.parent / "data" / "research_ideas.jsonl"


@app.get("/api/research/ideas")
async def list_research_ideas(limit: int = Query(50, le=200)):
    """List manually-added research ideas, most recent first."""
    if not RESEARCH_IDEAS_PATH.exists():
        return []
    items = []
    for line in RESEARCH_IDEAS_PATH.read_text().strip().split("\n"):
        if line:
            try:
                items.append(_json.loads(line))
            except _json.JSONDecodeError:
                continue
    items.reverse()
    return items[:limit]


@app.post("/api/research/ideas")
async def add_research_idea(payload: Dict):
    """Append a research idea. Body: {title, source, body, tags?}."""
    title = (payload.get("title") or "").strip()[:200]
    body = (payload.get("body") or "").strip()[:20000]
    if not title or not body:
        return {"ok": False, "error": "title and body required"}
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "title": title,
        "source": (payload.get("source") or "manual").strip()[:100],
        "tags": payload.get("tags") or [],
        "body": body,
    }
    RESEARCH_IDEAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESEARCH_IDEAS_PATH, "a") as f:
        f.write(_json.dumps(entry) + "\n")
    return {"ok": True, "entry": entry}


@app.delete("/api/research/ideas/{ts}")
async def delete_research_idea(ts: str):
    """Delete an idea by timestamp."""
    if not RESEARCH_IDEAS_PATH.exists():
        return {"ok": False}
    lines = RESEARCH_IDEAS_PATH.read_text().strip().split("\n")
    kept = []
    for line in lines:
        if not line:
            continue
        try:
            e = _json.loads(line)
            if e.get("timestamp") != ts:
                kept.append(line)
        except _json.JSONDecodeError:
            kept.append(line)
    RESEARCH_IDEAS_PATH.write_text("\n".join(kept) + ("\n" if kept else ""))
    return {"ok": True}


@app.get("/agent")
async def serve_agent():
    return FileResponse(
        "frontend/agent.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/strategy")
async def serve_strategy():
    return FileResponse(
        "frontend/strategy.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/")
async def serve_frontend():
    return FileResponse(
        "frontend/index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/copy")
async def serve_copy_trading():
    return FileResponse(
        "frontend/copy.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/trades")
async def serve_trades():
    return FileResponse(
        "frontend/trades.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/research")
async def serve_research():
    return FileResponse(
        "frontend/research.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/playbook")
async def serve_playbook():
    return FileResponse(
        "frontend/playbook.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/stocks")
async def serve_stocks():
    return FileResponse(
        "frontend/stocks.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/btc")
async def serve_btc():
    return FileResponse(
        "frontend/btc.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/api/stocks/politician-trades")
async def get_politician_trades(days: int = Query(30, le=90)):
    """Recent congressional stock disclosures (House + Senate)."""
    from .stocks_data import fetch_politician_trades
    return await fetch_politician_trades(days_back=days)


@app.get("/api/stocks/squeeze-setups")
async def get_squeeze_setups():
    """Cross-reference watchlist tickers with short interest + politician activity."""
    from .stocks_data import fetch_squeeze_setups
    return await fetch_squeeze_setups()


@app.get("/api/stocks/watchlist")
async def get_stocks_watchlist():
    from .stocks_data import get_watchlist
    return {"tickers": get_watchlist()}


@app.post("/api/stocks/watchlist")
async def add_to_stocks_watchlist(payload: Dict):
    from .stocks_data import get_watchlist, set_watchlist
    ticker = (payload.get("ticker") or "").upper().strip()
    if not ticker:
        return {"ok": False, "error": "ticker required"}
    current = get_watchlist()
    if ticker not in current:
        current.append(ticker)
        set_watchlist(current)
    return {"ok": True, "tickers": current}


@app.delete("/api/stocks/watchlist/{ticker}")
async def remove_from_stocks_watchlist(ticker: str):
    from .stocks_data import get_watchlist, set_watchlist
    current = [t for t in get_watchlist() if t.upper() != ticker.upper()]
    set_watchlist(current)
    return {"ok": True, "tickers": current}


@app.get("/api/stocks/ticker/{ticker}")
async def get_ticker_details(ticker: str):
    """Live stats for a specific ticker."""
    from .stocks_data import fetch_ticker_stats
    stats = await fetch_ticker_stats(ticker)
    if not stats:
        return {"ok": False, "error": "ticker not found"}
    return stats


@app.get("/api/btc/all")
async def get_all_crypto_signals():
    """Aggregated BTC dashboard data — funding, basis, exchange spread."""
    from .crypto_data import fetch_all_crypto_signals
    return await fetch_all_crypto_signals()


@app.get("/api/playbook")
async def get_playbook_content():
    """Serve TRADING_STRATEGIES.md content for the playbook page."""
    md_path = Path(__file__).parent.parent / "TRADING_STRATEGIES.md"
    if not md_path.exists():
        return {"content": "# Playbook not found"}
    return {"content": md_path.read_text()}


@app.get("/animations")
async def serve_animations():
    return FileResponse(
        "animation-showcase.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


# Mount static files
try:
    app.mount("/static", StaticFiles(directory="frontend"), name="static")
except:
    pass  # Frontend not yet created


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
