# Polymarket Trade Execution — Failure Modes & Pre-flight Checks

Operational doc on **why** Polymarket trades fail and the layered checks that prevent silent rejections. Read this when a `❌ Trade failed` shows up on Telegram and the reason isn't immediately obvious.

---

## The `order_version_mismatch` problem

Polymarket's CLOB returns a single error code — `order_version_mismatch` — for **at least six structurally different conditions**. The string is misleading: it suggests an EIP-712 / contract-version issue, but in practice fewer than half of these failures are actually about signing versions. The rest are market-state issues that Polymarket maps to the same error code.

We've cataloged each cause and added pre-flight checks (in the trade proxy) and agent-side guards (in `backend/ai_agent.py`) that surface a clean reason instead of letting the trade hit Polymarket and get rejected.

---

## The six known failure modes

### 1. UMA market disputed
**Symptom:** trade fails on a market that's still listed as `closed=False, active=True` in Gamma metadata.
**Trigger example:** *Clavicular pregnancy in 2026?* — the market was listed as active but its UMA resolution had been challenged.
**Detection:** `gamma /markets ... → umaResolutionStatus == "disputed"` (or `"challenged"`).
**Where caught:** `trade-proxy/main.py::check_market_tradeable`.
**User-facing reason:** `market not tradeable: UMA disputed (no orders accepted)`.

### 2. UMA market in proposed liveness window
**Symptom:** Same as above (market looks active, orders fail).
**Trigger example:** *MegaETH market cap (FDV) >$1.5B one day after launch?* — UMA resolver had submitted a proposal and we were inside the dispute window.
**Detection:** `umaResolutionStatus == "proposed"` (or `"resolved"`).
**Where caught:** Same pre-flight as #1.
**User-facing reason:** `market not tradeable: UMA proposed (no orders accepted)`.

### 3. `orderMinSize` violation
**Symptom:** Multi-outcome event markets (election outcomes, "...by date Z" chains) reject any order under their per-market minimum, but the error returned is `order_version_mismatch` not anything about size.
**Trigger example:** *Will Stephen A. Smith win the 2028 Democratic presidential nomination?* (orderMinSize = $5; agent submitted $1.05).
**Detection:** Gamma metadata exposes `orderMinSize` per market. Standard binaries: $1. Multi-outcome: typically $5.
**Where caught:**
- Pre-flight in proxy: refuses with clean reason if amount < min.
- Agent-side bump in `_execute_trades`: looks up `orderMinSize` and auto-bumps the proposed amount to `min + $0.05` if below, capped at `agent_max_per_trade`.
**User-facing reason:** `market not tradeable: order below market minimum (need ≥$5.00, got $1.05)` — but typically the agent auto-bumps so the user never sees this.

### 4. Token resolution failure on low-volume markets
**Symptom:** "could not resolve token ID for market X" — the agent's market_id lookup fails before any signing happens.
**Trigger example:** *Will the highest temperature in Lagos be 28°C or below on May 1?* — low-volume daily weather market, not in the top-500-by-volume cache, not findable via `/markets/{conditionId}` path lookup either (Gamma returns 422 for hex IDs).
**Detection:** N/A — this is a missing-data issue, not a market-state issue.
**Where caught:** `backend/ai_agent.py::_resolve_token_id` has a 3-tier fallback:
  1. `client.get_market(market_id)` — works for numeric DB ids only
  2. Top-500 markets by volume — substring/slug match
  3. `/public-search?q=<question_text>` — catches niche markets like daily weather, low-volume specialty
**User-facing reason:** `Trade failed: <market_question> | Reason: could not resolve token ID for market <id>` — should be rare now.

### 5. Empty / unfavorable orderbook
**Symptom:** Trade fails with `order_version_mismatch` but market is fully open. Underlying issue: the orderbook has no asks at the displayed price.
**Trigger example:** *Will the price of Bitcoin be between $80,000 and $82,000 on May 1?* — Gamma showed YES@1c but the cheapest CLOB ask was 99¢ (only contrarian high-priced asks existed). Buying at 99¢ for a 1¢ thesis isn't an asymmetric bet; CLOB rejects with the generic error.
**Detection:** `client.get_order_book(token_id)` then compare cheapest ask to `client.get_midpoint(token_id)`.
**Where caught:** `trade-proxy/main.py::check_orderbook_feasibility`.
**Refusal rules:**
- `expected_price < 0.10` AND `best_ask > expected_price × 5` → refuse (asymmetric bet thesis broken).
- `expected_price ≥ 0.10` AND `best_ask > expected_price × 1.5` → refuse (mid-range slippage too high).
**User-facing reason:** `orderbook unfavorable: orderbook too thin: best ask 99.00¢ vs displayed 1.00¢ (99× worse)`.

### 6. Orderbook 404 (expired market)
**Symptom:** Polymarket returns `status_code=404, "No orderbook exists for the requested token id"`.
**Trigger example:** *Ethereum Up or Down - May 1, 7:35AM-7:40AM ET* — short-window crypto price markets where the resolution window has already passed. CLOB tears down the orderbook after settlement; Gamma still lists the market in cached responses.
**Detection:** Catch the 404 from `get_order_book()` (string match on "404", "no orderbook", "not found").
**Where caught:** Same `check_orderbook_feasibility` function.
**User-facing reason:** `orderbook unfavorable: no orderbook exists (market likely expired/closed)`.

---

## Pre-flight chain (order of execution)

When `POST /buy` arrives at the proxy, we run these checks **before** signing or submitting any order. Each check that fails returns a clean reason; the order never reaches Polymarket's CLOB.

```
1. check_market_tradeable(token_id, amount_usd)
   ├── gamma /markets ?clob_token_ids=…
   ├── if closed → refuse
   ├── if archived → refuse
   ├── if not active → refuse
   ├── if acceptingOrders == false → refuse
   ├── if umaResolutionStatus in {disputed, challenged, proposed, resolved} → refuse
   └── if amount_usd < orderMinSize → refuse

2. get_midpoint() → expected_price (treated as 0 on dict-shaped response)

3. check_orderbook_feasibility(token_id, expected_price)
   ├── get_order_book()
   │   └── 404 / no orderbook → refuse (#6)
   ├── if no asks → refuse (#5 empty)
   ├── if expected_price < 0.10 and best_ask > expected_price × 5 → refuse
   └── if expected_price ≥ 0.10 and best_ask > expected_price × 1.5 → refuse

4. neg_risk lookup (CLOB-authoritative) — pass to PartialCreateOrderOptions
5. create_market_order + post_order(FOK) — only path beyond this point goes to CLOB
```

**Why pre-flight matters:** every check we add prevents a `❌ Trade failed: order_version_mismatch` Telegram message and replaces it with an actionable reason. The agent learns nothing from `order_version_mismatch` but it can adjust thinking when it sees `orderbook too thin` or `UMA proposed`.

---

## Agent-side guards (`backend/ai_agent.py::_execute_trades`)

Before the proxy is even called, the agent applies these guards:

1. **Action filter**: only `BUY` is supported (no SELL yet via the agent).
2. **Hard limits**: `amount_usd` capped at `settings.agent_max_per_trade` ($10).
3. **Below-minimum bump**: $1 minimum bumped to $1.05 to clear rounding.
4. **Malformed market_id check**: reject if `market_id` is not a 66-char hex string starting with `0x` (catches truncated agent outputs).
5. **Exposure cap**: skip if total exposure would exceed `agent_max_total_exposure` ($100).
6. **Slot cap**: skip if at `agent_max_positions` (30).
7. **Duplicate check**: skip if we already hold this market.
8. **Token resolution**: 3-tier fallback (see #4 above).
9. **`orderMinSize` auto-bump**: bump amount to per-market minimum before sending to proxy (so you don't waste a trade slot on a $1 attempt against a $5-min market).

---

## Adding a new failure mode

When a new `order_version_mismatch` (or other generic error) surfaces:

1. **Find the specific token_id** from the failed trade Telegram message.
2. **Inspect via Gamma**: `curl https://gamma-api.polymarket.com/markets?clob_token_ids=<id>` — look at all fields. New flag values often reveal the cause (e.g. `umaResolutionStatus: "proposed"` was unknown to us until we saw it).
3. **Inspect orderbook**: `client.get_order_book(token_id)` — empty? all asks suspiciously high?
4. **Check tick size + neg_risk + min size**: any divergence from expectation?
5. **Add a check** to `check_market_tradeable` (for state issues) or `check_orderbook_feasibility` (for liquidity issues). Return a clean reason string.
6. **Document the new mode here** — extend the table above.
7. **Deploy the proxy** (`fly deploy`) and verify with a test `curl -X POST /buy` against a known-bad token.

---

## Why we don't blame Polymarket more loudly

The `order_version_mismatch` error code is a single bucket for fundamentally different conditions because their CLOB matcher rejects orders at multiple stages and bubbles up the same error. We could file an issue or wait for a fix, but in practice:

- Polymarket has been consistent for 18+ months
- Pre-flight checks against Gamma metadata cost us ~10ms per trade
- Each new check we add prevents the same class of failure forever
- Cleaner errors help the AI agent reason about what to skip vs. what to retry

So we treat this as a **stable interface** to be wrapped, not a bug to wait out.

---

## Related operational notes

- **Auto-redemption**: Polymarket added auto-redeem in late 2026 — resolved positions automatically convert CTF tokens back to USDC in the wallet. Our journal still logs EXIT entries via the cashPnl-from-Data-API path; user doesn't need to manually claim.
- **Cash balance display**: `Cash idle` on the dashboard reads from `auto_seller.get_usdc_balance()` which routes through the proxy `/balance` endpoint. After auto-redeem, this should match the actual on-chain USDC balance.
- **Telegram volume**: every trade attempt (success or fail) sends a Telegram message with the cycle thinking. Trade failures send a separate `❌` message with the reason. Skipped trades (exposure cap, etc.) send `⏭️`. Resolved positions send `🎉`/`💀`.
