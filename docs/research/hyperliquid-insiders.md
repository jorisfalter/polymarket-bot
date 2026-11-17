# Hyperliquid insiders: can a follower profit? (2026-11-17)

Question (Joris): is Hyperliquid the next frontier for following insiders? All positions
are public (free API `api.hyperliquid.xyz/info`, no key).

## Case 1: "Trump insider whale" `0xb317d2bc2d3d2df5fa441b5bae0ab9d8b07283ae`
Shorted BTC/ETH before the 10 Oct 2025 tariff post (~$192M reported). `portfolio` allTime PnL:

| date | PnL |
|---|---|
| 15 Oct 2025 | +$93M |
| 14 Jan 2026 (peak) | +$156M |
| early Feb 2026 | **−$129M**, account value 0 (liquidated), flat since |

Following him after he became famous = following him into a ~$285M drawdown. One good call
(insider or luck) does not make a followable wallet.

## Case 2: Robinhood listings (proven insider)
Ex-Robinhood engineer pleaded guilty 16 Nov 2026: ≥11 Hyperliquid perp trades before listing
announcements, $125k profit. Kaiko (May 2026) saw OI/funding rise before LIT, ZEC, SNX, NEAR.

- LIT, 15 Jan 2026 (announcement 12:12 UTC): 4h volume rose ~$5M → $17M during the morning,
  price did not; at the announcement +11% spike, gone within the 4h candle.
- MON, 5 Oct 2026 (21:21 UTC): +2-3% at most, lower the next day. One volume spike (3.4M, 3h
  before) with a +1% move.
- Most Robinhood listings since Sep 2026 (cryptolisting.ws) are wallet memecoins not on
  Hyperliquid; only MON (and maybe AI, a different token) overlap.

The money was in knowing ~1h ahead and exiting within the hour. A follower who reacts to rising
volume can't separate it from ordinary noise, and the post-announcement pop fades fast.

## Not done / limits
- Wallets that hit several listings (the KPMG-style follow list): the public API has no
  historical trades per coin (only recent; per user ≤10k fills). Needs the requester-pays S3
  node-fills archive or Kaiko data. Not attempted.
- Old hourly candles: only the last ~5000 candles per interval (use 4h for early 2026).

## Verdict
No followable edge found. Same lesson as Polymarket: the edge sits with the person who knows,
inside a window shorter than a follower's reaction time; famous "insider" wallets are not
reliably right afterwards.
