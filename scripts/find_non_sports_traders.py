#!/usr/bin/env python3
"""
Find traders who trade non-sports markets (crypto, politics, etc.)
"""
import asyncio
import sys
sys.path.insert(0, '.')

from backend.polymarket_client import PolymarketClient
from backend.leaderboard import tracker


async def find_non_sports_traders():
    """Find traders with non-sports trades."""

    print("=" * 70)
    print("SEARCHING FOR NON-SPORTS TRADERS")
    print("=" * 70)
    print()

    leaders = await tracker.fetch_leaderboard(limit=50)

    candidates = []

    async with PolymarketClient() as client:
        for i, leader in enumerate(leaders):
            address = leader["address"]
            name = leader["display_name"] or address[:12] + "..."

            trades = await client.get_user_trades(address, limit=30)

            sports_count = 0
            non_sports_count = 0
            non_sports_examples = []

            for trade in trades:
                title = trade.get("title") or ""
                title_lower = title.lower()

                is_sports = any(x in title_lower for x in [
                    "vs.", "spread:", "o/u ", "moneyline",
                    "lakers", "celtics", "warriors", "bulls", "heat", "nets",
                    "rangers", "flames", "oilers", "penguins", "bruins",
                    "nba", "nhl", "nfl", "mlb", "ncaa",
                    "patriots", "chiefs", "eagles", "cowboys",
                ])

                if is_sports:
                    sports_count += 1
                else:
                    non_sports_count += 1
                    if len(non_sports_examples) < 3:
                        non_sports_examples.append(title[:60])

            if non_sports_count > 0:
                pct_non_sports = non_sports_count / len(trades) * 100 if trades else 0
                candidates.append({
                    "rank": i + 1,
                    "name": name,
                    "address": address,
                    "pnl": leader["pnl"],
                    "non_sports_pct": pct_non_sports,
                    "non_sports_count": non_sports_count,
                    "examples": non_sports_examples,
                })

                if pct_non_sports > 20:  # Show traders with >20% non-sports
                    print(f"\n#{i+1} {name} - ${leader['pnl']:,.0f} PnL")
                    print(f"    Non-sports: {non_sports_count}/{len(trades)} trades ({pct_non_sports:.0f}%)")
                    for ex in non_sports_examples[:2]:
                        print(f"    📌 {ex}...")

    print("\n\n" + "=" * 70)
    print("BEST CANDIDATES FOR COPY-TRADING")
    print("=" * 70)

    # Sort by non-sports percentage
    candidates.sort(key=lambda x: x["non_sports_pct"], reverse=True)

    for c in candidates[:10]:
        print(f"\n{c['name']} (#{c['rank']})")
        print(f"   Address: {c['address']}")
        print(f"   PnL: ${c['pnl']:,.0f}")
        print(f"   Non-sports: {c['non_sports_pct']:.0f}%")
        print(f"   Examples: {c['examples'][:2]}")


if __name__ == "__main__":
    asyncio.run(find_non_sports_traders())
