# Stocks — Strategy Playbook

Strategies for the **/stocks** dashboard. Currently manual execution — no broker integration yet. The dashboard surfaces signals; user makes the trade.

---

## Strategy 1: Short Squeeze Plays
**Data source:** yfinance (short interest %, days-to-cover, float) + Quiver (politician/insider buying as confirmation)

**Logic:** When short interest exceeds 25-30% of float AND a single holder crosses the 10% ownership threshold, you have the structural setup for a Section 16-driven squeeze. Avis (CAR) was the canonical 2026 example: SI 49% + Pentwater 39% economic interest → stock went from $99 to $713 in a month.

**Trigger:**
- Short interest ≥ 25% of float
- One holder owns ≥ 10% (recent 13D/13G filing)
- Days to cover ≥ 5 days (low buying-back capacity)
- Recent positive catalyst or insider/politician buying on the same name

**Edge:** When shorts have to cover and one holder is constrained from selling, supply collapses. The holder can still sell INTO the squeeze for legitimate reasons (Section 16 short-swing-profit rules apply, but most accounts can structure around it).

**Risk:** Squeezes are unpredictable in timing. Position sizing matters — ATM call spreads or small share positions, never naked calls.

**Currently surfaced on dashboard:** ✅ Squeeze Setups panel scores by SI + politician activity.

---

## Strategy 2: Politician Following ("Pelosi Tracker")
**Data source:** Finnhub `/stock/congressional-trading` (free tier, 60 calls/min, requires `FINNHUB_API_KEY`). Switched from Quiver after they dropped public access in early 2026.

**Logic:** Members of Congress consistently outperform broader markets. Studies put their alpha at 6-12% vs SPY annually. Disclosure delay is up to 45 days — but the trades that disclose late often still have legs.

**Reliability tiers** (the dashboard surfaces these so you don't chase noise):
- 🟢 **Reliable** — 20+ trades AND beats SPY ≥55%. Track record is statistically meaningful.
- 🟡 **Moderate** — 10-19 trades. Meaningful but not bulletproof.
- 🟠 **Weak** — 5-9 trades. Interesting, small sample.
- 🔴 **Small sample** — <5 trades. α numbers are noise.

A 2-trade politician with +25% α is one good Apple buy, not skill. Don't be fooled by the leaderboard sort.

**Currently confirmed reliable** (as of April 2026):
- **Markwayne Mullin** (R-OK, Senate Banking Cmte) — 99 trades, +11.4% α, beats SPY 61%. Real signal.
- **Tim Moore** (R-NC) — 15 trades, +8.3% α, beats SPY 80%.

**Trigger:**
- 🟢 or 🟡 reliability politician makes a new disclosed trade
- Trade is a **purchase** (sales noisier — could be rebalancing)
- Amount range ≥ $50,001-$100,000 bracket
- Within 7 days of disclosure (older = priced-in)

**Edge:** Information asymmetry. Members of Congress sit on legislative + intel committees that move markets. Their staff too.

**Watch closely feature:** Click ☆ next to a politician on /stocks to add them to your personal watchlist. Watched politicians:
- Get pinned to top of the table with green tint
- Trigger an **email alert** to `ALERT_EMAIL` (or `GMAIL_ADDRESS` fallback) when they file a new trade
- Scheduler checks every 30 min; dedup state in `data/politicians_seen.json` prevents repeat alerts

**Currently surfaced on dashboard:** ✅ Top Politicians table with reliability tiers + ☆ stars + Recent Trades feed.

---

## Strategy 3: Insider Buying (Form 4)
**Data source:** SEC EDGAR Form 4 filings (free RSS feed, not yet integrated)

**Logic:** Corporate officers and directors must disclose stock transactions within 2 business days. Insider **buying** is a much stronger signal than insider selling (selling has many reasons; buying has one — they think it's going up). Particularly powerful: cluster buys (multiple insiders buying within a few weeks) and CEO purchases of $100k+.

**Trigger:**
- Form 4 "P" (purchase) filing
- Amount ≥ $100,000
- Cluster: 3+ insiders buying within 30 days
- Buyer is C-suite (CEO, CFO) — board members carry less signal

**Edge:** Insiders have legal information advantage on company performance. They can't trade on material non-public information but they can act on their general read of the business.

**Currently surfaced:** ✅ SEC Form 4 panel on /stocks shows recent filings with link-through to filing detail (purchase vs sale visible there).

---

## Strategy 4: 13D/13G Activist Filings
**Data source:** SEC EDGAR 13D/13G filings (free, RSS available)

**Logic:** Any party crossing 5% ownership in a public company must file a 13D (active intent) or 13G (passive). 13D is the activist signal — the filer plans to push for change (board seats, M&A, divestitures). Stock typically pops 5-15% on filing.

**Trigger:**
- New 13D filing (not amendment)
- Filer is a known activist fund (Pershing Square, Elliott, Starboard, Engine, Trian, ValueAct, etc.)
- Stake ≥ 7%

**Edge:** Activist campaigns extract value over months. Buying alongside a credible activist is asymmetric — they do the work, you ride the move.

**Currently surfaced:** ✅ 13D/13G panel on /stocks. Activist filings (Pershing Square, Elliott, Starboard, Engine, Trian, ValueAct, Icahn, Third Point, Jana, ValueAct, Ancora, Macellum, Scopia, Irenic) auto-flagged with a star and ranked first.

---

## Strategy 5: Post-Earnings Drift
**Data source:** earnings calendar + price action 1d post-release

**Logic:** Stocks that beat earnings continue drifting up for 30-90 days. Stocks that miss continue drifting down. Despite being one of the most documented anomalies in finance (since the 1960s), it persists because retail closes positions too early and institutions can't pile in fast enough on small/mid caps.

**Trigger:**
- Earnings beat: actual EPS > consensus by ≥10%
- Day-after price reaction ≥ +5% on volume ≥ 2× average
- Buy at close of day-1, hold 30-60 days

**Edge:** Persistent behavioral anomaly. Best on small/mid caps where coverage is thin.

**Currently surfaced:** ❌ Would need earnings calendar API + an automated post-earnings price scan.

---

## Strategy 6: M&A Spread Arbitrage
**Data source:** Manual — major M&A announcements

**Logic:** When Company A announces it'll acquire Company B at $X/share, B's stock typically trades at a 1-5% discount to $X until deal close. Deal closes → you collect the spread. Deal breaks → you take a 10-30% hit.

**Trigger:**
- All-cash deal with announced terms
- Spread ≥ 2% (annualized depends on close timeline)
- No major regulatory red flags
- Both companies are US-listed

**Edge:** Predictable resolution event. Returns are bounded but consistent (~5-12% annualized when deals close as expected).

**Risk:** Deal breaks are catastrophic for this strategy. Diversification across 5-10 deals is essential.

**Currently surfaced:** ❌ Manual — would need M&A news feed + tracking spread evolution.

---

## Strategy 6.5: WSB Sentiment / Retail Flow
**Data source:** r/wallstreetbets JSON API (free, no auth). Reddit blocks Hetzner / data-center IPs so we route through the Fly.io trade-proxy in Tokyo (`/reddit/{subreddit}/{sort}`).

**Logic:** WSB is the canonical retail-flow leading indicator. When a ticker accumulates buzz (upvotes + comments) within 24h, retail money is moving. The 2021 GME / AMC squeezes, the 2024 NVDA run, the Avis (CAR) squeeze in April 2026 — all visible on WSB before mainstream coverage. Many WSB pumps fail; this is signal not gospel.

**Trigger:**
- Ticker buzz score (upvotes + comments/2 across hot+new posts) ≥ 5,000
- Multiple distinct posts mentioning the ticker
- Combine with another signal (squeeze setup, recent news, earnings) before acting

**The combo signal — Watchlist × WSB overlap:**
A ticker on your stock watchlist (Squeeze Setups) that also appears in WSB buzz is the strongest combination we have — high short interest + retail attention = AVIS pattern setup. Surfaced on the dashboard with a 🔥 badge and orange left-border. Email alert fires whenever this overlap appears.

**Spike detection:**
Scheduler checks every 30 min. Spike fires when:
- Ticker buzz ≥ 3× prior observation AND ≥3,000 buzz, OR
- Brand-new ticker entering the list with ≥5,000 buzz

State persists in `data/wsb_buzz_state.json` so each spike alerts once per move (next observation becomes the new baseline).

**AI agent integration:**
The Polymarket AI agent now receives the top-10 WSB buzz tickers in its 15-min cycle prompt. If a Polymarket market exists on a hot WSB ticker (earnings, price levels, election outcomes), the agent can incorporate WSB momentum as a soft signal.

**Edge:** Front-running the retail wave when it aligns with fundamentals. Ride 1-3 days, exit before euphoria breaks.

**Risk:** WSB pumps die fast and unpredictably. Position size like a moonshot, not a core trade.

**Currently surfaced:** ✅ Three layers:
1. WSB Ticker Buzz + Hot Posts panels on /stocks (refresh 10 min)
2. 🔥 cross-reference badge on Squeeze Setups when ticker overlaps WSB buzz
3. Email alerts (spike detection + watchlist overlap) every 30 min

---

## Strategy 7: Special Situations (Spinoffs, Tender Offers)
**Data source:** Spin-Off Research, manual press release tracking

**Logic:** Spinoffs are systematically under-covered for the first 6 months because the parent company's holders dump them (mandate mismatch). Empirically, spinoffs outperform the market by 10%+ in the year following separation.

**Trigger:**
- Newly spun-off company within first 90 days of trading
- Heavy initial selling pressure (down 10%+ from spin-off date)
- Profitable underlying business
- Clean balance sheet

**Edge:** Forced selling creates undervaluation. Joel Greenblatt wrote the book on this ("You Can Be a Stock Market Genius").

**Currently surfaced:** ❌ Manual.

---

## Implementation Roadmap

### Currently live on dashboard
- ✅ Strategy 1 (Squeeze Setups) — ticker watchlist + yfinance SI score + 🔥 WSB cross-reference
- ✅ Strategy 2 (Politician Following) — Finnhub feed + reliability tiers + ☆ watchlist + email alerts
- ✅ Strategy 3 (Insider Buying / Form 4) — SEC EDGAR full-text search, click-through to filings
- ✅ Strategy 4 (13D/13G) — SEC EDGAR with activist auto-flagging
- ✅ Strategy 6.5 (WSB Sentiment) — buzz panel + spike alerts + watchlist overlap + agent integration

### Not yet integrated
- Strategy 5 (Post-Earnings Drift) — needs earnings calendar API + price scanner.
- Strategy 6 (M&A Spreads) — Bloomberg / news feed required, harder to automate.
- Strategy 7 (Spinoffs) — manual research strategy, not great candidate for automation.

---

## Alert channel summary

The Stocks board uses **email** (Gmail SMTP via `GMAIL_APP_PASSWORD`) for low-volume high-signal alerts — the Telegram channel is reserved for the Polymarket bot's firehose (cycle thinking, trade fills, resolutions). Set `ALERT_EMAIL` in `.env` for a different destination, or leave unset to use `GMAIL_ADDRESS`.

Active alert types:
- 📢 Watched politician files a new trade (every 30 min check)
- 🦍 WSB ticker buzz spike (every 30 min check)
- 🔥 Watchlist ticker × WSB overlap (every 30 min check)

---

## Risk discipline (manual execution)

- **Max position size:** 5% of total stock book per single name
- **Stop-loss:** 15% from entry, no exceptions
- **Holding period:** strategy-specific (squeeze = days-weeks, drift = 30-60 days, spinoff = 6-12 months)
- **No naked options** — only spreads, defined-risk
- **Track everything** in a spreadsheet or via the dashboard manual log
