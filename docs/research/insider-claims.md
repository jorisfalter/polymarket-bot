# Insider claims → paper follow (2026-11-16)

## Why

Joris: "we waren sloppy, er waren wel edges". The KPMG wallets (EventWaves, Feb 2026)
and the Ballon d'Or 2026 leak were real and followable, but our pipeline never acted
on the public reports. And the insider detector itself was blind (see below).

## Finding 1 — the detector was blind (fixed)

- Polymarket retired Data API v1: `/trades`, `/positions`, `/pnl`, `/v1/leaderboard`
  return **410 Gone**. Every scan logged `Total alerts: 0`. The client now uses `/v2`
  (snake_case, cursor pagination) and maps records back to v1 keys (`_v2()`, `_to_v1()`
  in `backend/polymarket_client.py`).
- The large-trade scan now uses server-side `filter_type=CASH&filter_amount=<min>`, so it
  sees up to 1500 trades ≥ min instead of the last 1500 trades of any size.
- Prices were passed as 0-1 while the detector's `Trade` works in cents: a $6.7k bet at
  0.70 was scored as a $67 bet at 0.7¢ (fake extreme longshot → bogus "high" alerts).
- Wallet volume used `size*price/100` → every bet looked ≥5× the wallet's average.
- The Twitter bearer token returns 401: `fetch_twitter_intel()` has been silently empty.
- Alerts live only in memory (500 cap), so past misses cannot be audited.

## Finding 2 — the November claims, replayed on trade data

| Case | What the trade data shows | Followable? |
|---|---|---|
| **Ballon d'Or 2026** (Upside 23 Oct, In Game 6 Nov) | Wallet `0xdd97e6ad12…` created 20 Oct, same day $21k on exact #2-#5; `0x71ae923f12…` created 22 Oct, $24.6k, Ballon d'Or only. Kane 0.76 on 23 Oct, 0.68 on the day; 2nd/3rd/5th 0.70-0.75. All paid 1.0. | **Yes, ~+40%, for days**, also after the article |
| **Times/Siena poll** (NYT 7 Nov, Vanderbilt) | ~$200k on Ricketts 1h before the poll. After the jump the Republican side sat at ~0.72 for days → 1.0. | Yes, after the poll |
| **Israel election** (Bloomberg 29 Oct) | 600+ same-day wallets on Netanyahu/Likud before polls closed. Likud 25-29 seats paid; but "Netanyahu next PM" now trades at 0.20. | A cluster is not automatically right |

## Finding 3 — the generic rule does NOT work

`scripts/research/fresh_wallet_backtest.py`: all non-sports BUYs ≥ $5k since 2026-08-15
(11,751 trades, 7,522 wallet×market bets). Fresh = wallet's first activity ≤ 7 days
before the bet. Follow = token price 1h after the first buy; outcome from CLOB price
history (13-day windows; longer windows return 400).

| Group | n | won | mean follow return | t |
|---|---|---|---|---|
| Fresh, elections | 223 | 64% | +18.3% | +2.2 (one election night, highly correlated) |
| **Fresh, non-election** | 79 | 49% | **−23.4%** | −2.6 |
| Non-fresh sample | 482 | 75% | +5.2% | +1.3 |

Most fresh non-election whales are news gamblers (e.g. ~12 fresh wallets betting Jensen
Huang would *not* resign, all lost; daily "Ukraine targets Moscow" bets). A fresh wallet
is not an insider. What set Ballon d'Or/KPMG apart is the **market type**: the outcome
already existed and was known to a small group (jury vote, audited numbers, finished poll).

## What we built

- `scripts/fetch_insider_claims.py` + `scripts/claims_sentinel.{sh,md}`: every 6h, Google
  News + X (Firecrawl search) + EventWaves; only new items go to a headless Claude that
  extracts claims, resolves usernames → wallets (Gamma `public-search?search_profiles=true`),
  adds them to the paper follower and journals the claim (`/home/app/sentinel/claims_journal.jsonl`),
  with `followable` = market still open and price ≤ 0.85.
- `backend/sharp_follow.py`: per-wallet market filter (`markets`: regex or `any`; default
  earnings for the KPMG seed), CLI `add` / `list`.

## Open

- EventWaves (1 Sep 2026): WSJ reported a KPMG employee under investigation; the author
  offers a spreadsheet of *all* suspect accounts by email (matt@eventwaves.io) — Joris to ask.
- No Telegram yet for followable claims (Telegram is restricted to macro-BTC/earnings-gap).
- Next measurable rule to test: fresh wallet + `predetermined` market category only
  (awards, poll releases, rankings) — n is small today.
