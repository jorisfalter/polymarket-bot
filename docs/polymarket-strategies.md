# AI Trading Agent — Strategy Playbook

## Overview
The AI agent runs every 15 minutes and systematically checks all 7 strategies. It receives 9 data sources per cycle and decides whether to trade based on genuine edge.

**Limits**: $10 max per trade, $100 max total exposure, 10 max positions.

---

## Strategy 1: Insider Signal Following
**Data source**: Insider detection alerts (HIGH/CRITICAL severity)

**Logic**: When the detection system flags a suspicious trade — fresh wallet, big position on unlikely outcome, low market diversity — the agent evaluates whether to follow.

**Trigger**: Fresh wallet dumps $5k+ on a <30c outcome in a non-sports market.

**Edge**: Insider traders have information the market hasn't priced in yet. Following their bet before the market moves captures the same edge.

---

## Strategy 2: Smart Money Copy Trading
**Data source**: Leaderboard top traders + watched wallets

**Logic**: Top-performing traders (60%+ win rate, 20+ markets) have demonstrated skill. Three known quant wallets made $1.3M in 30 days using Markov chain arbitrage on Polymarket crypto windows. When they take new positions, consider copying.

**Known quant wallets (added April 2026):**
- `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` — High-Confidence Spread Capture (BTC/ETH hourly)
- `0xe1d6b51521bd4365769199f392f9818661bd907c` — Dual-Mode EV (directional + price locks)
- `0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82` — Multi-Asset Variance Reduction (5-min windows)

**Trigger**: Top trader or quant wallet places a new significant bet.

**Edge**: Skilled traders identify mispriced markets before the crowd.

---

## Strategy 3: Near-Resolution Mispricing (updated)
**Data source**: Near-resolution markets (ending within 48h)

**Logic**: Research on 72M Polymarket trades (Movez, April 2026) shows traders *underprice* high-probability outcomes. The real edge is in the **80¢–99¢ range**, not in cheap contracts. Markets priced 80-95c with near-certain outcomes are systematically mispriced.

**Trigger**: Market ends within 48h, dominant outcome priced 80–99c, outcome appears near-certain from fundamentals.

**Edge**: Guaranteed return if outcome resolves as expected. Compounding many of these creates consistent returns. Buying at 92c that resolves at 100c = 8.7% return in hours.

**Previous approach was wrong**: We were only looking at 95%+ markets. The real edge starts at 80c.

---

## Strategy 3b: Daily Repeating Base-Rate Plays ("Infinite Money Glitch")
**Data source**: Polymarket daily-resolving markets with strong historical base rate

**Logic**: Some markets resolve the same way every single day (e.g., "Will Trump insult someone today?", "Will Bitcoin finish up today?"). Traders systematically underprice these — a 99%+ event is priced 90-95c because traders anchor on "prices above 90c feel expensive". Classic example: @CarOnPolymarket's Trump-insult market priced 92-95c daily, resolving Yes 30+ days in a row ($100/day ≈ 5-8% daily compounded).

**Trigger**: Daily-resolving market where the Yes side has resolved Yes 10+ times in a row AND current price ≤ 95c. The base rate must be derivable from the market's own history, not speculation.

**Edge**: Same mispricing as Strategy 3 (traders underprice near-certain outcomes) but applied to a repeating market, so you can compound the edge every 24 hours. 5% daily for 30 days = ~4.3x capital if fills weren't a constraint.

**Risk**: The one day it breaks, you lose 90c+. Size so a single loss ≤ 2-3 winning days. Skip if the underlying pattern has a known expiration (e.g., "Trump tweets daily" doesn't survive Trump leaving office).

---

## Strategy 4: Stock Market Arbitrage
**Data source**: Polymarket finance markets + real-time SPY, QQQ, Gold, Oil prices

**Logic**: If real market data diverges from what Polymarket is pricing, that's an arbitrage opportunity.

**Trigger**: e.g., "S&P above 5500 by March 31" priced at 40c but SPY is already at 5490.

**Edge**: Real-time stock data gives us information Polymarket hasn't fully priced in yet.

---

## Strategy 5: Auditor Insider Pattern (KPMG Pattern)
**Data source**: Earnings market alerts + auditor mapping (80+ companies mapped to Big 4 auditors)

**Logic**: Based on EventWaves research — wallets that bet big exclusively on earnings markets for companies with the same auditor are likely insiders at the audit firm.

**Trigger**: Wallet bets $5k+ on KPMG-audited company earnings but only $50 on non-KPMG companies.

**Edge**: Audit firm insiders have the most reliable pre-earnings information.

---

## Strategy 6: Market Inconsistencies (Temporal + Hierarchy Arb)
**Data source**: Cross-market inconsistency detector

**Logic**: Related markets sometimes price contradictory outcomes. P(X by April) > P(X by December) is mathematically impossible. P(BTC > $80k) > P(BTC > $70k) is impossible. Bet the cheaper side.

**Trigger**: Two logically related markets with >10% pricing gap in the wrong direction.

**Edge**: Near risk-free — one of the two prices MUST be wrong by definition.

---

## Strategy 8: Asymmetric Bet (Paris-Weather Pattern)
**Data source**: Detector's new `♻️ Asymmetric Bet` signal (fires in the detector pipeline, not a separate feed)

**Logic**: The Paris Météo-France tampering case (FT, April 2026) exposed a blind spot: insiders routinely bet *small dollar amounts* on *extreme longshots* (<3c) and pocket 50-100x returns. Our $1000 notional floor was hiding this pattern entirely. An insider betting $50 at 0.5c to win $10,000 is exactly as suspicious as one betting $5000 at 50c — just the blast radius differs.

**Trigger**: Detector raises a HIGH-severity alert with `♻️ Asymmetric Bet` flag. That means: BUY side, price ≤3c, stake ≥$5, payoff ratio ≥30x, ideally fresh wallet and low market diversity.

**Edge**: Piggyback the insider's asymmetric bet with our own moonshot-sized stake ($1–3). If they're right, we 30-100x our stake. If they're wrong or it's a false positive, we lose $1–3. The math strongly favors us even at a 10% hit rate.

**Budget**: lives in the Moonshot book (see `docs/trading-philosophy.md`). Max $20 aggregate exposure across all active moonshots.

**Known cases**: `paris_temperature_apr6_2026`, `paris_temperature_apr15_2026` — both backtestable via `backtester.run_known_case()`.

---

## Strategy 9: Own Conviction
**Data source**: All available data + thesis board

**Logic**: Sometimes the data tells a clear story that doesn't fit neatly into the other strategies. The agent trades on its own analysis when conviction is high.

**Trigger**: Strong evidence from multiple sources pointing to a mispriced market.

**Edge**: AI reasoning applied to full context of market data, signals, and theses.

---

## Quant Math (from 0xRicker research, April 2026)

The three quant wallets above used:
- **Markov Chain transition matrices** — measure which price state the market is in NOW and probability of next state
- **Entry rule**: Arbitrage gap ≥ 5% AND state persistence ≥ 0.87
- **Kelly Criterion**: f* ≈ 0.71 for optimal bet sizing
- **Off-hours edge**: Human traders are offline at 3AM → crypto windows become "stale and exploitable"

Applicable to our bot: focus on Kelly-sized positions and exploit off-hours mispricing in resolution arb.

---

## Data Sources (12 total)
1. Insider alerts — suspicious trades flagged by detection system
2. Auditor pattern watch — earnings alerts tagged with auditor
3. Smart money — recent trades from watched wallets (incl. 3 quant wallets: 0xeebde7a0, 0xe1d6b515, 0xb27bc932)
4. Leaderboard — top traders by PnL with win rates + specialization tags
5. Top 20 markets — volume, prices, end dates (from a 300-market fetch)
6. Near-resolution markets — ending within 48h with 80%+ dominant outcome
7. Long-tail mispricing — 80-99¢ near-resolution markets *outside* volume top-50 (whales-don't-bother edge)
8. Daily-repeating candidates — Trump-insult and similar (Strategy 3b)
9. Stock market data — live SPY/QQQ/Gold/Oil
10. Market inconsistencies — cross-market contradictions (temporal + hierarchy arb)
11. Newsletter intel — Matt Levine, Doomberg, EventWaves (via Gmail IMAP, 8000 chars per email)
12. WSB ticker buzz — top 10 r/wallstreetbets tickers via Fly.io proxy (cross-board signal)
13. Thesis board — running hypotheses from previous cycles

---

## Thesis Board
The agent maintains persistent investment theses across cycles:
- **CREATE**: new pattern spotted
- **UPDATE**: new evidence (confirm or weaken)
- **CLOSE**: resolved or invalidated

Stored in `data/agent_theses.json`.

## Audit Trail
- **Thinking journal**: `data/agent_thinking.jsonl`
- **Trade journal**: `data/trade_journal.jsonl`
- **Airtable**: live trade log
