# AI Trading Agent — Strategy Playbook

## Overview
The AI agent (Claude Haiku) runs every 5 minutes and systematically checks all 6 strategies. It receives 9 data sources per cycle and decides whether to trade based on genuine edge, not arbitrary minimums.

**Limits**: $1 max per trade, $5 max total exposure, 5 max positions.

---

## Strategy 1: Insider Signal Following
**Data source**: Insider detection alerts (HIGH/CRITICAL severity)

**Logic**: When the detection system flags a suspicious trade — fresh wallet, big position on unlikely outcome, low market diversity — the agent evaluates whether to follow with a penny trade.

**Trigger**: Fresh wallet dumps $5k+ on a <30c outcome in a non-sports market.

**Edge**: Insider traders have information the market hasn't priced in yet. Following their bet before the market moves captures the same edge.

---

## Strategy 2: Smart Money Copy Trading
**Data source**: Leaderboard top 10 traders + watched wallet trades

**Logic**: Top-performing traders (60%+ win rate, 20+ markets) have demonstrated skill. When they take new positions, the agent considers copying.

**Trigger**: Top trader places a significant new bet on a market the agent finds interesting.

**Edge**: Skilled traders identify mispriced markets. Copying their best ideas at similar prices captures their alpha.

---

## Strategy 3: Resolution Arbitrage
**Data source**: Near-resolution markets (ending within 48h, one outcome 90%+)

**Logic**: Markets about to resolve with a near-certain outcome still trade at 95-99c. Buying the dominant outcome yields 1-5% return in hours.

**Trigger**: Market ends within 48h, dominant outcome is 95-99c, sufficient liquidity.

**Edge**: Guaranteed return if the outcome resolves as expected. Low risk, low reward, but consistent.

---

## Strategy 4: Stock Market Arbitrage
**Data source**: Polymarket finance/stock markets + real-time SPY, QQQ, Gold, Oil prices

**Logic**: Polymarket has markets on stock prices, earnings, economic indicators. If real market data diverges from what Polymarket is pricing, that's an arbitrage opportunity.

**Trigger**: e.g., "S&P above 5500 by March 31" priced at 40c but SPY is already at 5490.

**Edge**: Real-time stock data gives us information that Polymarket's prediction market hasn't fully priced in yet.

---

## Strategy 5: Auditor Insider Pattern (KPMG Pattern)
**Data source**: Earnings market alerts + auditor mapping (80+ companies mapped to Big 4 auditors)

**Logic**: Based on EventWaves research — wallets that bet big exclusively on earnings markets for companies with the same auditor (e.g., all KPMG clients) are likely insiders at the audit firm with access to pre-release earnings data.

**Trigger**: Wallet bets $5k+ on KPMG-audited company earnings but only $50 on non-KPMG companies. Multiple bets on same-auditor clients.

**Edge**: Audit firm insiders have the most reliable pre-earnings information. Their bets have historically been highly profitable.

---

## Strategy 6: Own Conviction
**Data source**: All available data + thesis board

**Logic**: Sometimes the data tells a clear story that doesn't fit neatly into the other 5 strategies. The agent can trade on its own analysis when conviction is high.

**Trigger**: Strong evidence from multiple sources pointing to a mispriced market.

**Edge**: Claude's reasoning ability applied to the full context of market data, signals, and theses.

---

## Data Sources (9 total)
1. Insider alerts — suspicious trades flagged by detection system
2. Auditor pattern watch — earnings alerts tagged with auditor (KPMG/Deloitte/EY/PwC)
3. Smart money — recent trades from watched top performers
4. Leaderboard — top 10 traders by PnL with win rates
5. Top 20 markets — volume, prices, end dates
6. Near-resolution markets — ending within 48h with 90%+ dominant outcome
7. Stock market data — Polymarket finance markets + live SPY/QQQ/Gold/Oil
8. Thesis board — running hypotheses from previous cycles
9. Recent thinking — agent's own analysis from last few cycles

## Thesis Board
The agent maintains persistent investment theses that survive across cycles:
- **CREATE**: when a developing pattern is spotted
- **UPDATE**: when new evidence arrives (confirm or weaken)
- **CLOSE**: when resolved or invalidated

Stored in `data/agent_theses.json`.

## Audit Trail
- **Thinking journal**: `data/agent_thinking.jsonl` — full reasoning each cycle
- **Trade journal**: `data/trade_journal.jsonl` — every entry/exit with reason
- **Google Sheets**: Trades tab + Thinking tab
- **Twitter**: @BotPolyJoris — public thinking feed
