# Listing-pump fade on Hyperliquid (2026-11-18)

Joris pushed back on "you can't make money on listings": a bot has more than enough time.
He was right that the bot case was untested. Result: buying after the announcement doesn't
pay, but **shorting the pump does**, and it doesn't need speed.

## Data
- Events: cryptolisting.ws `data/recent-announcements.json` (350 announcements since
  9 Apr 2026, microsecond detection times). `spot_listing` only, ticker must have a
  Hyperliquid perp. Same coin within 3 days = one episode (Upbit + Bithumb often list the
  same coin). Upbit's own notice API also works (`api-manager.upbit.com/api/v1/announcements`,
  816 notices, rate-limited).
- Prices: Hyperliquid `candleSnapshot` 1h (only the last ~5000 candles: ~205 days), funding
  from `fundingHistory`.
- Scripts: scratchpad `hl/fade.py`, `hl/control.py` (copy the logic from `backend/listing_fade.py`).

## First look (5/15-min candles, Oct-Nov, n=8): the long side
From the announcement to a bot entry 5-15 min later the coin was already up +9.4% on average
(8/8). From there a long was −0.7% after 1h, −3.7% after 4h, −11.8% after 24h (0/8). A bot
buying 5-15 min late earns nothing. Whether seconds-fast entry pays could not be measured
(1-minute candles only reach back 3.5 days).

## Backtest: short the pump (1h candles, Apr 25 - Nov 17, n=21 episodes)
Short at the open of the first full hour after detection (0-60 min late), hold, long the same
notional of BTC. Funding received by shorts included, 0.25% round-trip cost.

| | mean | median | won | t |
|---|---|---|---|---|
| pump until entry | +12.1% | +9.9% | 20/21 up | |
| net after 4h | +2.0% | +1.8% | 14/21 | 1.4 |
| **net after 24h** | **+7.1%** | +6.7% | 18/21 | 3.3 |
| net after 48h | +8.9% | +8.2% | 18/21 | 4.1 |

**Control** (is this just "small alts bleed vs BTC"?): the same short-vs-BTC trade on 12
random mid-volume alts at the same moments: listing coin beat the basket by **+8.1%/24h**,
median +7.7%, 18/21, t=3.9. The effect is listing-specific.

By exchange: Upbit 18 episodes (+7.4%, 15 won), Binance 2, Bithumb 1. First half +5.9%,
second half +8.1%. Worst cases −19% (SPX, Jun), −8.5%, −8% (NIL, CRV, Aug): short squeezes.

## Longer test: two years of Upbit listings (added same day)
Upbit's own notice API (`api-manager.upbit.com/api/v1/announcements?category=trade`, 816
notices since 2017, 425 listings; use `first_listed_at`, skip titles with 취소 = cancelled).
Hyperliquid 4h candles reach back ~820 days, so entry = open of the first 4h candle after the
notice (0-4h late). Scratchpad `hl/fade_upbit.py`.

| Upbit, Aug 2024 - Nov 2026, n=77 | mean | median | won | t |
|---|---|---|---|---|
| no stop | +2.0% | +4.7% | 55/77 | 0.8 |
| vs alt basket | +4.2% | +6.4% | 65/77 | 1.9 |
| stop 15% (+2% slippage) | +3.9% | +4.7% | 52/76 | 2.7 |
| **stop 20%** | **+4.4%** | +5.0% | 55/76 | **3.0** |
| stop 30% | +4.3% | +5.0% | 55/76 | 2.7 |

Per year (no stop): 2024 +4.2% (n=11), 2025 +0.5% (n=42), 2026 +3.7% (n=24). 2025 holds the
squeezes: HYPER −122%, XPL −71%, 0G −63%, AZTEC −48%, AVNT −26% (Sep 2025 launch frenzy).
Filtering out coins that traded < 7 days on Hyperliquid does not remove them. Same window on
1h candles (n=16): +7.8%, 14/16, t=3.1.

So the median trade is a reliable ~+5%, but the left tail is fat: **a stop is required**. The
paper bot uses a 20% stop (checked every 2 min).

## Caveats
- n=21, one 7-month regime; mostly Upbit (Korean retail pump).
- Survivorship: only coins still listed on Hyperliquid today.
- Fill assumption: open of the hour at the mid; on thin coins the real short fill is worse
  than the 0.25% assumed right after a pump.
- No stop-loss tested; the losers are squeezes of 8-19%.
- "Fade the Upbit pump" is a known idea among crypto traders; it can decay.

## What runs now
`backend/listing_fade.py` (scheduler every 2 min, `/api/listing-fade/status`): paper only,
same rules as the backtest, $100 notional, journal `data/listing_fade.jsonl`. Promotion
criteria are the same spirit as the other lanes: n≥20-30 live paper episodes with a mean
near the backtest, and only on Joris' explicit request.
