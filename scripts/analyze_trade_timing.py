#!/usr/bin/env python3
"""
Analyze trade timing for top sports bettors.

Checks if trades are placed:
- Hours before games (pre-game) - copyable
- During games (live) - not copyable
"""
import asyncio
import sys
import re
from datetime import datetime, timedelta
from collections import defaultdict
sys.path.insert(0, '.')

from backend.polymarket_client import PolymarketClient
from backend.leaderboard import tracker


async def analyze_trade_timing():
    """Analyze when top traders place their bets."""

    print("=" * 80)
    print("TRADE TIMING ANALYSIS")
    print("=" * 80)
    print()

    # Fetch top 5 traders
    leaders = await tracker.fetch_leaderboard(limit=5)

    if not leaders:
        print("ERROR: Could not fetch leaderboard")
        return

    async with PolymarketClient() as client:
        for leader in leaders[:3]:  # Top 3
            address = leader["address"]
            name = leader["display_name"] or address[:12] + "..."

            print(f"\n{'='*60}")
            print(f"Trader: {name}")
            print(f"PnL: ${leader['pnl']:,.0f}")
            print(f"{'='*60}")

            # Fetch their recent trades
            trades = await client.get_user_trades(address, limit=50)

            if not trades:
                print("  No trades found")
                continue

            # Group trades by market
            markets = defaultdict(list)
            for trade in trades:
                title = trade.get("title") or trade.get("question") or "Unknown"
                ts = trade.get("timestamp")
                if isinstance(ts, int):
                    trade_time = datetime.fromtimestamp(ts)
                elif isinstance(ts, str):
                    try:
                        trade_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except:
                        trade_time = None
                else:
                    trade_time = None

                markets[title[:60]].append({
                    "time": trade_time,
                    "side": trade.get("side"),
                    "price": float(trade.get("price") or 0),
                    "size": float(trade.get("usdcSize") or trade.get("size") or 0),
                })

            print(f"\nUnique markets traded: {len(markets)}")
            print(f"\nTrade patterns per market:")
            print("-" * 50)

            single_trade_markets = 0
            multi_trade_markets = 0

            for market, market_trades in list(markets.items())[:10]:
                trade_count = len(market_trades)

                if trade_count == 1:
                    single_trade_markets += 1
                    t = market_trades[0]
                    print(f"\n📍 {market}...")
                    print(f"   Single trade: {t['side']} @ {t['price']:.2f}")
                    if t['time']:
                        print(f"   Time: {t['time'].strftime('%Y-%m-%d %H:%M')}")
                else:
                    multi_trade_markets += 1
                    # Analyze timing spread
                    times = [t['time'] for t in market_trades if t['time']]
                    if len(times) >= 2:
                        times.sort()
                        time_span = (times[-1] - times[0]).total_seconds() / 60  # minutes

                        print(f"\n🔄 {market}...")
                        print(f"   {trade_count} trades over {time_span:.0f} minutes")
                        print(f"   First: {times[0].strftime('%H:%M')} -> Last: {times[-1].strftime('%H:%M')}")

                        # If trades span < 3 hours, likely during game
                        if time_span < 180:
                            print(f"   ⚡ LIVE BETTING (trades within {time_span:.0f} min)")
                        else:
                            print(f"   📅 SPREAD BETTING (trades over {time_span/60:.1f} hours)")
                    else:
                        print(f"\n🔄 {market}...")
                        print(f"   {trade_count} trades (timing unclear)")

            print(f"\n\nSummary:")
            print(f"  Single-trade markets: {single_trade_markets}")
            print(f"  Multi-trade markets: {multi_trade_markets}")

            # Calculate average trades per market
            avg_trades = sum(len(t) for t in markets.values()) / len(markets) if markets else 0
            print(f"  Avg trades per market: {avg_trades:.1f}")

            if avg_trades > 3:
                print(f"  ⚡ Pattern: ACTIVE TRADER - adjusts positions during events")
            else:
                print(f"  📍 Pattern: POSITION TAKER - places bets and holds")


if __name__ == "__main__":
    asyncio.run(analyze_trade_timing())
