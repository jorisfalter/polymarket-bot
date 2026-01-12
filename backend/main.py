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
            
            for trade_data in large_trades[:50]:  # Analyze top 50
                try:
                    # Get wallet profile
                    trader_address = trade_data.get("maker")
                    if not trader_address:
                        continue
                        
                    wallet_profile = await client.get_wallet_profile(trader_address)
                    
                    # Get market data
                    market_id = trade_data.get("market")
                    market_data = await client.get_market(market_id) if market_id else {}
                    
                    # Run detection with detailed signals
                    suspicious, signals = detector.analyze_trade_detailed(
                        trade_data=trade_data,
                        wallet_profile=wallet_profile,
                        market_data=market_data or {}
                    )
                    
                    # Log ALL trades to activity log (for debugging/tuning)
                    activity_entry = {
                        "id": str(uuid.uuid4()),
                        "timestamp": datetime.utcnow().isoformat(),
                        "market": market_data.get("question", trade_data.get("market_question", "Unknown"))[:80],
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
                        
                        # Avoid duplicates
                        existing_ids = {a.suspicious_trade.trade.id for a in alerts_store}
                        if suspicious.trade.id not in existing_ids:
                            alerts_store.insert(0, alert)
                            suspicious_trades_store.insert(0, suspicious)
                            logger.info(f"🚨 New alert: {suspicious.severity.value.upper()} - {suspicious.flags[0]}")
                            
                            # Send notification
                            try:
                                notifier = get_notifier()
                                await notifier.notify(suspicious)
                            except Exception as e:
                                logger.error(f"Notification failed: {e}")
                        
                        # Keep only last 500 alerts
                        while len(alerts_store) > 500:
                            alerts_store.pop()
                            
                except Exception as e:
                    logger.error(f"Error analyzing trade: {e}")
                    continue
            
            # Detect wallet clusters (coordinated trading)
            clusters = detector.detect_wallet_clusters(large_trades)
            for cluster in clusters:
                if cluster.cluster_id not in [c.cluster_id for c in wallet_clusters_store]:
                    wallet_clusters_store.insert(0, cluster)
                    logger.info(f"🕸️ Detected wallet cluster: {len(cluster.wallets)} wallets, ${cluster.total_volume:,.0f}")
                    
    except Exception as e:
        logger.error(f"Scan error: {e}")
        
    logger.info(f"✅ Scan complete. Total alerts: {len(alerts_store)}")


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


# Serve frontend
@app.get("/")
async def serve_frontend():
    return FileResponse("frontend/index.html")


# Mount static files
try:
    app.mount("/static", StaticFiles(directory="frontend"), name="static")
except:
    pass  # Frontend not yet created


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)

