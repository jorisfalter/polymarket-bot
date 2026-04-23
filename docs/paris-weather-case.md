# Paris Temperature Tampering — April 2026

## Source
FT, 22 April 2026 — "French weather service alerts police to tampering after suspicious Polymarket bets". Météo-France filed a criminal complaint with the Air Transport Gendarmerie Brigade in Roissy after detecting anomalous temperature spikes at the Paris-Charles de Gaulle airport sensor on April 6 and April 15, coinciding with large profits on Polymarket's daily "Highest temperature in Paris" market.

## The markets
- **April 6**: `highest-temperature-in-paris-on-april-6-2026-21c`, conditionId `0xefb630b450bc264209fef9a27a6a94e0f54612c2f0f391f08b0629993e396bc7`. Resolved Yes at 21°C. Total event volume $778k (normally ~$250k).
- **April 15**: `highest-temperature-in-paris-on-april-15-2026-22c`, conditionId `0xdb8d12c38bb10135ee8b344deccfcf3a93abfc8427b5da2474e6c1eadff65b01`. Resolved Yes at 22°C. Total event volume $591k.

## The trades we identified
Via full trade history pagination (3000 trades per market) and the detector's new asymmetric-bet signal:

**April 6 — wallet `0xf1faf3f6ad1e0264d6cbecc1a416e7c536be047d`**
- 4 BUYs of the 21°C outcome between 16:49–17:51 UTC
- Prices 0.19c–5c, total stake ~$80
- Received 15,368 shares, resolved at $1 each → **~$15,288 profit**

**April 15 — wallet `0x1c0f3e4c90a48e4dd93d0abcdf719a5a5f1599d0`**
- 33 BUYs of the 22°C outcome between 19:39–22:23 UTC
- Prices 0.1c–3.78c, total stake ~$65
- Received 27,591 shares, resolved at $1 each → **~$27,526 profit**
- **Same wallet also bought the Apr 6 21°C market** — cross-day pattern is the strongest signal we have.

Multiple other wallets in both markets show the same pattern (BUY ≤3c, low stake, fresh wallet). Detector now raises HIGH-severity alerts for 7–8 wallets per market.

## Why we initially missed it
Two structural gaps:

1. **`min_notional_alert: 1000`** — the detector required a $1000+ stake to even generate an alert. The insider bets were $65–$80 totals, split into $1–$20 chunks. Classic insider pattern, but under the dollar-noise floor.
2. **Market selection bias** — the AI agent's 15-minute briefing only includes top-20 markets by volume. Daily Paris-weather markets never qualified until the manipulation event already inflated their volume, by which time it was too late to front-run.

## What we added (commit `8f25acb`)

1. **New signal: `♻️ Asymmetric Bet`** in `backend/detectors.py`
   - Triggers: BUY side, price ≤3c, stake ≥$5, payoff ratio ≥30x
   - Bypasses `min_notional_low` (since the edge is payoff-ratio, not stake-size)
   - Caps severity at HIGH (never CRITICAL, because dollar amount is small)

2. **Config entries** in `backend/config.py`:
   - `asymmetric_max_price_cents: 3.0`
   - `asymmetric_min_notional: 5.0`
   - `asymmetric_min_payoff_ratio: 30.0`

3. **Two new `KNOWN_CASES`** in `backend/backtester.py`:
   - `paris_temperature_apr6_2026`
   - `paris_temperature_apr15_2026`

4. **Backtester pagination** raised to 3000 trades per market (was 500), plus a latent price-normalization bug fix — `trade["price"]` was previously left as a raw 0–1 fraction when the detector expected 0–100 cents.

## What we still haven't solved

- **Market discovery.** The AI agent still won't automatically scan daily-weather markets unless they're in the top-20 briefing. The asymmetric-bet signal catches the trades *after* they're in our data stream, but the agent doesn't know to look at Paris weather on day 1. Future work: add a "daily repeating or single-day resolution" feed that surfaces low-volume markets with known patterns.
- **Live trailing signal.** We can detect asymmetric bets in historic data but haven't validated in live-scan. The next real insider case is our live test.
- **Whether we would have piggybacked.** The insiders bought at 0.19c. Even if we detected at 1c, the expected payoff is still ~100x. Question: should the AI agent be allowed to follow asymmetric signals with its own (tiny) stake as part of the moonshot book? Current answer: yes, and this is explicitly encouraged in the trading philosophy.

## Regression testing

```bash
./venv/bin/python -c "
import asyncio
from backend.backtester import backtester
async def main():
    for case_id in ['paris_temperature_apr6_2026', 'paris_temperature_apr15_2026']:
        r = await backtester.run_known_case(case_id)
        print(case_id, 'top_score:', r.top_score, 'alerts:', sum(1 for s in r.suspicious_trades if s.get('is_alert')))
asyncio.run(main())
"
```

Expected: both cases produce HIGH-severity alerts on the named insider wallets.
