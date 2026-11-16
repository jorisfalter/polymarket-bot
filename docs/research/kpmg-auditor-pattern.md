# KPMG-auditor pattern on Polymarket earnings markets: replication

**Source:** Matt Lamers, EventWaves, "KPMG-Audited Companies are Trading Strangely on Polymarket", 24 Feb 2026, https://eventwaves.substack.com/p/kpmg-audited-companies-are-trading. The author alleges no wrongdoing ("I'm not saying anything nefarious is occurring").

## Claim
A handful of wallets bet small on most "Will X beat quarterly earnings?" markets, but big on companies audited by KPMG, and win those. The article names 13 wallets.

## What our bot did (Mar–May 2026)
- `ai_agent._check_auditor_patterns()` + `auditor_data.py` (strategy 5).
- It only ran on wallets the detector had already alerted on, and those alerts needed a $1,000+ stake.
- It never fired: ~3,000 cycles say "auditor pattern: nothing". No trades.
- It never pulled a wallet's full earnings history, which is the article's method.

## Replication 2026-11-16
- **Wallet data:** full activity of the 13 wallets via the Polymarket Data API v2 (`/v2/activity`, cursor pagination).
- **Markets:** only titles containing "earnings"; 82 tickers.
- **Auditor per company:** SEC full-text search (efts) on 10-K/20-F/40-F filings since 2025-01-01. Per company, the Big-4 firm with the most hits counts as the auditor. Ties and 0 hits count as unknown and are left out (12 tickers).
- **Win** = sells + redeems > buys. This is conservative: winners that were never redeemed count as losses.

| Period | Group | n markets | Median stake | Won | Bet "Yes" |
|---|---|---|---|---|---|
| Before 24 Feb (in-sample: these wallets were picked for it) | KPMG | 42 | $951 | 39/42 (93%) | 21/42 |
| | other | 42 | $113 | 27/42 (64%) | 25/42 |
| **After 24 Feb (out-of-sample in time)** | **KPMG** | **20** | **$541** | **17/20 (85%)** | 11/20 |
| | other | 30 | $50 | 14/30 (47%) | 14/30 |

## Reading
- **The pattern holds after publication.** The wallets bet ~10× more on KPMG clients and win far more often. They bet on beats and misses about equally, so this is not "companies usually beat".
- **Caveats:**
  - small n;
  - the wallets were selected *because* they looked odd (survivorship of the pattern itself);
  - the auditor mapping is a text-search heuristic;
  - copy-trading: see the follow test below.
- **Not acted on.** Detection, not a strategy; no money.

## Follow test 2026-11-16: could a follower have copied them?
For each of the 13 wallets, take its largest BUY per market after 24 Feb 2026. For each delay, the follower's entry = the first CLOB `prices-history` point (1-minute fidelity) at or after bet time + delay. Payout = 1 if that outcome resolved Yes, else 0. Return = (payout − entry) / entry.

| Follow after | KPMG markets (n=17, 14 won) | Other markets (n=29, 14 won) |
|---|---|---|
| their own price | +36% avg (median +9%), entry 0.65 | +16% avg (median −100%) |
| +1 min | **+38%**, entry 0.62 | +19% |
| +10 min | **+39%** (n=15), entry 0.60 | +23% |
| +1 hour | +19% (n=15) | +23% |
| +1 day | +11% (n=12) | −15% (n=10) |

Reading:
- **The price does not run away after their bet.** Entry within 1-10 min is the same or cheaper. Speed matters on an hour/day scale, not seconds.
- **The hard part was knowing *which* wallets to follow.** That took a published track record (EventWaves, 24 Feb).
- **Caveats:**
  - n=17;
  - entry = last/mid price, not a fillable ask for a given size, so depth is untested;
  - wallets selected on past behaviour;
  - no fees.
- **Next step if pursued:** live paper-follow of known sharp earnings-market wallets. Not built.
