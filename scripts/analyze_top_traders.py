#!/usr/bin/env python3
"""
Analyze top Polymarket traders to evaluate copy-trading viability.

Fetches the top performers and analyzes their trade history to determine:
- Win rate consistency
- Trade frequency
- Market concentration
- Recent performance vs historical
"""
import asyncio
import sys
sys.path.insert(0, '.')

from backend.polymarket_client import PolymarketClient
from backend.leaderboard import tracker
from datetime import datetime, timedelta
from collections import defaultdict


async def analyze_top_traders(top_n: int = 10):
    """Analyze the trading patterns of top performers."""

    print("=" * 80)
    print("TOP TRADER ANALYSIS - Copy Trading Viability Assessment")
    print("=" * 80)
    print()

    # Fetch leaderboard
    print("Fetching leaderboard...")
    leaders = await tracker.fetch_leaderboard(limit=top_n)

    if not leaders:
        print("ERROR: Could not fetch leaderboard")
        return

    print(f"Analyzing top {len(leaders)} traders...\n")

    trader_analyses = []

    async with PolymarketClient() as client:
        for i, leader in enumerate(leaders):
            address = leader["address"]
            name = leader["display_name"] or address[:12] + "..."
            pnl = leader["pnl"]

            print(f"\n{'='*60}")
            print(f"#{i+1}: {name}")
            print(f"{'='*60}")
            print(f"Address: {address}")
            print(f"Reported PnL: ${pnl:,.2f}")

            # Fetch their trades
            trades = await client.get_user_trades(address, limit=100)

            if not trades:
                print("  No trades found in API")
                continue

            # Fetch wallet profile
            profile = await client.get_wallet_profile(address)

            print(f"\nWallet Profile:")
            print(f"  Total trades: {profile.get('total_trades', 'N/A')}")
            print(f"  Unique markets: {profile.get('unique_markets', 'N/A')}")
            print(f"  Total volume: ${profile.get('total_volume_usd', 0):,.2f}")
            print(f"  First seen: {profile.get('first_seen', 'N/A')}")

            # Analyze trades
            print(f"\nTrade Analysis (last {len(trades)} trades):")

            # Group by market
            markets = defaultdict(list)
            total_volume = 0
            buy_count = 0
            sell_count = 0

            for t in trades:
                market = t.get("title") or t.get("question") or t.get("conditionId") or "Unknown"
                markets[market[:50]].append(t)

                size = float(t.get("usdcSize") or t.get("size") or 0)
                total_volume += size

                side = (t.get("side") or t.get("type") or "").upper()
                if "BUY" in side:
                    buy_count += 1
                else:
                    sell_count += 1

            print(f"  Trades analyzed: {len(trades)}")
            print(f"  Unique markets: {len(markets)}")
            print(f"  Buy/Sell ratio: {buy_count}/{sell_count}")
            print(f"  Volume in sample: ${total_volume:,.2f}")

            # Market concentration
            print(f"\n  Market Concentration:")
            sorted_markets = sorted(markets.items(), key=lambda x: len(x[1]), reverse=True)
            for market, market_trades in sorted_markets[:5]:
                pct = len(market_trades) / len(trades) * 100
                print(f"    - {market}... ({len(market_trades)} trades, {pct:.0f}%)")

            # Check for signs of insider trading or unusual patterns
            concentration_ratio = len(sorted_markets[0][1]) / len(trades) if sorted_markets else 0

            # Trading frequency
            timestamps = []
            for t in trades:
                ts = t.get("timestamp") or t.get("createdAt")
                if ts:
                    try:
                        if isinstance(ts, str):
                            # Handle ISO format
                            ts = ts.replace("Z", "+00:00")
                            dt = datetime.fromisoformat(ts)
                            timestamps.append(dt)
                    except:
                        pass

            if len(timestamps) >= 2:
                timestamps.sort()
                time_span = (timestamps[-1] - timestamps[0]).days
                trades_per_day = len(trades) / max(time_span, 1)
                print(f"\n  Trading Frequency:")
                print(f"    Time span: {time_span} days")
                print(f"    Avg trades/day: {trades_per_day:.1f}")

            # Risk assessment
            print(f"\n  Copy-Trading Risk Assessment:")

            risks = []
            if concentration_ratio > 0.5:
                risks.append(f"HIGH concentration ({concentration_ratio*100:.0f}% in one market) - possible insider or gambler")
            if profile.get("total_trades", 0) < 20:
                risks.append("LOW trade count - insufficient history to assess skill")
            if len(markets) < 3:
                risks.append("LOW market diversity - may be luck-based")
            if profile.get("unique_markets", 0) < 5:
                risks.append("Narrow focus - edge may not be replicable")

            if not risks:
                risks.append("No major red flags detected")

            for risk in risks:
                print(f"    ⚠️  {risk}")

            # Store for summary
            trader_analyses.append({
                "rank": i + 1,
                "name": name,
                "pnl": pnl,
                "trades": len(trades),
                "markets": len(markets),
                "concentration": concentration_ratio,
                "risks": risks,
            })

    # Summary
    print("\n\n" + "=" * 80)
    print("SUMMARY: COPY-TRADING VIABILITY")
    print("=" * 80)

    viable_count = 0
    for analysis in trader_analyses:
        is_viable = (
            analysis["markets"] >= 5 and
            analysis["concentration"] < 0.4 and
            analysis["trades"] >= 20
        )
        if is_viable:
            viable_count += 1

        status = "✅ VIABLE" if is_viable else "⚠️  RISKY"
        print(f"\n#{analysis['rank']} {analysis['name']}: {status}")
        print(f"   PnL: ${analysis['pnl']:,.0f} | Markets: {analysis['markets']} | Concentration: {analysis['concentration']*100:.0f}%")

    print(f"\n\nConclusion: {viable_count}/{len(trader_analyses)} top traders appear viable for copy-trading")
    print("\nKey Takeaways:")
    print("- High concentration = possible insider or lucky gambler (avoid copying)")
    print("- Low market diversity = edge may not generalize")
    print("- Copy with delay = you'll get worse odds than they did")
    print("- Consider following traders with 10+ markets and <40% concentration")


if __name__ == "__main__":
    asyncio.run(analyze_top_traders(10))
