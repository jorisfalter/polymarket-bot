# Maker-mode market shortlist

> **Status (2026-05-31)**: live-pulled per cycle via `backend/maker_shortlist.py`. This doc explains *how* the picks happen + lists a sample at freeze time.

## Selection criteria

Picks 3 markets per cycle from Polymarket's crypto-prices tag (paper footnote 13: maker rebates active since 2026-03-06 → wider spreads). Hard filters:

| Filter | Value | Why |
|---|---|---|
| Tag | `crypto-prices` | Maker-rebate categories per paper |
| Mid price | 0.15 — 0.85 | Avoid favorite-longshot bias zone; avoid 1-tick spreads at extremes |
| 24h volume | ≥ $1,500 | Need actual flow for fills |
| Spread | ≥ 2c | Need room to capture spread (1-tick markets have no maker edge) |
| Hours-to-end | 6h ≤ end ≤ 168h (1 week) | <6h = CLOB rejects orders; >1w = capital tied up too long |

Score: `spread_cents × sqrt(volume_24h)`. Spread is the primary driver (paper finding: maker P&L ≈ spread captured × fill rate); volume enters as sqrt because past a threshold, more flow only helps fill rate diminishingly.

## Override mechanism

`config.maker_target_token_ids` — if non-empty, the auto-pick is skipped and these exact token IDs are used. Use this to:
- Lock onto a specific market you have a thesis on
- Test against a single market during dry-run
- Opt into long-dated markets (Hyperliquid year-end etc.) that the auto-pick filters out

## Sample picks (2026-05-31)

For reference — the auto-pick at freeze time produced these top candidates:

| Score | Spread | Vol 24h | Mid | Ends | Market |
|---|---|---|---|---|---|
| 824 | 3.0c | $75,542 | 0.235 | 19h | Will Bitcoin reach $75,000 in May? |
| 245 | 5.0c | $2,399 | 0.665 | 79h | Ethereum > $2,000 on June 3 |
| 218 | 4.0c | $2,977 | 0.760 | 31h | Ethereum > $2,000 on June 1 |
| 215 | 4.0c | $2,900 | 0.490 | 55h | Bitcoin > $74,000 on June 2 |
| 142 | 3.0c | $2,246 | 0.695 | 55h | Ethereum > $2,000 on June 2 |

Top 3 (default `DEFAULT_TOP_N=3`) become the maker targets for the next cycle. The list refreshes every cycle (`maker_cycle_seconds = 30s`), so new markets bubble in as old ones approach resolution.

## What this list does NOT contain (and why)

- **Hourly BTC/ETH markets**: too volatile fair-value; tick spread is usually 1c (no edge).
- **SOL markets**: no middle-probability candidates with sufficient volume at writing.
- **Sports / politics**: tag-filtered out; paper says top performers cluster in sports but our config explicitly blocks them (reputation), and politics rarely has 2c+ spreads outside of micro-cap markets.
- **Long-dated (>1 week)** like Hyperliquid year-end: filtered out by default. Opt-in via config override only.
- **Sub-$1500 daily volume**: filtered out. Even with wide spread, no fill = no edge.
