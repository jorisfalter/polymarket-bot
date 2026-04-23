# 0xRicker — The Math That Made $1M+ for Quant Traders in 30 Days

**Source:** https://x.com/0xRicker/status/2044722741706678282 (Apr 16, 2026)

## Core Claim
Three Polymarket wallets running the same mathematical framework (Markov chain state-persistence) made **$1.33M combined profit across 48,061 predictions in 30 days** during March–April 2026. Not luck — a concrete, reproducible entry rule.

## The Decision Engine
One function, two conditions, both must be true:

```python
def should_enter(P, current_state, market_price, tau=0.87, eps=0.05):
    j_star = np.argmax(P[current_state])     # optimal next state
    p_hat = P[current_state][j_star]         # model probability
    persist = P[j_star][j_star]              # state persistence (diagonal)
    gap = p_hat - market_price               # arbitrage gap (delta)
    return gap >= eps and persist >= tau     # eq.(2.2) AND eq.(2.3)
```

- **Arbitrage gap** ≥ 5% (model's implied probability beats market price by at least 5 cents)
- **State persistence** ≥ 0.87 (the optimal next state is ≥87% likely to hold)
- Runs once per minute, every market, 24h/day.

## The Three Wallets

| Wallet | Strategy | Entry window | Notes |
|---|---|---|---|
| `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` ("Bonereaper") | High-Confidence Spread Capture | 83–97¢ on hourly BTC/ETH | 1,500–2,900 shares/position, 4–19% per resolution, lowest variance |
| `0xe1d6b51521bd4365769199f392f9818661bd907c` | Dual-Mode EV | 64–83¢ directional + 99.5–99.8¢ price locks | Best single trade: $42,200 at 64.7¢ entry (54.6% return) |
| `0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82` | Multi-Asset Variance Reduction | 1.3¢ entries on 5-min windows across BTC/ETH/SOL/BNB/XRP | σ reduced 55%, ~1 trade per 1.7 min |

All three are on our watchlist (`data/watched_wallets.json`) — the agent gets their trades fed via smart-money copy (Strategy 2).

## Why It Works
**The off-hours edge:** Polymarket crypto windows are priced by humans. Humans are not online at 3 AM watching a 5-minute BTC window. Prices become "lazy, stale, and exploitable" when attention drops.

**Compounding:** 0.034% per trade becomes ×240 at 16K trades via the law of large numbers.

**Kelly Criterion (eq. 2.17):** `f* ≈ 0.71` — high enough to compound aggressively, low enough to avoid ruin.

## Applicable to Our Bot
- Watchlist these 3 wallets ✓ (done)
- Consider Kelly-sized positions (currently fixed $1-10 per trade — could be improved)
- Exploit off-hours mispricing in the near-resolution strategy (not yet implemented — current agent runs every 15 min regardless of hour)

## Key Quote
> "The market rewards people who understand probability. Everyone else is just providing the liquidity."
