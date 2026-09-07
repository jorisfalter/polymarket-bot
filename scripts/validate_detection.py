#!/usr/bin/env python3
"""
Offline validation of insider detection parameters.

Fetches the actual known insider trades and checks if our detection
engine would have flagged them.
"""
import asyncio
import sys
sys.path.insert(0, '.')

from backend.polymarket_client import PolymarketClient
from backend.detectors import detector

# Known insider cases with their wallet addresses and the specific trades
INSIDER_CASES = [
    {
        "name": "Burdensome-Mix (Maduro Capture)",
        "wallet": "0x31a56e9E690c621eD21De08Cb559e9524Cdb8eD9",
        "market_filter": "maduro",
        "expected_signals": ["Fresh Wallet", "Extreme Odds", "Position Size"],
        "description": "Wagered ~$32k at ~7% odds on Maduro capture, netted $436k profit",
    },
    {
        "name": "dirtycup (Nobel Peace Prize)",
        "wallet": "0x234cc49e43dff8b3207bbd3a8a2579f339cb9867",
        "market_filter": "machado",
        "expected_signals": ["Extreme Odds", "Position Size"],
        "description": "Placed ~$70k on Machado at ~3.6% odds before announcement",
    },
    {
        "name": "romanticpaul (Taylor Swift)",
        "wallet": "0xf5cfe6f998d597085e366f915b140e82e0869fc6",
        "market_filter": "swift",
        "expected_signals": ["Fresh Wallet", "Timing"],
        "description": "Bought shares ~15 hours before engagement announcement",
    },
    {
        "name": "AlphaRaccoon (Google Year in Search)",
        "wallet": "0xee50a31c3f5a7c77824b12a941a54388a2827ed6",
        "market_filter": "google",
        "expected_signals": ["Position Size", "Extreme Odds"],
        "description": "Went 22-for-23 on Google search markets, netted ~$1M",
    },
]


async def analyze_insider_trades():
    """Fetch and analyze each insider's trades."""

    print("=" * 80)
    print("INSIDER DETECTION VALIDATION REPORT")
    print("=" * 80)
    print()

    async with PolymarketClient() as client:
        for case in INSIDER_CASES:
            print(f"\n{'='*80}")
            print(f"CASE: {case['name']}")
            print(f"{'='*80}")
            print(f"Wallet: {case['wallet']}")
            print(f"Description: {case['description']}")
            print(f"Expected signals: {', '.join(case['expected_signals'])}")
            print()

            # Fetch wallet profile
            wallet_profile = await client.get_wallet_profile(case['wallet'])
            print(f"Wallet Profile:")
            print(f"  Total trades: {wallet_profile.get('total_trades', 0)}")
            print(f"  Unique markets: {wallet_profile.get('unique_markets', 0)}")
            print(f"  Total volume: ${wallet_profile.get('total_volume_usd', 0):,.2f}")
            print(f"  Win rate: {wallet_profile.get('win_rate', 'N/A')}")
            print(f"  First seen: {wallet_profile.get('first_seen', 'N/A')}")
            print()

            # Fetch trades for this wallet
            trades = await client.get_user_trades(case['wallet'], limit=100)
            print(f"Found {len(trades)} trades for this wallet")

            # Filter to relevant market trades
            market_filter = case['market_filter'].lower()
            relevant_trades = []
            for t in trades:
                title = (t.get('title') or t.get('question') or '').lower()
                if market_filter in title:
                    relevant_trades.append(t)

            print(f"Relevant trades (containing '{market_filter}'): {len(relevant_trades)}")
            print()

            if not relevant_trades:
                print("  [!] No relevant trades found - checking all trades instead")
                relevant_trades = trades[:10]  # Just check first 10

            # Analyze each relevant trade
            print("TRADE ANALYSIS:")
            print("-" * 60)

            for i, trade in enumerate(relevant_trades[:5]):  # Analyze up to 5
                title = trade.get('title') or trade.get('question') or 'Unknown'
                size = float(trade.get('size') or trade.get('amount') or 0)
                price = float(trade.get('price') or 0)
                if price <= 1:
                    price = price * 100  # Convert to cents
                side = trade.get('side') or trade.get('type') or 'BUY'
                usdc = float(trade.get('usdcSize') or 0) or (size * price / 100)

                print(f"\nTrade {i+1}: {title[:60]}...")
                print(f"  Side: {side}, Size: {size:,.0f} shares, Price: {price:.1f}¢, Value: ${usdc:,.2f}")

                # Prepare trade data for detector
                trade_data = {
                    "maker": case['wallet'],
                    "market": trade.get('conditionId', ''),
                    "side": side,
                    "size": size,
                    "price": price,
                    "notional_usd": usdc,
                    "timestamp": trade.get('timestamp'),
                }

                market_data = {
                    "id": trade.get('conditionId', ''),
                    "slug": trade.get('slug', ''),
                    "question": title,
                    "yes_price": price if side == 'BUY' else 100 - price,
                    "no_price": 100 - price if side == 'BUY' else price,
                    "volume_24h": 0,
                    "volume_total": 0,
                    "liquidity": 0,
                    "is_active": False,
                }

                # Run through detector
                suspicious, signals = detector.analyze_trade_detailed(
                    trade_data=trade_data,
                    wallet_profile=wallet_profile,
                    market_data=market_data,
                )

                total_score = sum(s['score'] for s in signals)
                active_signals = [s for s in signals if s['score'] > 0]

                print(f"  Detection Score: {total_score}")
                print(f"  Would Alert: {'YES' if suspicious else 'NO'}")
                if suspicious:
                    print(f"  Severity: {suspicious.severity.value.upper()}")

                print(f"  Active Signals:")
                for s in active_signals:
                    print(f"    - {s['signal']}: +{s['score']} ({s['details']})")

                if not active_signals:
                    print(f"    (none)")

                # Check expected signals
                expected = case['expected_signals']
                found_expected = []
                missing_expected = []
                for exp in expected:
                    if any(exp.lower() in s['signal'].lower() for s in active_signals):
                        found_expected.append(exp)
                    else:
                        missing_expected.append(exp)

                if found_expected:
                    print(f"  Expected signals FOUND: {', '.join(found_expected)}")
                if missing_expected:
                    print(f"  Expected signals MISSING: {', '.join(missing_expected)}")

            print()

    print("\n" + "=" * 80)
    print("VALIDATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(analyze_insider_trades())
