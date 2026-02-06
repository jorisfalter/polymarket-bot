#!/usr/bin/env python3
"""
Simulate copy-trading the top 5 leaderboard traders.

This script:
1. Fetches the top 5 traders
2. Gets their recent trades
3. Simulates what would happen if we copied each trade with a delay
4. Calculates slippage and potential P&L impact
"""
import asyncio
import sys
sys.path.insert(0, '.')

from backend.polymarket_client import PolymarketClient
from backend.leaderboard import tracker


async def simulate_copy_trading():
    """Simulate copy-trading the top performers."""

    print("=" * 80)
    print("COPY-TRADING SIMULATION")
    print("=" * 80)
    print()
    print("Settings:")
    print("  - Fixed position size: $100 per trade")
    print("  - Max slippage tolerance: 5%")
    print("  - Excluded: Sports betting markets")
    print()

    # Fetch top 5 traders
    print("Fetching top 5 traders...")
    leaders = await tracker.fetch_leaderboard(limit=5)

    if not leaders:
        print("ERROR: Could not fetch leaderboard")
        return

    total_trades_analyzed = 0
    copyable_trades = []
    skipped_sports = 0
    skipped_slippage = 0
    skipped_small = 0

    async with PolymarketClient() as client:
        for leader in leaders:
            address = leader["address"]
            name = leader["display_name"] or address[:12] + "..."

            print(f"\n{'='*60}")
            print(f"Analyzing: {name} (PnL: ${leader['pnl']:,.0f})")
            print(f"{'='*60}")

            # Fetch their recent trades
            trades = await client.get_user_trades(address, limit=30)

            if not trades:
                print("  No trades found")
                continue

            for trade in trades[:20]:  # Analyze last 20 trades
                total_trades_analyzed += 1

                title = trade.get("title") or trade.get("question") or "Unknown"
                side = trade.get("side") or "BUY"
                price = float(trade.get("price") or 0)
                size = float(trade.get("size") or 0)
                usdc_size = float(trade.get("usdcSize") or 0)
                if not usdc_size and price:
                    usdc_size = size * price
                condition_id = trade.get("conditionId")

                # Skip small trades
                if usdc_size < 10:
                    skipped_small += 1
                    continue

                # Check if sports
                title_lower = title.lower()
                is_sports = any(x in title_lower for x in [
                    "vs.", "spread:", "o/u ", "moneyline",
                    "lakers", "celtics", "warriors", "bulls",
                    "rangers", "flames", "oilers", "penguins"
                ])

                if is_sports:
                    skipped_sports += 1
                    continue

                # Get current market price to calculate slippage
                if condition_id:
                    market_info = await client.get_market(condition_id)
                    current_price = None

                    if market_info:
                        tokens = market_info.get("tokens", [])
                        outcome = trade.get("outcome")
                        for token in tokens:
                            if token.get("outcome") == outcome:
                                current_price = float(token.get("price") or 0)
                                break

                    if not current_price:
                        current_price = price  # Fallback

                    # Calculate slippage
                    if price > 0:
                        slippage_pct = abs(current_price - price) / price * 100
                    else:
                        slippage_pct = 0

                    # Check slippage threshold
                    if slippage_pct > 5:
                        skipped_slippage += 1
                        print(f"  ⏭️  SKIP (slippage {slippage_pct:.1f}%): {title[:50]}...")
                        continue

                    # This trade is copyable!
                    copy_size = 100  # Fixed $100
                    shares_to_buy = copy_size / current_price if current_price > 0 else 0

                    copyable_trades.append({
                        "trader": name,
                        "market": title,
                        "side": side,
                        "their_price": price,
                        "current_price": current_price,
                        "their_size": usdc_size,
                        "our_size": copy_size,
                        "slippage_pct": slippage_pct,
                        "shares": shares_to_buy,
                    })

                    print(f"  ✅ COPY: {title[:50]}...")
                    print(f"     Side: {side} | Their entry: {price:.4f} | Current: {current_price:.4f} | Slip: {slippage_pct:.1f}%")

    # Summary
    print("\n\n" + "=" * 80)
    print("SIMULATION RESULTS")
    print("=" * 80)

    print(f"\nTrades analyzed: {total_trades_analyzed}")
    print(f"Skipped (sports): {skipped_sports}")
    print(f"Skipped (small <$10): {skipped_small}")
    print(f"Skipped (slippage >5%): {skipped_slippage}")
    print(f"Copyable trades: {len(copyable_trades)}")

    if copyable_trades:
        print("\n" + "-" * 60)
        print("COPYABLE TRADES DETAIL")
        print("-" * 60)

        total_investment = 0
        avg_slippage = 0

        for i, trade in enumerate(copyable_trades[:15]):  # Show top 15
            print(f"\n{i+1}. {trade['market'][:55]}...")
            print(f"   Trader: {trade['trader']}")
            print(f"   Side: {trade['side']}")
            print(f"   Their entry: ${trade['their_price']:.4f} ({trade['their_size']:.0f} USDC)")
            print(f"   Current price: ${trade['current_price']:.4f}")
            print(f"   Slippage: {trade['slippage_pct']:.2f}%")
            print(f"   Our position: $100 = {trade['shares']:.1f} shares")

            total_investment += trade['our_size']
            avg_slippage += trade['slippage_pct']

        avg_slippage = avg_slippage / len(copyable_trades) if copyable_trades else 0

        print("\n" + "-" * 60)
        print("SUMMARY")
        print("-" * 60)
        print(f"Total investment needed: ${total_investment:,.0f}")
        print(f"Average slippage: {avg_slippage:.2f}%")
        print(f"Markets: {len(set(t['market'] for t in copyable_trades))}")
        print(f"Traders copied: {len(set(t['trader'] for t in copyable_trades))}")

        print("\n⚠️  IMPORTANT CAVEATS:")
        print("   - This is a simulation with CURRENT prices")
        print("   - Real copy-trading would have ~1-2 min delay")
        print("   - Slippage could be higher during volatile periods")
        print("   - Past performance doesn't guarantee future results")
        print("   - Most profitable traders are sports bettors (excluded here)")


if __name__ == "__main__":
    asyncio.run(simulate_copy_trading())
