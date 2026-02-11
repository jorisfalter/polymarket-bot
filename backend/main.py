"""
Polymarket Insider Detector - API Server

A FastAPI application that monitors Polymarket for suspicious trading patterns
that may indicate insider information.

Run with: uvicorn backend.main:app --reload
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
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


async def scan_for_suspicious_activity():
    """
    Background task that periodically scans for suspicious trades
    """
    logger.info("🔍 Scanning for suspicious activity...")

    try:
        async with PolymarketClient() as client:
            # Get recent large trades
            large_trades = await client.get_recent_large_trades(
                min_notional=settings.min_notional_alert,
                hours=settings.alert_window_hours
            )

            logger.info(f"Found {len(large_trades)} large trades to analyze")

            new_alerts_count = 0
            duplicate_count = 0

            for trade_data in large_trades[:50]:  # Analyze top 50
                try:
                    # Get wallet profile
                    trader_address = trade_data.get("maker")
                    if not trader_address or trader_address == "unknown":
                        continue  # Skip synthetic market entries without real wallets

                    wallet_profile = await client.get_wallet_profile(trader_address)

                    # Get market data - try multiple sources
                    market_id = trade_data.get("market") or trade_data.get("conditionId") or trade_data.get("marketId")
                    market_data = {}

                    # First check if trade already has market info embedded
                    if trade_data.get("market_question"):
                        market_data = {
                            "id": market_id or "unknown",
                            "slug": trade_data.get("market_slug", ""),
                            "question": trade_data.get("market_question", "Unknown"),
                            "yes_price": float(trade_data.get("price", 50)),
                            "no_price": 100 - float(trade_data.get("price", 50)),
                            "volume_24h": 0,
                            "volume_total": 0,
                            "liquidity": 0,
                            "is_active": True
                        }
                    # Otherwise try to fetch from API
                    elif market_id:
                        fetched_market = await client.get_market(market_id)
                        if fetched_market:
                            market_data = {
                                "id": fetched_market.get("id", market_id),
                                "slug": fetched_market.get("slug", ""),
                                "question": fetched_market.get("question", "Unknown"),
                                "yes_price": float(fetched_market.get("outcomePrices", [50, 50])[0] if fetched_market.get("outcomePrices") else 50),
                                "no_price": float(fetched_market.get("outcomePrices", [50, 50])[1] if fetched_market.get("outcomePrices") else 50),
                                "volume_24h": float(fetched_market.get("volume24hr", 0) or 0),
                                "volume_total": float(fetched_market.get("volume", 0) or 0),
                                "liquidity": float(fetched_market.get("liquidity", 0) or 0),
                                "is_active": fetched_market.get("active", True)
                            }

                    # If still no market data, create minimal placeholder
                    if not market_data:
                        market_data = {
                            "id": market_id or "unknown",
                            "slug": "",
                            "question": trade_data.get("title", trade_data.get("description", "Unknown Market")),
                            "yes_price": float(trade_data.get("price", 50)),
                            "no_price": 100 - float(trade_data.get("price", 50)),
                            "volume_24h": 0,
                            "volume_total": 0,
                            "liquidity": 0,
                            "is_active": True
                        }

                    # Run detection with detailed signals
                    suspicious, signals = detector.analyze_trade_detailed(
                        trade_data=trade_data,
                        wallet_profile=wallet_profile,
                        market_data=market_data
                    )

                    # Log ALL trades to activity log (for debugging/tuning)
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

                    # Avoid duplicate entries
                    existing_traders = [(a["trader_full"], a["market"]) for a in activity_log[-100:]]
                    if (trader_address, activity_entry["market"]) not in existing_traders:
                        activity_log.insert(0, activity_entry)
                        # Keep last 500 entries
                        while len(activity_log) > 500:
                            activity_log.pop()

                    if suspicious:
                        # Create alert
                        alert = InsiderAlert(
                            id=str(uuid.uuid4()),
                            created_at=datetime.utcnow(),
                            suspicious_trade=suspicious,
                            market=market_data,
                            insider_probability=suspicious.suspicion_score / 100,
                            narrative=_generate_narrative(suspicious)
                        )

                        # Use composite key for deduplication (fixes None trade ID bug)
                        trade_key = _get_trade_key(suspicious.trade)

                        if trade_key not in seen_trade_keys:
                            seen_trade_keys.add(trade_key)
                            alerts_store.insert(0, alert)
                            suspicious_trades_store.insert(0, suspicious)
                            new_alerts_count += 1
                            logger.info(f"🚨 New alert: {suspicious.severity.value.upper()} - {suspicious.flags[0] if suspicious.flags else 'Suspicious'}")

                            # Send notification
                            try:
                                notifier = get_notifier()
                                await notifier.notify(suspicious)
                            except Exception as e:
                                logger.error(f"Notification failed: {e}")
                        else:
                            duplicate_count += 1
                            logger.debug(f"Skipping duplicate trade: {trade_key[:50]}...")

                        # Keep only last 500 alerts
                        while len(alerts_store) > 500:
                            alerts_store.pop()

                        # Limit seen_trade_keys to prevent memory growth
                        if len(seen_trade_keys) > 10000:
                            # Keep most recent by clearing old ones
                            seen_trade_keys.clear()
                            # Repopulate from current alerts
                            for a in alerts_store:
                                seen_trade_keys.add(_get_trade_key(a.suspicious_trade.trade))

                except Exception as e:
                    logger.error(f"Error analyzing trade: {e}")
                    continue

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
        seconds=30,  # Check trade targets every 30 seconds
        id='trade_monitor_job'
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


# Mount static files
try:
    app.mount("/static", StaticFiles(directory="frontend"), name="static")
except:
    pass  # Frontend not yet created


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
