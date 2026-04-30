# Trading Philosophy — Entertainment + Edge

**Purpose of this document:** lock in the philosophy so we don't drift. The system exists for two reasons, in this order:

1. **Entertainment and content** — daily stories to share on social (Telegram, X, whatever). Every day must produce something worth talking about.
2. **Edge** — systematic detection + AI agent should make money, or at least not lose much. Small account, real money, real risk.

If a change improves edge but kills the narrative, we skip it. If a change makes it more fun without breaking the edge, we do it.

---

## Three Boards

The system is split into three independent boards, each with its own dashboard and playbook:

- **🎯 Polymarket** (`/agent`) — the AI bot trades autonomously, real money, $100 cap. Strategy playbook: [`polymarket-strategies.md`](polymarket-strategies.md). Sub-pages: Dashboard / Research / Playbook / Detection / Engine.
- **📈 Stocks** (`/stocks`) — manual execution. Surfaces signals: squeeze setups, politician trades (with reliability tiers + ☆ watchlist), Form 4 insider transactions, 13D/13G filings, WSB buzz with spike alerts. Playbook: [`stocks-strategies.md`](stocks-strategies.md).
- **₿ Crypto** (`/crypto`) — manual execution. Funding rates, perp/spot basis, cross-exchange spreads, stablecoin yields, liquid staking premium. Playbook: [`crypto-strategies.md`](crypto-strategies.md).

Each board uses **its own alert channel**:
- Polymarket → **Telegram** (firehose: cycle thinking, trade fills, resolutions, daily summary)
- Stocks → **email** (low-volume high-signal: politician watchlist trades, WSB spikes, watchlist × WSB overlap)
- Crypto → no alerts yet — dashboard refresh-and-look

---

## The Three Books (Polymarket)

The Polymarket AI agent runs three "books" with different sizing and philosophies. This mirrors how a real trader thinks and gives us three distinct stories per day.

The agent runs three separate "books" with different sizing and different philosophies. This mirrors how a real trader thinks, and gives us three distinct stories per day.

### 📘 Core Book — high-conviction edge
- ~70% of total exposure
- Only trade when multiple signals align: insider alert + fresh wallet + extreme odds, or near-resolution mispricing with clear fundamentals, or cross-market inconsistency with ≥10% gap.
- Target win rate: 65%+
- Typical size: $5–10 per position
- This is where the real P&L comes from.

### 🚀 Moonshot Book — asymmetric longshots
- ~20% of total exposure, max $20 at any time
- Explicitly budgeted for low-probability / high-payoff bets (30x+ payoff multiple).
- The Paris-weather pattern lives here: buy at ≤3c when something smells fishy, lose small or win 50x.
- Target win rate: can be 10%. One 50x win pays for a lot of misses.
- Typical size: $1–3 per position, split across 3–5 live moonshots.
- Explicit mandate: **at least one moonshot exploration per day.** Even if nothing qualifies, the agent reports what it looked at.

### 🎯 Opportunistic Book — news-reaction swings
- ~10% of exposure
- Short-duration trades (<48h) driven by breaking news, stock market divergence, or a developing story.
- Size: $2–5
- Target win rate: 50-60% — these are directional bets with modest edge.

**Hard rule:** never rebalance books by force. If Core is full at $70 and a moonshot appears, take it from Moonshot budget, not by closing a core position.

---

## What We Trade On

| Strategy | Book | Typical trigger |
|---|---|---|
| 1. Insider signals (HIGH/CRITICAL alerts) | Core | Fresh wallet, big bet, unlikely outcome |
| 2. Smart money copy | Core | Top-trader takes new position in their specialty |
| 3. Near-resolution mispricing (80-99c) | Core | Dominant outcome, <48h left, clearly certain |
| 3b. Daily repeating base-rate plays | Core | 10+ consecutive Yes resolutions, priced ≤95c |
| 4. Stock market arbitrage | Opportunistic | Polymarket diverges from real SPY/QQQ |
| 5. Auditor pattern (KPMG) | Core | Fresh wallet betting only on one auditor's clients |
| 6. Market inconsistencies | Core | P(X by April) > P(X by Dec) — near-riskless |
| 7. Own conviction | Opportunistic | Clear thematic story from news |
| 8. Asymmetric bet (Paris pattern) | Moonshot | BUY ≤3c, stake ≥$5, 30x+ payoff, fresh wallet |

---

## Daily Narrative Mandate

Every day the agent must produce a **daily summary** at 09:00 UTC with this structure:

1. **Headline** — one sentence. What's the story of the last 24h?
2. **Scoreboard** — P&L over 24h / 7d / lifetime. Open positions count. Exposure vs cap.
3. **Biggest win + biggest loss** — name the market, show the numbers. No hiding.
4. **Theses on the board** — 3 running investment theses with conviction level.
5. **Moonshots live** — what longshots are currently in play, at what price, for what payoff.
6. **Today's watchlist** — 2–3 markets to keep an eye on, and why.
7. **Moonshot for today** — one new asymmetric bet candidate, even if tiny ($1–2). If nothing qualifies, explain what was considered and why it was skipped.
8. **Trader's take** — 1–2 sentence personality take on the day. This is the part that makes it fun to read.

The output is structured enough to be copy-pasted straight to X/Telegram/LinkedIn. No cleanup needed.

---

## Tone and Personality

- **Cautious but decisive in core book.** Never trade because "it's Tuesday and we haven't traded today."
- **Degenerate but disciplined in moonshot book.** Take shots, but within the budget. Each loss is a funded experiment.
- **Transparent about losses.** A bad day reported honestly is more compelling than a fake-win narrative.
- **Specific, not generic.** Name markets, prices, wallets, counterparties. "We bought Paris 21°C at 0.19c" beats "we took a weather bet."
- **No fake humility, no fake bravado.** Neither "I am but a humble AI" nor "ALPHA SECURED." State what you did, why, and what you think will happen.

---

## What We Explicitly Don't Do

- Sports betting
- Crypto price markets (BTC/ETH daily price levels) — too noisy, too exploited
- Entertainment/celebrity markets unless there's a clear insider signal
- Trades purely because "we haven't traded in a while"
- Max-leverage swings outside the moonshot budget

---

## Review Cadence

- **Weekly:** glance at the last 7 daily summaries. Are the stories interesting? Are the moonshots showing any payoff? Adjust sizing if needed.
- **Monthly:** revisit this file. Is the 70/20/10 split still right? Has the social-media angle earned anything (followers, DMs, opportunities)? If the entertainment value is there but edge is down, rebalance toward core. If edge is up but it reads like a spreadsheet, lean more moonshot.

---

## Known Cases in Memory

These live in `backend/backtester.py` as `KNOWN_CASES` — replay-able regression tests for the detector:

- Maduro capture (Jan 2026)
- Nobel Peace Prize (2025)
- Taylor Swift engagement (Aug 2025)
- Google Year in Search (2025)
- Iran strikes (Feb 2026)
- **Paris temperature tampering — April 6 & 15, 2026** (asymmetric-bet pattern)

Every time we spot a new insider case in the wild, add it as a known case. It's our test harness.
