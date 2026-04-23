# Car on X — Infinite Money Glitch (Trump Insult Market)

**Source:** https://x.com/CarOnPolymarket (April 2026)

## Core Claim
Polymarket runs a **daily-resolving market on whether Trump will insult someone that day**. Every single day for 30+ consecutive days has resolved **Yes**. Prices sit at 92–95¢ even though the base rate is effectively 100%.

> "I bought $100 on each day for the rest of the month."

## Why It's a Strategy, Not a Meme
Same mispricing as Movez's 80–99¢ edge (see [movez-copy-trading-algo.md](movez-copy-trading-algo.md)):
- Traders anchor on "above 90¢ feels expensive"
- Base rate is derivable from the market's OWN HISTORY, not speculation
- 5–8% daily return compounded = ~4.3x capital in 30 days (if fills weren't a constraint)

## The Pattern
Applies to any daily-resolving market where:
1. The same outcome has hit Yes ≥10 days in a row
2. Current price ≤ 95¢
3. There is no fundamental reason the streak will break tomorrow

## Examples Beyond Trump-Insult
- "Will Bitcoin finish up today?" (historically ~55% — not a glitch, skip)
- "Will the ECB announce a policy change today?" (rare event — skip)
- **Qualifying pattern:** specific events where the underlying behavior is predictable and priced uncertainly.

## Risks
- **The day it breaks, you lose 90¢.** Size so a single loss ≤ 2–3 winning days.
- **Pattern expiration.** "Trump insults daily" doesn't survive Trump leaving office. Always check the underlying driver.
- **Liquidity.** Daily markets have thin books — filling $100 at 92¢ might move the price against you.

## Applicable to Our Bot
- Already shipped: **Strategy 3b (Daily Repeating Base-Rate Plays)** in the AI prompt. Agent scans for qualifying markets each cycle.
- Not shipped: an explicit feed that surfaces daily-resolving markets (currently the agent only sees top-20 by volume). Would need a separate scan that pulls `/events?tag_slug=daily` or similar and filters on resolution history.

## Key Number
A 95¢ buy that resolves Yes = **5.3% return in 24h**. Compounded over a month: 4.3× capital. The constraint is liquidity, not edge.
