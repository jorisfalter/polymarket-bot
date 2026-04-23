# Movez — 99.3% Win Rate Copy-Trading Algo

**Source:** https://x.com/0xMovez/status/2044801885870113084 (Apr 16, 2026)

## Core Claim
A Polymarket bot backtested on **72M trades** that printed **+$820K across 28,000 predictions** with a **99.3% win rate**. Not by gambling — by systematically finding mispriced high-probability contracts.

## The Key Insight
> From 72M trades, one pattern stands out: traders **overpay for cheap contracts** in the 0.1¢–50¢ range. **Most of the real edge shows up in 80¢–99¢ contracts**, where the bot does most of its trading.

This directly contradicted our previous approach. We were only looking at 95%+ markets for resolution arbitrage. The real edge starts at 80¢. Already updated in **Strategy 3 (Near-Resolution Mispricing)**.

## The Three-Step Algo

### 1. Mispricing Formula
```
δ = actual win rate − implied probability
```
Applied to every trade. Positive δ means the market is underpricing a likely outcome. Bigger δ = bigger edge.

### 2. Expected Value Check
```
EV = (P_win × Payout) − (P_lose × Cost)
```
Filters out trades that look mispriced on paper but don't pay enough to matter.

### 3. Kelly Criterion Sizing
```
f* = (p × b − q) / b
```
Bet exactly the fraction of the bankroll that maximizes long-term growth.

**Pipeline:** Mispricing found → EV calculated → Kelly sizing applied → enter trade.

## The Wallet
https://polymarket.com/profile/0x751a2b86cab503496efd325c8344e10159349ea1 (publicly shared, copy-tradeable via Ares bot per author).

## Applicable to Our Bot
- **Already shipped:** Strategy 3 refocused to 80–99¢ range (commit from April 2026).
- **Not shipped:** Kelly sizing. We still use fixed $1–10 per trade. Should revisit — especially for moonshots where per-trade size could be a function of (price, confidence).
- **Not shipped:** 72M-trade backtest-derived win-rate tables per outcome type. Would require historical trade data at scale — likely out of scope for now.

## Caveat
The 99.3% win rate is the author's self-reported backtest figure. Take with salt: survivor bias, optimization over historical data, and "backtested on 72M trades" doesn't mean "executed on 72M trades". The underlying principle (traders underprice high-probability outcomes) is well-documented in prediction-market literature and holds regardless.
