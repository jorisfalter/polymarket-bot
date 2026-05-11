# Polymarket Insider Detector + AI Trading Bot — Project Briefing

> **Purpose of this file**: complete onboarding briefing for a Claude session working on this repo, so a fresh session has the same context as one that's been around for months. Read this first.

---

## What this project is

A real-time surveillance system + autonomous AI trading bot for Polymarket. Two purposes (in this order, per `docs/trading-philosophy.md`):

1. **Entertainment + content** — daily stories worth sharing on social (Telegram firehose).
2. **Edge** — systematic detection + AI agent makes money, or at least doesn't lose much. Small account, real money, real risk.

Lives in three "boards" with separate dashboards and playbooks:

| Board | Path | Mode | Channel | Playbook |
| ----- | ---- | ---- | ------- | -------- |
| 🎯 Polymarket | `/agent` | Autonomous, $100 cap | Telegram | `docs/polymarket-strategies.md` |
| 📈 Stocks | `/stocks` | Manual exec | Email (disabled May 2026) | `docs/stocks-strategies.md` |
| ₿ Crypto | `/crypto` | Manual exec | Dashboard only | `docs/crypto-strategies.md` |

Polymarket agent runs three **books**: Core ($5-10), Asymmetric/longshot ($1-2 at ≤3c), Moonshot floor. Strategies 1-7 in `docs/polymarket-strategies.md`.

---

## Working directories

- **Local dev (Mac)**: `/Users/joris/Projects/polymarket`
- **VPS prod**: `/opt/polymarket-insider` on Hetzner (`ssh root@100.102.30.80` via Tailscale, or hostname `ubuntu-4gb-nbg1-1`)
- **Python venv**: `./venv/bin/python` (Python 3.10 on Mac). There is no `python` in PATH on the Mac — always use the venv.
- **Public URL**: `https://polymarket.ai-tigers.com` (Cloudflare → cloudflared tunnel → VPS port 8000). **Never modify Caddy for external routing** — external traffic comes through cloudflared.

## Entry points

- Local: `./venv/bin/python run.py` or `uvicorn backend.main:app --reload`
- Prod: `docker compose up -d` inside `/opt/polymarket-insider`
- Run a one-off backend script: `./venv/bin/python -m backend.<module>` from repo root

---

## Architecture (high level)

- **FastAPI** app (`backend/main.py`, ~1900 lines) — REST API + serves frontend as static files + APScheduler for periodic jobs.
- **Vanilla JS frontend** (`frontend/`) — no build step. Cache-bust by bumping `?v=N` on `<link>`/`<script>` tags after editing.
- **JSONL append-only journals** in `data/` — `agent_thinking.jsonl`, `paper_trades.json`, `tracked_trades.json`, `watched_wallets.json`. Trade journal (real money) is in a separate JSONL handled by `backend/trade_journal.py`.
- **AI model**: DeepSeek `deepseek/deepseek-chat-v3-0324` via OpenRouter (~$0.10/day). Old setup: Anthropic Haiku (~$2/day). Config keys in `.env`: `OPENROUTER_API_KEY` (preferred) or `ANTHROPIC_API_KEY` (legacy fallback).
- **Singleton pattern**: most modules export a module-level instance (`detector`, `journal`, `tracker`, `auto_seller`, `ai_agent`, etc.). Import from `backend.<module>` not `backend.<module>.ClassName()`.

---

## Backend module map (`backend/`)

| File | Lines | What it does |
| ---- | ----- | ------------ |
| `main.py` | 1886 | FastAPI app, ~90 endpoints, APScheduler bootstrap, scan loop, dedupe |
| `ai_agent.py` | 1359 | The autonomous bot: cycle every 15min, evaluates 7 strategies, places real orders. **Dual-source dedupe** (live + journal) added 2026-05 |
| `detectors.py` | 728 | Suspicion scoring engine (8 signals → 0-100 score, severity cap by trade size) |
| `integrations.py` | 660 | External data: 13D/13G filings, insider buys, politicians, etc. |
| `polymarket_client.py` | 635 | Async HTTP client for Gamma / CLOB / Data APIs |
| `ai_prompts.py` | 487 | System + per-strategy prompts. Strategy 7 (PIGGYBACK) was fixed 2026-05 to prevent fading insiders |
| `strategy_engine.py` | 440 | Legacy non-AI strategy runner. **Disabled** (`strategy_enabled=False`); replaced by `ai_agent.py` |
| `trade_tracker.py` | 430 | Watches tracked trades, fires sell triggers |
| `stocks_data.py` | 430 | Politician trades, Form 4 insider buys, 13D, WSB buzz, watchlist |
| `auto_seller.py` | 420 | Auto-exit logic: TP/SL/timeout, retries on `order_version_mismatch` (1.5s/3s/6s, 4 attempts) |
| `notifications.py` | 409 | Postmark email + Telegram + webhook fan-out |
| `backtester.py` | 397 | Historical case replay |
| `paper_trader.py` | 360 | Copy-trade simulator (no real money) |
| `copy_trader.py` | 351 | Live copy-trade execution |
| `trade_audit.py` | 327 | **Deep sanity audit** — dupes, P&L anomalies, theme concentration, sizing collapse, fade-vs-piggyback, burst clusters. See workflow doc |
| `leaderboard.py` | 325 | Top traders + ☆ watchlist |
| `intel_feeds.py` | 282 | Newsletters (Matt Levine / Money Stuff etc.) |
| `crypto_data.py` | 260 | Funding rates, basis, spreads |
| `reddit_data.py` | 256 | WSB scraping |
| `trade_analysis.py` | 255 | P&L by strategy / pattern / stake bucket — the "Learn from History" backend |
| `trade_failures.py` | 250 | Failure triage — re-runs failed trades through current pre-flight |
| `daily_summary.py` | 241 | 09:00 UTC social-media-ready recap |
| `models.py` | 175 | Pydantic models (Trade, WalletProfile, SuspiciousTrade, …) |
| `trade_journal.py` | 173 | Append-only JSONL real-money journal. **`get_open_positions()` aggregates duplicate ENTERs** (fix 2026-05) |
| `risk_manager.py` | – | `has_open_position()`, exposure caps, balance floor |
| `config.py` | – | Pydantic settings reading `.env`. All thresholds + limits live here |
| `sec_data.py` | – | SEC EDGAR fetchers |
| `auditor_data.py` | – | Audit firm metadata |

---

## Frontend page map (`frontend/`)

| Page | URL | What it does |
| ---- | --- | ------------ |
| `index.html` | `/` | Insider alert feed — auto-refreshes every 30s |
| `agent.html` | `/agent` | Bot dashboard: thinking history, theses, positions, **3 manual buttons** |
| `strategy.html` | `/strategy` | Legacy strategy engine view (disabled) |
| `copy.html` | `/copy` | Copy-trader status + watched traders |
| `trades.html` | `/trades` | Tracked manual trades |
| `research.html` | `/research` | Research ideas list + newsletter intel |
| `playbook.html` | `/playbook` | Dutch playbook for all 3 boards |
| `stocks.html` | `/stocks` | Politicians, WSB, watchlist, 13D, insider buys |
| `crypto.html` | `/crypto` | Funding, basis, spreads |

**Cache-bust convention**: when you edit CSS or JS, bump `?v=N` on the `<link>`/`<script>` tag in the corresponding HTML.

---

## Scheduled jobs (`backend/main.py` lifespan)

| Job | Cadence | Note |
| --- | ------- | ---- |
| `scan_for_suspicious_activity` | 5min | Detection engine |
| `tracker.check_watched_traders` | 5min | Watched wallets |
| `paper_trader.check_and_copy_new_trades` | 2min | Copy-trade simulator |
| `paper_trader.update_prices` | 10min | Mark-to-market |
| `trade_tracker.check_targets` | 10s | TP/SL/timeout firing |
| `strategy_engine.run_cycle` | 2min | **Disabled** in config |
| `ai_agent.run_cycle` | 15min | The autonomous bot |
| `run_daily_summary` | 09:00 UTC | Social-media recap |
| `check_politician_alerts` | 30min | Starred-politicians watch |
| `run_weekly_trade_analysis` | Mon 08:00 UTC | Weekly Telegram digest |

**Disabled**: WSB email alerts (per user 2026-05-08, "ze zijn vervelend"). Function `check_wsb_alerts()` kept intact, `/api/stocks/wsb-watchlist-overlap` endpoint still works for on-demand dashboard checks.

---

## Manual analysis flows (the 3 dashboard buttons)

User strongly prefers **click-to-trigger** over cron for analysis. Reason: findings need human judgment; daily robot pings get ignored. See `memory/feedback_manual_analysis_workflows.md`.

| Flow | Button | Endpoint | Module | What it surfaces |
| ---- | ------ | -------- | ------ | ---------------- |
| Failure triage | 🔧 Triage Failures | `POST /api/agent/triage-failures` | `trade_failures.py` | Re-checks failed trades against current pre-flight chain. Flags new failure modes |
| Performance review | 📊 Learn from History | `POST /api/agent/learn-from-history` | `trade_analysis.py` | P&L by strategy / signal-pattern / stake bucket |
| Trade audit | 🔍 Audit Trades | `POST /api/agent/audit-trades` | `trade_audit.py` | Dupes, P&L anomalies, theme concentration, sizing collapse, fade-vs-piggyback, bursts |

Each: dashboard button → POST endpoint → in-memory analysis → Telegram digest + JSON popup. **Run every 2-3 days manually.** Audit workflow doc: `docs/trade-audit-workflow.md`.

### What "evaluate trades" means to the user

When user says "evaluate trades" / "of dat er gekke dingen zijn", they want the **sanity audit** (`trade_audit.py`), not a P&L summary. Always lead with what's broken, not what's working. Severity: 🚨 critical → ⚠️ warning → ℹ️ info.

The May 2026 validation: P&L aggregates said "71% win rate, net -$2.76" (sounded fine). Deep audit revealed 9× duplicate-trade bug, fade-vs-piggyback issue, 50% theme concentration — all real bugs the aggregate hid.

---

## Wallet config (CRITICAL)

Polymarket uses **proxy wallets** (smart contracts created by Magic.link). The private key in `.env` derives to a different EOA than the proxy shown in the UI.

- **Proxy wallet (UI, holds funds)**: `0x04851d53c9b32f1818e0d962ba2852ba3f1ef429`
- **EOA (from private key, signs)**: `0x9514bC832b1c7AEaE146b482c2fcB4DcA31E2393`

**ClobClient must be initialized with `signature_type=1` AND `funder=proxy_address`.**
- `signature_type=1` = Polymarket proxy wallet
- `signature_type=0` = direct EOA (returns $0 balance for proxy wallets, orders fail)

Same applies to `get_balance_allowance()` — pass `signature_type=1` in params.

Export private key from: https://reveal.magic.link/polymarket

---

## Risk limits (hard caps — do NOT raise without explicit user approval)

In `backend/config.py`:

```
agent_max_per_trade      = $10
agent_max_total_exposure = $100
strategy_balance_floor   = $840   # refuse trades if balance would drop below this
strategy_max_open_positions = 5
```

Asymmetric-bet pattern (Paris-temperature case):
```
asymmetric_max_price_cents     = 3.0    # ≤3c entry (≤3% implied)
asymmetric_min_notional        = $50    # raised from $5 — retail Eurovision noise was firing
asymmetric_min_payoff_ratio    = 30x
```

Severity floors for alerts:
```
$5k+ → CRITICAL    $2k+ → HIGH    $500+ → MEDIUM    $100+ → any alert
```

---

## Recent fixes (history we should not repeat)

### 2026-04-03: 9× Iran duplicate-trade bug (the big one)
**Symptom**: Bot bought "US forces enter Iran by Dec 31?" 9× at $1.05 each ($9.45 burned).

**Root cause**: `ai_agent._execute_trades()` only checked `self._live_positions` (substring match on market_question). Polymarket's live API filters dust positions ($1 at 76c = 1.4 shares = below dust threshold). So between cycles the just-bought position wasn't visible → bot re-bought.

**Fix** (commit `7ca1a8f`): Dual-source dedupe before placing every trade:
1. Check `self._live_positions` (substring match, current cycle's snapshot)
2. Check `journal.get_open_positions()` by market_question (in-memory journal)
3. Post token-id resolve: `journal.has_open_position(token_id)` for exact-match

**Downstream P&L anomaly bug**: `journal.get_open_positions()` overwrote prior ENTERs on the same `token_id`, so aggregated Polymarket `cashPnl` was matched against a single $1.05 stake → `|pnl| > stake × 1.5`. Fixed by aggregating across duplicate ENTERs (`amount_usd`, `shares`, `_entries_aggregated` counter).

### 2026-05: PIGGYBACK confusion in strategy 7
Bot was fading insiders on some asymmetric trades. Fixed in `ai_prompts.py` strategy 7 with explicit "PIGGYBACK MEANS: BUY THE SAME SIDE THE INSIDER IS BUYING" + concrete examples (Bitcoin YES @1c, Cruz NO @1c) + "NEVER FADE the insider" warning.

### 2026-05: Order-version-mismatch retry
Added retry-with-backoff (1.5s / 3s / 6s, max 4 attempts) in `auto_seller.py` for `order_version_mismatch` errors.

### 2026-05: Asymmetric floor raised
`asymmetric_min_notional` $5 → $50. Retail $20-30 Eurovision/longshot bets were firing as "insider asymmetric". Real insider asymmetric bets (Paris weather) were $30+ AND from fresh wallets with no other activity.

---

## Stocks watchlist (Sandisk-pattern shortlist, seeded 2026-05-11)

28 tickers across 6 buckets (per Sandisk-as-biggest-SP500-grower-2025 framework):

| Lens | Tickers |
| ---- | ------- |
| Spin-offs | SOLV ATMU VLTO GEV KVUE |
| Semi pick-and-shovel (AI 2nd/3rd derivative) | ENTG MKSI ONTO MOD MTRN |
| Power/Nuclear AI-infra utilities | VST CCJ TLN NRG ETR |
| Magic-formula candidates | HEI BWXT FIX TPL |
| Hidden balance-sheet optionality | SMR OKLO STEM AVAV RKLB |
| Black-swan hedges | IREN CIFR WULF NEM |

Stored in `data/` watchlist. Surfaces via:
- WSB-buzz cross-reference (`/api/stocks/wsb-watchlist-overlap`, on-demand)
- Politician-trade overlap (if a named politician buys one of these)
- `/stocks` dashboard for live monitoring

Email alerts off (per user); dashboard only.

---

## Gotchas

- **Port conflicts on Mac**: `lsof -ti:8000 | xargs kill -9` before starting locally.
- **Data API field names vary**: always probe multiple (`user` / `proxyWallet` / `maker`, `size` / `amount`). Code in `polymarket_client.py` does fallback chains.
- **VPS deploy stale staging**: sometimes `/opt/polymarket-insider` has uncommitted changes from prior shell-edits. `git stash -u` is safe before `git pull`.
- **No `python` on Mac**: always `./venv/bin/python`.
- **CSS/JS cache-busting**: every HTML edit that changes a referenced `.css`/`.js` must bump `?v=N`.
- **External routing**: Cloudflare → cloudflared tunnel → port 8000. Do NOT touch Caddy for external traffic.
- **WSB email alerts disabled** (May 2026). Function kept; only the scheduler job was removed.
- **Strategy engine disabled** in config (`strategy_enabled=False`). Don't re-enable accidentally; the AI agent replaces it.
- **`signature_type=1` everywhere** for CLOB calls — see Wallet section.

---

## Deploy procedure

**Current reality: manual SSH + git pull. GitHub Actions is broken.**

There is a workflow at `.github/workflows/deploy.yml` (Tailscale auth → SSH → `git reset --hard origin/main` → `docker compose up -d`), but it has been failing since **2026-03-28** because the GitHub repo secrets `TS_OAUTH_CLIENT_ID` and `TS_OAUTH_SECRET` are empty/expired. Last successful run was before that date. To revive it, mint new Tailscale OAuth credentials and add them to GitHub repo secrets.

**Until that's fixed, deploy is two steps:**

```bash
# 1. From local (Mac):
git push origin main

# 2. From local, deploy to VPS:
ssh root@100.102.30.80
cd /opt/polymarket-insider
git fetch origin && git reset --hard origin/main
docker compose up -d --build
docker compose logs -f --tail=50    # verify startup
```

**Implications**:
- `git push` alone does NOT deploy. You must SSH + pull. The user often expects auto-deploy ("build and deploy") — be explicit that you've done both steps.
- The VPS has occasional stale untracked files from manual debugging. `git reset --hard` is safer than `git pull` because it wipes those.
- Never edit code directly on the VPS. The next deploy will wipe it.

**Verifying a deploy**:
```bash
ssh root@100.102.30.80 'cd /opt/polymarket-insider && git log --oneline -1 && docker compose ps'
curl -s https://polymarket.ai-tigers.com/api/stats | jq .total_alerts   # smoke test
```

The user expects: "build and deploy" unless told otherwise. If you ship code → push **and** SSH-deploy, then verify.

---

## User profile

- **Joris Falter** — Hinano Products BV / AI Tigers agency. Dutch + English mixed, fast typing with typos — infer intent.
- Prefers **action over discussion** — just build and deploy.
- Heavy plan-mode user for bigger features, then "Implement the following plan:".
- Wants **learnings saved in .md files** before closing conversations (this file is one of them).
- Asks for commit+push when satisfied.

---

## Useful commands (cheat-sheet)

```bash
# Local
./venv/bin/python run.py
./venv/bin/python -m backend.trade_audit            # run audit standalone

# Endpoint smoke tests
curl -s https://polymarket.ai-tigers.com/api/stats | jq
curl -s https://polymarket.ai-tigers.com/api/agent/status | jq
curl -sX POST https://polymarket.ai-tigers.com/api/agent/audit-trades | jq

# VPS
ssh root@100.102.30.80
cd /opt/polymarket-insider && docker compose logs -f --tail=100
docker compose ps
docker compose restart insider-detector

# Stocks watchlist
curl -s https://polymarket.ai-tigers.com/api/stocks/watchlist | jq
```

---

## Pointers — read these when context demands it

- `docs/trading-philosophy.md` — why this exists, three-board structure
- `docs/polymarket-strategies.md` — strategies 1-7 detail
- `docs/stocks-strategies.md` — stocks board logic
- `docs/crypto-strategies.md` — crypto board
- `docs/trade-audit-workflow.md` — how to use the audit button + historical findings
- `docs/research/` — research notes (single-name-vs-broad-based, Paris weather, 0xricker, etc.)
- `frontend/playbook.html` — Dutch playbook in production
