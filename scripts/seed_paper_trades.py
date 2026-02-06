#!/usr/bin/env python3
"""
Seed paper trading with current positions from watched traders.

This creates a starting portfolio based on their existing positions
so we can track performance going forward.
"""
import asyncio
import sys
sys.path.insert(0, '.')

from backend.polymarket_client import PolymarketClient
from backend.paper_trader import paper_trader
from backend.leaderboard import tracker


async def seed_paper_trades():
    """Seed paper trades from watched wallets."""

    print("=" * 70)
    print("SEEDING PAPER TRADING PORTFOLIO")
    print("=" * 70)
    print(f"Position size per trade: ${paper_trader.position_size}")
    print()

    watched = tracker.get_watching()
    if not watched:
        print("No watched wallets! Add some with:")
        print("  curl -X POST localhost:8000/api/leaderboard/watch/{address}")
        return

    print(f"Watched wallets: {len(watched)}")

    seeded = 0
    skipped_sports = 0
    skipped_duplicate = 0

    # Track what we've already seeded
    existing_keys = {
        f"{t.copied_from}:{t.market_id}:{t.outcome}"
        for t in paper_trader.trades
    }

    async with PolymarketClient() as client:
        for address in watched:
            profile = await client.get_wallet_profile(address)
            trader_name = profile.get("username") or address[:16] + "..."

            print(f"\n--- {trader_name} ---")

            trades = await client.get_user_trades(address, limit=20)

            for trade in trades:
                title = trade.get("title") or ""
                title_lower = title.lower()

                # Skip sports
                is_sports = any(x in title_lower for x in [
                    "vs.", "spread:", "o/u ", "moneyline"
                ])
                if is_sports:
                    skipped_sports += 1
                    continue

                market_id = trade.get("conditionId")
                outcome = trade.get("outcome") or ""
                if not market_id:
                    continue

                # Skip duplicates
                key = f"{address}:{market_id}:{outcome}"
                if key in existing_keys:
                    skipped_duplicate += 1
                    continue

                their_price = float(trade.get("price") or 0)
                if their_price <= 0:
                    continue

                # Get current price
                market = await client.get_market(market_id)
                current_price = their_price

                if market:
                    tokens = market.get("tokens", [])
                    for token in tokens:
                        if token.get("outcome") == outcome:
                            current_price = float(token.get("price") or their_price)
                            break

                # Record paper trade
                paper_trade = await paper_trader.record_copy_trade(
                    copied_from=address,
                    copied_from_name=trader_name,
                    market_id=market_id,
                    market_title=title,
                    market_slug=trade.get("slug") or "",
                    outcome=outcome,
                    side=trade.get("side") or "BUY",
                    their_entry_price=their_price,
                    our_entry_price=current_price,
                )

                existing_keys.add(key)
                seeded += 1

                slippage = abs(current_price - their_price) / their_price * 100 if their_price else 0
                print(f"  ✅ {title[:45]}...")
                print(f"     {paper_trade.side} {outcome} @ {current_price:.4f} (they: {their_price:.4f}, slip: {slippage:.1f}%)")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Paper trades seeded: {seeded}")
    print(f"Skipped (sports): {skipped_sports}")
    print(f"Skipped (duplicate): {skipped_duplicate}")
    print(f"\nTotal portfolio positions: {len(paper_trader.trades)}")
    print(f"Total invested (paper): ${paper_trader.position_size * len(paper_trader.trades):,.0f}")

    # Show stats
    print("\n" + "-" * 40)
    stats = paper_trader.get_stats()
    print(f"Open positions: {stats['open_trades']}")
    print(f"Won: {stats['won_trades']}")
    print(f"Lost: {stats['lost_trades']}")
    print(f"Unrealized P&L: ${stats['unrealized_pnl']:+,.2f}")


if __name__ == "__main__":
    asyncio.run(seed_paper_trades())
