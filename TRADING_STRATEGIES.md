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

## Strategy 7: Own Conviction
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

## Data Sources (9 total)
1. Insider alerts — suspicious trades flagged by detection system
2. Auditor pattern watch — earnings alerts tagged with auditor
3. Smart money — recent trades from watched wallets (incl. 3 quant wallets)
4. Leaderboard — top traders by PnL with win rates
5. Top 20 markets — volume, prices, end dates
6. Near-resolution markets — ending within 48h with 80%+ dominant outcome
7. Stock market data — live SPY/QQQ/Gold/Oil
8. Thesis board — running hypotheses from previous cycles
9. Market inconsistencies — cross-market contradictions

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
